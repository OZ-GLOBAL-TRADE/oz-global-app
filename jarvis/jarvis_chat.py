"""Jarvis AI sohbet asistanı. Claude'un tool-use'u ile services.py'deki okuma fonksiyonlarını çağırır;
rol bazlı görünürlük tek bir yerde (services.py) uygulanmış kalır, burada tekrarlanmaz.

Faz 2 — onay kapılı eylem alma: yazma araçları ("propose_*") hiçbir zaman doğrudan veri değiştirmez,
yalnızca "şunu yapmak istiyorum" diye bir öneri (onay_gerekiyor=True) döndürür. Gerçek işlem, kullanıcı
arayüzde açıkça onay düğmesine basınca execute_action() ile — modelin kendisinden tamamen bağımsız
olarak — çalışır. Bu, modelin kendi onayını sahtesini yazamamasını garanti eder (bkz. paylaşılan
Mark LII/JARVIS projesindeki core/confirm.py'nin aynı tasarım prensibi: onay token'ını arayüz üretir,
model değil)."""
import json

from jarvis import analytics, config, pipeline as pl, services as sv

MODEL_NAME = "claude-haiku-4-5-20251001"
MAX_TOOL_ROUNDS = 6
_client = None


def client():
    """Anthropic istemcisini ilk çağrıda kurar. Anahtar yoksa (ya da paket kurulu değilse) None döner."""
    global _client
    if _client is not None: return _client
    key = config.get_config_val("CLAUDE_API_KEY") or config.get_config_val("ANTHROPIC_API_KEY")
    if not key: return None
    try:
        import anthropic
    except ImportError:
        return None
    _client = anthropic.Anthropic(api_key=key)
    return _client


def _req_summary(req) -> dict:
    return {"kod": req.code, "musteri": req.customer.name, "sahibi": req.owner.name,
            "asama": pl.STAGE_BY_KEY[req.stage].label, "durum": pl.STATUS_LABELS[req.status],
            "para_birimi": req.currency, "guncelleme": req.updated_at.strftime("%Y-%m-%d %H:%M")}


def _req_detail(req, actor) -> dict:
    is_broker = actor.role == pl.CUSTOMS_BROKER
    data = {**_req_summary(req), "teslimat_tipi": req.delivery_type, "notlar": req.notes or "",
            "acilis": req.created_at.strftime("%Y-%m-%d"),
            "urunler": [{"urun": l.name, "adet": l.qty, "birim_alis": l.unit_cost, "birim_gumruk": l.unit_customs,
                        "birim_lojistik": l.unit_logistics} for l in req.lines]}
    if req.status == pl.SHELVED: data["rafa_kaldirma_sebebi"] = req.shelved_reason
    if not is_broker:
        data["kar_marji_pct"] = req.margin_pct
        data["po_numarasi"] = req.po_number
        data["musteri_karari"] = req.decision
        if req.quotes:
            last = req.quotes[-1]
            data["son_teklif"] = {"numara": last.number, "tutar": last.grand_total, "para_birimi": last.currency}
    if req.deliveries:
        data["teslimatlar"] = [{"numara": d.number, "tarih": d.issued_at.strftime("%Y-%m-%d")} for d in req.deliveries]
    return data


def _shipment_summary(shp) -> dict:
    return {"kod": shp.code, "awb": shp.awb_no, "tasiyici": shp.carrier, "lojistik_durumu": shp.logistics_status,
            "gumruk_statusu": shp.customs_status, "teslimat_tipi": shp.delivery_type, "teslimat_adresi": shp.delivery_address,
            "mevcut_konum": shp.current_location, "gcb_no": shp.gcb_no,
            "req_kodlari": sorted({item.req.code for item in shp.items})}


def _tool_list_reqs(s, actor, args) -> dict:
    query = (args.get("arama") or "").strip().lower()
    status = {"aktif": pl.ACTIVE, "tamamlandi": pl.DONE, "rafa": pl.SHELVED}.get(args.get("durum"))
    reqs = sv.visible_reqs(s, actor, status=status)
    if query:
        reqs = [r for r in reqs if query in r.code.lower() or query in r.customer.name.lower()]
    return {"toplam": len(reqs), "reqler": [_req_summary(r) for r in reqs[:30]]}


def _tool_get_req(s, actor, args) -> dict:
    try:
        req = sv.get_req(s, actor, code=args["req_kodu"])
    except sv.ServiceError as e:
        return {"hata": str(e)}
    return _req_detail(req, actor)


def _tool_list_shipments(s, actor, args) -> dict:
    query = (args.get("arama") or "").strip().lower()
    shipments = sv.list_shipments(s, actor)
    if query:
        shipments = [x for x in shipments if query in (x.code or "").lower() or query in (x.awb_no or "").lower()]
    return {"toplam": len(shipments), "kargolar": [_shipment_summary(x) for x in shipments[:30]]}


def _tool_get_shipment(s, actor, args) -> dict:
    try:
        shp = sv.get_shipment(s, actor, code=args["kargo_kodu"])
    except sv.ServiceError as e:
        return {"hata": str(e)}
    return _shipment_summary(shp)


STAGE_BREAKDOWN_KEY = "her_asamanin_KENDI_ayri_req_sayisi_bunlarin_TOPLAMI_yukaridaki_TOPLAM_aktif_req_sayisina_esittir"


def _tool_company_overview(s, actor, args) -> dict:
    """'Durum ne?' / 'genel durum özeti' gibi geniş sorular için: aşama dağılımı, darboğaz (Panel
    sayfasındaki aynı hesap: hangi aşamada REQ'ler ortalama en uzun bekliyor), kargo gümrük/lojistik
    tıkanıklıkları ve (gümrükçü hariç) para birimi bazında teklif/kâr toplamları."""
    is_broker = actor.role == pl.CUSTOMS_BROKER
    reqs = sv.visible_reqs(s, actor)
    active = [r for r in reqs if r.status == pl.ACTIVE]
    by_stage = {label: 0 for label in (pl.STAGE_BY_KEY[k].label for k in pl.STAGE_KEYS)}  # 1'den 8'e sabit sırada, hepsi 0'dan başlar
    for r in active:
        by_stage[pl.STAGE_BY_KEY[r.stage].label] += 1
    # "Adet" burada o aşamadan BUGÜNE KADAR geçmiş (from_stage event'i olan) REQ sayısıdır, o aşamada ŞU AN
    # bekleyen REQ sayısı DEĞİLDİR — ilk aşamalar (özellikle 1. Talep) neredeyse tüm REQ'lerin bir noktada
    # geçtiği aşama olduğu için bu sayı yanıltıcı şekilde yüksek çıkabilir. Yalnızca gerçekten anlamlı bir
    # ortalama süre (>= 1 gün) varsa darboğaz olarak raporla; yoksa "belirgin bir birikme yok" demek daha doğru.
    durations = analytics.stage_durations(s, reqs)
    slow = durations[durations["Adet"] > 0].sort_values("Ortalama Gün", ascending=False)
    bottleneck = None
    if not slow.empty and slow.iloc[0]["Ortalama Gün"] >= 1.0:
        bottleneck = {"asama": slow.iloc[0]["Aşama"], "ortalama_bekleme_gunu": float(slow.iloc[0]["Ortalama Gün"]),
                      "bu_asamadan_BUGUNE_KADAR_GECMIS_REQ_sayisi_su_an_orada_olan_sayisi_DEGIL": int(slow.iloc[0]["Adet"])}

    shipments = sv.list_shipments(s, actor)
    customs_pending = [x.code for x in shipments if x.customs_status != "Gümrükten Çekildi"]
    logistics_pending = [x.code for x in shipments if x.logistics_status != "Teslim Edildi"]

    data = {
        "TOPLAM_aktif_req_sayisi": len(active),
        STAGE_BREAKDOWN_KEY: by_stage,
        "tamamlanan_req": len([r for r in reqs if r.status == pl.DONE]),
        "rafa_kaldirilan_req": len([r for r in reqs if r.status == pl.SHELVED]),
        "en_buyuk_darbogaz_TEK_bir_asamayla_ilgilidir_diger_asamalari_etkilemez": bottleneck,
        "toplam_kargo": len(shipments), "gumrukte_bekleyen_kargo_sayisi": len(customs_pending),
        "yolda_lojistik_bekleyen_kargo_sayisi": len(logistics_pending),
    }
    if not is_broker:
        df = analytics.reqs_frame(active)
        priced = df[df["Teklif"].notna()]
        totals = {}
        for cur, grp in priced.groupby("Para Birimi"):
            offer, profit = float(grp["Teklif"].sum()), float(grp["Kâr"].sum())
            totals[cur] = {"toplam_teklif": round(offer, 2), "toplam_kar": round(profit, 2),
                          "maliyet_uzerinden_kar_orani_pct": round(profit / (offer - profit) * 100, 1) if offer > profit else None}
        data["para_birimi_bazinda_teklif_kar"] = totals
    return data


def _tool_rep_performance(s, actor, args) -> dict:
    """'Hangi temsilci/yönetici en çok satış yapıyor' gibi sorular için: her REQ sahibi başına aktif REQ
    sayısı ve (gümrükçü hariç) para birimi bazında toplam teklif/kâr. Tek tek REQ'leri elle saymak yerine
    bu aracı çağır. Yöneticinin kendisi yalnızca kendi REQ'lerini görüyorsa (rol kısıtı), sonuç da ona göredir."""
    is_broker = actor.role == pl.CUSTOMS_BROKER
    reqs = [r for r in sv.visible_reqs(s, actor) if r.status == pl.ACTIVE]
    by_owner_count = {}
    for r in reqs:
        by_owner_count[r.owner.name] = by_owner_count.get(r.owner.name, 0) + 1
    result = {"aktif_req_sayisi_temsilci_basina": by_owner_count}
    if not is_broker:
        df = analytics.reqs_frame(reqs)
        priced = df[df["Teklif"].notna()]
        by_owner_money = {}
        for (owner, cur), grp in priced.groupby(["Yönetici", "Para Birimi"]):
            by_owner_money.setdefault(owner, {})[cur] = {"toplam_teklif": round(float(grp["Teklif"].sum()), 2),
                                                          "toplam_kar": round(float(grp["Kâr"].sum()), 2)}
        result["temsilci_basina_teklif_kar"] = by_owner_money
    return result


def _propose(eylem: str, aciklama: str, **parametreler) -> dict:
    return {"onay_gerekiyor": True, "eylem": eylem, "parametreler": parametreler, "aciklama": aciklama}


def _tool_propose_advance_req(s, actor, args) -> dict:
    try:
        req = sv.get_req(s, actor, code=args.get("req_kodu", ""))
    except sv.ServiceError as e:
        return {"hata": str(e)}
    current = pl.STAGE_BY_KEY[req.stage].label
    nxt = pl.next_stage(req.stage)
    hedef = "tamamlanmış olacak" if nxt is None else f"'{pl.STAGE_BY_KEY[nxt].label}' aşamasına"
    return _propose("advance_req", f"{req.code}'ü '{current}' aşamasından {hedef} ilerletmek", req_kodu=req.code)


def _tool_propose_update_shipment(s, actor, args) -> dict:
    try:
        shp = sv.get_shipment(s, actor, code=args.get("kargo_kodu", ""))
    except sv.ServiceError as e:
        return {"hata": str(e)}
    fields = {}
    if args.get("lojistik_durumu"): fields["logistics_status"] = args["lojistik_durumu"]
    if args.get("gumruk_durumu"): fields["customs_status"] = args["gumruk_durumu"]
    if args.get("mevcut_konum"): fields["current_location"] = args["mevcut_konum"]
    if not fields:
        return {"hata": "Güncellenecek en az bir alan belirtilmeli: lojistik durumu, gümrük durumu ya da mevcut konum."}
    parts = ", ".join(f"{k}={v}" for k, v in fields.items())
    return _propose("update_shipment", f"{shp.code} kargosunu güncellemek: {parts}", kargo_kodu=shp.code, **fields)


def _tool_propose_move_back(s, actor, args) -> dict:
    try:
        req = sv.get_req(s, actor, code=args.get("req_kodu", ""))
    except sv.ServiceError as e:
        return {"hata": str(e)}
    sebep = (args.get("sebep") or "").strip()
    if not sebep: return {"hata": "Geri alma sebebi belirtilmeli."}
    onceki = pl.prev_stage(req.stage)
    if onceki is None: return {"hata": f"{req.code} zaten ilk aşamada, geri alınamaz."}
    return _propose("move_back", f"{req.code}'ü '{pl.STAGE_BY_KEY[req.stage].label}' aşamasından "
                    f"'{pl.STAGE_BY_KEY[onceki].label}' aşamasına geri almak (sebep: {sebep})", req_kodu=req.code, sebep=sebep)


def _tool_propose_shelve_req(s, actor, args) -> dict:
    try:
        req = sv.get_req(s, actor, code=args.get("req_kodu", ""))
    except sv.ServiceError as e:
        return {"hata": str(e)}
    sebep = (args.get("sebep") or "").strip()
    if not sebep: return {"hata": "Rafa kaldırma sebebi belirtilmeli."}
    return _propose("shelve_req", f"{req.code}'ü rafa kaldırmak (sebep: {sebep})", req_kodu=req.code, sebep=sebep)


def _tool_propose_reopen_req(s, actor, args) -> dict:
    try:
        req = sv.get_req(s, actor, code=args.get("req_kodu", ""))
    except sv.ServiceError as e:
        return {"hata": str(e)}
    if req.status != pl.SHELVED: return {"hata": f"{req.code} rafa kaldırılmış değil."}
    return _propose("reopen_req", f"{req.code}'ü yeniden açmak (rafadan çıkarmak)", req_kodu=req.code)


def _tool_propose_decide(s, actor, args) -> dict:
    try:
        req = sv.get_req(s, actor, code=args.get("req_kodu", ""))
    except sv.ServiceError as e:
        return {"hata": str(e)}
    approved = bool(args.get("onaylandi"))
    sebep = (args.get("sebep") or "").strip()
    if not approved and not sebep: return {"hata": "Reddedildiyse sebep belirtilmeli."}
    aciklama = f"{req.code}: müşteri kararını 'onaylandı' olarak kaydedip Sipariş aşamasına geçirmek" if approved \
        else f"{req.code}: müşteri kararını 'reddedildi' olarak kaydedip rafa kaldırmak (sebep: {sebep})"
    return _propose("decide", aciklama, req_kodu=req.code, onaylandi=approved, sebep=sebep)


def _tool_propose_set_po_approved(s, actor, args) -> dict:
    try:
        req = sv.get_req(s, actor, code=args.get("req_kodu", ""))
    except sv.ServiceError as e:
        return {"hata": str(e)}
    approved = bool(args.get("onaylandi"))
    fiil = "vermek" if approved else "geri almak"
    return _propose("set_po_approved", f"{req.code} için Çin ofisine satın alma onayını {fiil}", req_kodu=req.code, onaylandi=approved)


def _tool_propose_mark_quote_sent(s, actor, args) -> dict:
    try:
        req = sv.get_req(s, actor, code=args.get("req_kodu", ""))
    except sv.ServiceError as e:
        return {"hata": str(e)}
    return _propose("mark_quote_sent", f"{req.code}'ün teklifini 'müşteriye iletildi' olarak işaretlemek "
                    "(güncel içerikle eşleşen teklif yoksa otomatik yeni numara üretilir)", req_kodu=req.code)


def _tool_propose_update_currency(s, actor, args) -> dict:
    try:
        req = sv.get_req(s, actor, code=args.get("req_kodu", ""))
    except sv.ServiceError as e:
        return {"hata": str(e)}
    currency = (args.get("para_birimi") or "").strip().upper()
    if currency not in pl.CURRENCIES: return {"hata": f"Geçersiz para birimi. Geçerli: {', '.join(pl.CURRENCIES)}."}
    return _propose("update_currency", f"{req.code}'ün para birimini {req.currency} → {currency} olarak düzeltmek",
                    req_kodu=req.code, para_birimi=currency)


def _tool_propose_create_full_delivery(s, actor, args) -> dict:
    try:
        req = sv.get_req(s, actor, code=args.get("req_kodu", ""))
    except sv.ServiceError as e:
        return {"hata": str(e)}
    if req.stage != "teslim": return {"hata": f"{req.code} henüz Teslim aşamasında değil."}
    rows = [{"line_id": l.id, "qty": l.qty - pl.delivered_qty(req, l.id)} for l in req.lines]
    rows = [r for r in rows if r["qty"] > 0]
    if not rows: return {"hata": f"{req.code}'deki tüm ürünler zaten tam teslim edilmiş."}
    ozet = ", ".join(f"{r['qty']:g} adet" for r in rows)
    return _propose("create_full_delivery", f"{req.code} için kalan tüm ürünleri tek teslimatla kapatmak ({ozet})",
                    req_kodu=req.code, delivered_by=(args.get("teslim_eden") or ""), delivered_to=(args.get("teslim_alan") or ""))


def _tool_propose_create_shipment(s, actor, args) -> dict:
    awb = (args.get("awb_no") or "").strip()
    carrier = (args.get("tasiyici") or "").strip() or (pl.detect_carrier(awb) if awb else "")
    aciklama = "Yeni bir kargo (CRG) kaydı oluşturmak" + (f" (AWB {awb}, {carrier})" if awb else " (AWB henüz girilmedi)")
    return _propose("create_shipment", aciklama, awb_no=awb, tasiyici=carrier)


def _tool_propose_add_shipment_item(s, actor, args) -> dict:
    try:
        shp = sv.get_shipment(s, actor, code=args.get("kargo_kodu", ""))
        req = sv.get_req(s, actor, code=args.get("req_kodu", ""))
    except sv.ServiceError as e:
        return {"hata": str(e)}
    urun = (args.get("urun_adi") or "").strip().lower()
    matches = [l for l in req.lines if urun in l.name.lower()] if urun else []
    if len(matches) != 1:
        return {"hata": f"'{args.get('urun_adi', '')}' ürünü {req.code}'de net eşleşmedi ({len(matches)} eşleşme). "
                        f"REQ'deki ürünler: {[l.name for l in req.lines]}"}
    line = matches[0]
    info = next(r for r in sv.shippable_lines(s, actor, req, exclude_shipment_id=shp.id) if r["line"].id == line.id)
    qty = float(args["adet"]) if args.get("adet") else info["remaining"]
    if qty <= 0 or qty > info["remaining"]:
        return {"hata": f"Geçersiz adet; {line.name} için kalan (henüz kargoya eklenmemiş) adet: {info['remaining']:g}."}
    return _propose("add_shipment_item", f"{shp.code} kargosuna {req.code}'den {line.name} ürününden {qty:g} adet eklemek",
                    kargo_kodu=shp.code, req_line_id=line.id, adet=qty)


def _tool_propose_add_partner(s, actor, args) -> dict:
    name = " ".join((args.get("ad") or "").split())
    if not name: return {"hata": "Ad boş olamaz."}
    tip = args.get("tip", "musteri")
    aciklama = f"'{name}' adında yeni bir {'müşteri' if tip == 'musteri' else 'tedarikçi'} eklemek"
    return _propose("add_partner", aciklama, ad=name, tip=tip, adres=(args.get("adres") or ""),
                    vergi_no=(args.get("vergi_no") or ""), email=(args.get("email") or ""), ulke=(args.get("ulke") or ""))


def _tool_propose_add_product(s, actor, args) -> dict:
    name = " ".join((args.get("ad") or "").split())
    if not name: return {"hata": "Ürün adı boş olamaz."}
    return _propose("add_product", f"'{name}' adında yeni bir ürün kataloğa eklemek", ad=name,
                    kategori=(args.get("kategori") or ""), gtip=(args.get("gtip") or ""),
                    son_alis=args.get("son_alis"))


def _tool_list_partners(s, actor, args) -> dict:
    kind = args.get("tip", "musteri")
    partners = sv.list_partners(s, actor, customers=kind == "musteri", suppliers=kind == "tedarikci")
    return {"toplam": len(partners), "kayitlar": [{"ad": p.name, "kisa_kod": p.short_code, "ulke": p.country} for p in partners[:40]]}


def _tool_list_products(s, actor, args) -> dict:
    query = (args.get("arama") or "").strip().lower()
    products = sv.list_products(s, actor)
    if query: products = [p for p in products if query in p.name.lower()]
    return {"toplam": len(products), "urunler": [{"ad": p.name, "kategori": p.category, "gtip": p.hs_code, "son_alis": p.last_cost} for p in products[:40]]}


TOOLS = [
    {"name": "company_overview", "description": "'Durum ne?', 'genel özet', 'şirketin durumu ne' gibi geniş/toplu sorular için tek çağrıda "
     "tüm resmi verir: aşama dağılımı, en büyük darboğaz (hangi aşamada REQ'ler ortalama en uzun bekliyor), kargo/gümrük tıkanıklıkları, "
     "ve (yetki varsa) para birimi bazında toplam teklif/kâr. Bu tür sorularda önce bunu çağır, list_reqs'i tek tek REQ ayrıntısı gerekmedikçe kullanma.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "list_reqs", "description": "Görebildiği REQ'leri (taleplerin) özet listesini döndürür; isteğe bağlı durum ve metin araması ile filtrelenebilir.",
     "input_schema": {"type": "object", "properties": {
         "durum": {"type": "string", "enum": ["aktif", "tamamlandi", "rafa"], "description": "Boş bırakılırsa tümü."},
         "arama": {"type": "string", "description": "REQ kodu veya müşteri adında geçen metin."}}}},
    {"name": "get_req", "description": "Tek bir REQ'in tüm ayrıntılarını (ürünler, aşama, teslimat, varsa teklif/kar marjı) döndürür.",
     "input_schema": {"type": "object", "properties": {"req_kodu": {"type": "string"}}, "required": ["req_kodu"]}},
    {"name": "list_shipments", "description": "Görebildiği kargoları (CRG) özetiyle listeler; AWB veya kod ile aranabilir.",
     "input_schema": {"type": "object", "properties": {"arama": {"type": "string"}}}},
    {"name": "get_shipment", "description": "Tek bir kargonun (CRG kodu ile) tüm ayrıntılarını döndürür.",
     "input_schema": {"type": "object", "properties": {"kargo_kodu": {"type": "string"}}, "required": ["kargo_kodu"]}},
    {"name": "list_partners", "description": "Müşteri veya tedarikçi listesini döndürür.",
     "input_schema": {"type": "object", "properties": {"tip": {"type": "string", "enum": ["musteri", "tedarikci"]}}}},
    {"name": "list_products", "description": "Ürün kataloğunu döndürür; ürün adında geçen metinle aranabilir.",
     "input_schema": {"type": "object", "properties": {"arama": {"type": "string"}}}},
    {"name": "rep_performance", "description": "'Hangi temsilci/yönetici en çok satış yapıyor', 'kim kaç REQ yönetiyor' gibi "
     "sorularda tek çağrıda temsilci bazlı dağılımı verir; REQ'leri tek tek sayma.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "propose_advance_req", "description": "Bir REQ'i bir sonraki aşamaya ilerletmeyi ÖNERİR — hemen uygulamaz, "
     "kullanıcı arayüzde açıkça onaylamalı. Kullanıcı 'ilerlet / bir sonraki aşamaya geçir / tamamla' gibi bir komut "
     "verdiğinde bunu çağır, sonra kullanıcıya arayüzdeki onay düğmesine basması gerektiğini söyle.",
     "input_schema": {"type": "object", "properties": {"req_kodu": {"type": "string"}}, "required": ["req_kodu"]}},
    {"name": "propose_update_shipment", "description": "Bir kargonun lojistik/gümrük durumunu ya da mevcut konumunu "
     "güncellemeyi ÖNERİR — hemen uygulamaz, kullanıcı arayüzde açıkça onaylamalı. Yalnızca kullanıcının belirttiği "
     "alanları gönder.",
     "input_schema": {"type": "object", "properties": {
         "kargo_kodu": {"type": "string"},
         "lojistik_durumu": {"type": "string", "enum": pl.LOGISTICS_STATUSES},
         "gumruk_durumu": {"type": "string", "enum": pl.CUSTOMS_STATUSES},
         "mevcut_konum": {"type": "string"}}, "required": ["kargo_kodu"]}},
    {"name": "propose_move_back", "description": "Bir REQ'i önceki aşamaya geri almayı ÖNERİR (sebep zorunlu) — hemen uygulamaz.",
     "input_schema": {"type": "object", "properties": {"req_kodu": {"type": "string"}, "sebep": {"type": "string"}},
                      "required": ["req_kodu", "sebep"]}},
    {"name": "propose_shelve_req", "description": "Bir REQ'i rafa kaldırmayı ÖNERİR (sebep zorunlu) — hemen uygulamaz.",
     "input_schema": {"type": "object", "properties": {"req_kodu": {"type": "string"}, "sebep": {"type": "string"}},
                      "required": ["req_kodu", "sebep"]}},
    {"name": "propose_reopen_req", "description": "Rafa kaldırılmış bir REQ'i yeniden açmayı ÖNERİR — hemen uygulamaz.",
     "input_schema": {"type": "object", "properties": {"req_kodu": {"type": "string"}}, "required": ["req_kodu"]}},
    {"name": "propose_decide", "description": "Müşteri Kararı aşamasındaki bir REQ için müşterinin onayladığını/reddettiğini "
     "kaydetmeyi ÖNERİR (onay -> Sipariş'e geçer, ret -> rafa kaldırılır, sebep zorunlu) — hemen uygulamaz.",
     "input_schema": {"type": "object", "properties": {"req_kodu": {"type": "string"}, "onaylandi": {"type": "boolean"},
                                                        "sebep": {"type": "string", "description": "Yalnızca ret durumunda zorunlu."}},
                      "required": ["req_kodu", "onaylandi"]}},
    {"name": "propose_set_po_approved", "description": "Sipariş aşamasındaki bir REQ için Çin ofisine satın alma onayını "
     "vermeyi/geri almayı ÖNERİR (onay verilince otomatik PO numarası üretilir) — hemen uygulamaz.",
     "input_schema": {"type": "object", "properties": {"req_kodu": {"type": "string"}, "onaylandi": {"type": "boolean"}},
                      "required": ["req_kodu", "onaylandi"]}},
    {"name": "propose_mark_quote_sent", "description": "Teklif aşamasındaki bir REQ'in teklifini müşteriye iletildi olarak "
     "işaretlemeyi ÖNERİR (gerekirse teklif PDF numarası otomatik oluşturulur) — hemen uygulamaz.",
     "input_schema": {"type": "object", "properties": {"req_kodu": {"type": "string"}}, "required": ["req_kodu"]}},
    {"name": "propose_update_currency", "description": "Bir REQ'in yanlışlıkla seçilmiş para birimini düzeltmeyi ÖNERİR "
     "(aşamadan bağımsız çalışır) — hemen uygulamaz.",
     "input_schema": {"type": "object", "properties": {"req_kodu": {"type": "string"},
                                                        "para_birimi": {"type": "string", "enum": pl.CURRENCIES}},
                      "required": ["req_kodu", "para_birimi"]}},
    {"name": "propose_create_full_delivery", "description": "Teslim aşamasındaki bir REQ'in KALAN tüm ürünlerini tek "
     "teslimatla (tam teslimat) kapatmayı ÖNERİR — hemen uygulamaz. Yalnızca kısmi/özel adetli bir teslimat DEĞİL, "
     "'REQ'i teslim et / tamamen teslim et' gibi tam teslimat isteklerinde kullan; kısmi teslimat mevcut arayüzden yapılır.",
     "input_schema": {"type": "object", "properties": {"req_kodu": {"type": "string"},
                                                        "teslim_eden": {"type": "string"}, "teslim_alan": {"type": "string"}},
                      "required": ["req_kodu"]}},
    {"name": "propose_create_shipment", "description": "Yeni bir kargo (CRG) kaydı oluşturmayı ÖNERİR — hemen uygulamaz.",
     "input_schema": {"type": "object", "properties": {"awb_no": {"type": "string"}, "tasiyici": {"type": "string"}}}},
    {"name": "propose_add_shipment_item", "description": "Bir REQ'deki belirli bir ürünü belirtilen adette bir kargoya "
     "eklemeyi ÖNERİR (adet verilmezse REQ'deki o üründen kalan tüm miktar eklenir) — hemen uygulamaz.",
     "input_schema": {"type": "object", "properties": {
         "kargo_kodu": {"type": "string"}, "req_kodu": {"type": "string"},
         "urun_adi": {"type": "string", "description": "REQ'deki ürün adında geçen metin, tam ad olmak zorunda değil."},
         "adet": {"type": "number"}}, "required": ["kargo_kodu", "req_kodu", "urun_adi"]}},
    {"name": "propose_add_partner", "description": "Yeni bir müşteri ya da tedarikçi eklemeyi ÖNERİR — hemen uygulamaz.",
     "input_schema": {"type": "object", "properties": {
         "ad": {"type": "string"}, "tip": {"type": "string", "enum": ["musteri", "tedarikci"]},
         "adres": {"type": "string"}, "vergi_no": {"type": "string"}, "email": {"type": "string"}, "ulke": {"type": "string"}},
         "required": ["ad", "tip"]}},
    {"name": "propose_add_product", "description": "Ürün kataloğuna yeni bir ürün eklemeyi ÖNERİR — hemen uygulamaz.",
     "input_schema": {"type": "object", "properties": {
         "ad": {"type": "string"}, "kategori": {"type": "string"}, "gtip": {"type": "string"}, "son_alis": {"type": "number"}},
         "required": ["ad"]}},
]
_HANDLERS = {"company_overview": _tool_company_overview, "list_reqs": _tool_list_reqs, "get_req": _tool_get_req,
            "list_shipments": _tool_list_shipments, "get_shipment": _tool_get_shipment,
            "list_partners": _tool_list_partners, "list_products": _tool_list_products,
            "rep_performance": _tool_rep_performance, "propose_advance_req": _tool_propose_advance_req,
            "propose_update_shipment": _tool_propose_update_shipment, "propose_move_back": _tool_propose_move_back,
            "propose_shelve_req": _tool_propose_shelve_req, "propose_reopen_req": _tool_propose_reopen_req,
            "propose_decide": _tool_propose_decide, "propose_set_po_approved": _tool_propose_set_po_approved,
            "propose_mark_quote_sent": _tool_propose_mark_quote_sent, "propose_update_currency": _tool_propose_update_currency,
            "propose_create_full_delivery": _tool_propose_create_full_delivery,
            "propose_create_shipment": _tool_propose_create_shipment, "propose_add_shipment_item": _tool_propose_add_shipment_item,
            "propose_add_partner": _tool_propose_add_partner, "propose_add_product": _tool_propose_add_product}


def _system_prompt(actor) -> str:
    return (f"Sen OZ Global Trade'in dış ticaret ERP'si içindeki Jarvis AI asistanısın. Şu an {actor.name} "
            f"({pl.ROLE_LABELS[actor.role]}) ile konuşuyorsun. Sorulara YALNIZCA sana verilen araçlarla çektiğin "
            "gerçek verilere dayanarak, kısa ve net (Türkçe) cevap ver; veri uydurma. Bir REQ/kargo koduna "
            "ihtiyacın varsa önce arama araçlarıyla bul.\n\n"
            "'Durum ne?', 'genel özet', 'şirketin durumu nasıl?' gibi geniş bir soru geldiğinde company_overview "
            "aracını çağır ve dönen veriden kısa (en fazla 6-8 satır) bir yönetici brifingi kur: (1) aktif/tamamlanan/"
            "rafa kaldırılan REQ sayıları, (2) varsa en büyük darboğaz (hangi aşamada en çok beklendiği) ve kargo "
            "tarafında gümrük/lojistikte bekleyen sayısı, (3) yetkin varsa para birimi bazında toplam teklif ve kâr, "
            "(4) 1-2 cümlelik somut bir tavsiye (örn. 'X aşamasında Y REQ birikmiş, önce onlara bakılmalı'). Sadece "
            "sayıları sıralama — kısa yorumla. Ham veriyi olduğu gibi dökme. Temsilci/yönetici bazlı satış/performans "
            "sorularında (örn. 'en çok satış yapan kim') REQ'leri tek tek incelemek yerine rep_performance aracını çağır.\n\n"
            "SAYILARI KARIŞTIRMA (sık yapılan bir hata): company_overview'daki TOPLAM aktif REQ sayısı ile aşama "
            "bazlı dağılımdaki alan AYRI şeylerdir. Aşama dağılımı sözlüğü 8 ayrı sayı içerir (her aşama için bir "
            "tane) ve bunların TOPLAMI toplam aktif REQ sayısına eşittir — TEK bir aşamanın sayısı asla toplama "
            "eşit olamaz (öyle görünüyorsa yanlış okumuşsundur, veriyi tekrar kontrol et). Örnek: 'toplam 20 aktif "
            "REQ var' derken '1. Talep aşamasında 20 REQ var' DEME, aşama dağılımındaki '1. Talep' anahtarının "
            "GERÇEK değerini (örn. 1 ya da 2) kullan.\n\n"
            "DARBOĞAZ ALANI: en_buyuk_darbogaz yalnızca gerçekten anlamlı (>=1 gün ortalama bekleme) bir aşama "
            "varsa dolu gelir; null ise 'belirgin bir birikme/darboğaz yok' de, bir şey uydurma. Doluysa bile "
            "içindeki REQ sayısı o aşamadan BUGÜNE KADAR GEÇMİŞ REQ sayısıdır (anahtar adı bunu açıkça söyler) — "
            "o aşamada ŞU AN bekleyen REQ sayısı DEĞİLDİR, aşama dağılımıyla karıştırma. 'Kaç REQ şu an bu "
            "aşamada bekliyor' sorusunun cevabı her zaman aşama dağılımı sözlüğündeki sayıdır, darboğazdaki değil.\n\n"
            "EYLEM ALMA: propose_ ile başlayan tüm araçlar (advance_req, move_back, shelve_req, reopen_req, decide, "
            "set_po_approved, mark_quote_sent, update_currency, create_full_delivery, create_shipment, add_shipment_item, "
            "add_partner, add_product) bir işlemi HEMEN uygulamaz, yalnızca öneri olarak kullanıcı arayüzüne düşürür; "
            "gerçek işlem ancak kullanıcı orada açıkça onaylarsa çalışır. Kullanıcı bir komut verirse ilgili propose_ "
            "aracını çağır, sonra ne yapmak istediğini kısaca söyleyip arayüzdeki onay/vazgeç düğmesini beklediğini "
            "belirt — 'yaptım' ya da 'tamamlandı' deme, çünkü sen değil kullanıcı onaylayınca gerçekleşir. Birden "
            "fazla eylem gerektiren bir istekte (örn. 'şunu onayla ve ilerlet') tek seferde yalnızca BİR propose_ "
            "aracı çağır, kullanıcı onayladıktan sonra bir sonraki adımı iste. Satır bazlı fiyatlama (birim maliyet, "
            "kâr marjı gibi tablo alanları) ve kısmi teslimat gibi ayrıntılı/tablo gerektiren işlemler için henüz bir "
            "araç yok — bu durumlarda kullanıcıyı ilgili sayfaya (Talepler/Kargo) yönlendir.")


def ask(s, actor, history: list[dict], user_message: str) -> tuple[str, dict | None]:
    """history: [{'role': 'user'|'assistant', 'content': str}, ...] — önceki turların düz metni (araç
    çağrıları turlar arası taşınmaz, her tur kendi içinde tamamlanır).
    Dönüş: (cevap metni, varsa onay bekleyen eylem — {'eylem', 'parametreler', 'aciklama'})."""
    c = client()
    if not c:
        return "⚠️ Jarvis AI için CLAUDE_API_KEY (veya ANTHROPIC_API_KEY) tanımlı değil. Ayarlar için CLAUDE.md'ye bakın.", None
    messages = [{"role": h["role"], "content": h["content"]} for h in history] + [{"role": "user", "content": user_message}]
    pending = None
    for _ in range(MAX_TOOL_ROUNDS):
        try:
            resp = c.messages.create(model=MODEL_NAME, max_tokens=1024, system=_system_prompt(actor), tools=TOOLS, messages=messages)
        except Exception as e:
            return f"⚠️ Jarvis AI'a ulaşılamadı: {e}", pending
        if resp.stop_reason != "tool_use":
            return "".join(b.text for b in resp.content if b.type == "text").strip() or "…", pending
        messages.append({"role": "assistant", "content": resp.content})
        results = []
        for block in resp.content:
            if block.type != "tool_use": continue
            handler = _HANDLERS.get(block.name)
            try:
                payload = handler(s, actor, block.input or {}) if handler else {"hata": f"Bilinmeyen araç: {block.name}"}
            except sv.ServiceError as e:
                payload = {"hata": str(e)}
            if isinstance(payload, dict) and payload.get("onay_gerekiyor"): pending = payload
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(payload, ensure_ascii=False, default=str)})
        messages.append({"role": "user", "content": results})
    return "⚠️ Bu soru çok fazla adım gerektirdi; daha spesifik sorar mısınız?", pending


def greeting(s, actor) -> str:
    """Uygulama açıldığında bir kerelik karşılama: company_overview'ı kullanıp kısa, samimi bir brifingle karşılar."""
    if not client():
        return f"Merhaba {actor.name}, hoş geldiniz. (Jarvis AI karşılaması için CLAUDE_API_KEY tanımlı değil.)"
    text, _ = ask(s, actor, [], "Bana kısa, samimi bir karşılama cümlesiyle başlayan ve company_overview aracını kullanan "
                              "güncel bir durum özeti ver. 3-4 cümleyi geçme.")
    return text


def daily_briefing(s, actor, facts: list[str]) -> str:
    """Panel'deki 'Günlük brifing üret' düğmesi. facts = analytics.briefing_facts (gerçek veriden, deterministik);
    AI yoksa ya da hata verirse bu maddeler olduğu gibi döner, varsa AI'a bağlam olarak verilir."""
    plain = "\n".join(f"- {f}" for f in facts)
    if not client():
        return plain + "\n\n_(Yorumlu brifing için CLAUDE_API_KEY tanımlanmalı; yukarıdaki maddeler doğrudan veriden.)_"
    prompt = ("Günlük yönetici brifingi hazırla. Önce company_overview ve rep_performance araçlarını kullan. Aşağıdaki "
              "gerçek veri maddelerini de dikkate al:\n" + plain + "\n\nBiçim (Markdown, kısa madde işaretleri): "
              "**Genel durum** (2-3 madde), **Dikkat gerektirenler** (bekleyen karar, iletilmemiş teklif, uzun süredir "
              "güncellenmeyen REQ'ler — REQ kodlarıyla), **Satış & kâr** (2 madde), **Bugün için öneriler** (en fazla 3). "
              "Sayı uydurma; veride olmayan bir şeyi söyleme.")
    text, _ = ask(s, actor, [], prompt)
    return text if not text.startswith("⚠️") else plain + f"\n\n_{text}_"


def _exec_advance_req(s, actor, p: dict) -> str:
    req = sv.get_req(s, actor, code=p["req_kodu"])
    sv.advance_req(s, actor, req)
    durum = pl.STAGE_BY_KEY[req.stage].label if req.status == pl.ACTIVE else pl.STATUS_LABELS[req.status]
    return f"{req.code} ilerletildi: şimdi '{durum}'."


def _exec_update_shipment(s, actor, p: dict) -> str:
    shp = sv.get_shipment(s, actor, code=p["kargo_kodu"])
    fields = {k: v for k, v in p.items() if k != "kargo_kodu"}
    sv.update_shipment(s, actor, shp, **fields)
    return f"{shp.code} güncellendi."


def _exec_move_back(s, actor, p: dict) -> str:
    req = sv.get_req(s, actor, code=p["req_kodu"])
    sv.move_back(s, actor, req, p["sebep"])
    return f"{req.code} '{pl.STAGE_BY_KEY[req.stage].label}' aşamasına geri alındı."


def _exec_shelve_req(s, actor, p: dict) -> str:
    req = sv.get_req(s, actor, code=p["req_kodu"])
    sv.shelve_req(s, actor, req, p["sebep"])
    return f"{req.code} rafa kaldırıldı."


def _exec_reopen_req(s, actor, p: dict) -> str:
    req = sv.get_req(s, actor, code=p["req_kodu"])
    sv.reopen_req(s, actor, req)
    return f"{req.code} yeniden açıldı."


def _exec_decide(s, actor, p: dict) -> str:
    req = sv.get_req(s, actor, code=p["req_kodu"])
    sv.decide(s, actor, req, bool(p.get("onaylandi")), p.get("sebep", ""))
    return f"{req.code} için müşteri kararı kaydedildi: şimdi '{pl.STAGE_BY_KEY[req.stage].label if req.status == pl.ACTIVE else pl.STATUS_LABELS[req.status]}'."


def _exec_set_po_approved(s, actor, p: dict) -> str:
    req = sv.get_req(s, actor, code=p["req_kodu"])
    sv.set_po_approved(s, actor, req, bool(p.get("onaylandi")))
    return f"{req.code} için satın alma onayı {'verildi' if p.get('onaylandi') else 'geri alındı'}."


def _exec_mark_quote_sent(s, actor, p: dict) -> str:
    req = sv.get_req(s, actor, code=p["req_kodu"])
    sv.mark_quote_sent(s, actor, req)
    return f"{req.code}'ün teklifi müşteriye iletildi olarak işaretlendi."


def _exec_update_currency(s, actor, p: dict) -> str:
    req = sv.get_req(s, actor, code=p["req_kodu"])
    sv.update_currency(s, actor, req, p["para_birimi"])
    return f"{req.code}'ün para birimi {p['para_birimi']} olarak düzeltildi."


def _exec_create_full_delivery(s, actor, p: dict) -> str:
    req = sv.get_req(s, actor, code=p["req_kodu"])
    rows = [{"line_id": l.id, "qty": l.qty - pl.delivered_qty(req, l.id)} for l in req.lines]
    rows = [r for r in rows if r["qty"] > 0]
    doc = sv.create_delivery(s, actor, req, rows, delivered_by=p.get("delivered_by", ""), delivered_to=p.get("delivered_to", ""))
    return f"{req.code} için {doc.number} numaralı teslimat makbuzu oluşturuldu."


def _exec_create_shipment(s, actor, p: dict) -> str:
    fields = {}
    if p.get("awb_no"): fields["awb_no"] = p["awb_no"]
    if p.get("tasiyici"): fields["carrier"] = p["tasiyici"]
    shp = sv.create_shipment(s, actor, **fields)
    return f"{shp.code} kodlu yeni kargo oluşturuldu."


def _exec_add_shipment_item(s, actor, p: dict) -> str:
    shp = sv.get_shipment(s, actor, code=p["kargo_kodu"])
    sv.add_shipment_item(s, actor, shp, p["req_line_id"], p["adet"])
    return f"{shp.code} kargosuna eklendi."


def _exec_add_partner(s, actor, p: dict) -> str:
    partner = sv.add_partner(s, actor, name=p["ad"], is_customer=p.get("tip") == "musteri", is_supplier=p.get("tip") == "tedarikci",
                             address=p.get("adres", ""), tax_no=p.get("vergi_no", ""), email=p.get("email", ""), country=p.get("ulke", ""))
    return f"'{partner.name}' ({partner.short_code}) kaydedildi."


def _exec_add_product(s, actor, p: dict) -> str:
    product = sv.add_product(s, actor, name=p["ad"], category=p.get("kategori", ""), hs_code=p.get("gtip", ""), last_cost=p.get("son_alis"))
    return f"'{product.name}' kataloğa eklendi."


_EXECUTORS = {"advance_req": _exec_advance_req, "update_shipment": _exec_update_shipment, "move_back": _exec_move_back,
              "shelve_req": _exec_shelve_req, "reopen_req": _exec_reopen_req, "decide": _exec_decide,
              "set_po_approved": _exec_set_po_approved, "mark_quote_sent": _exec_mark_quote_sent,
              "update_currency": _exec_update_currency, "create_full_delivery": _exec_create_full_delivery,
              "create_shipment": _exec_create_shipment, "add_shipment_item": _exec_add_shipment_item,
              "add_partner": _exec_add_partner, "add_product": _exec_add_product}


def execute_action(s, actor, eylem: str, parametreler: dict) -> str:
    """Kullanıcı arayüzde onayladıktan SONRA çağrılır — modelin kendisi bunu asla çağırmaz. sv.* içindeki
    rol/aşama kontrolleri burada da geçerlidir; yetkisiz ya da geçersiz bir işlem yine ServiceError verir."""
    executor = _EXECUTORS.get(eylem)
    if not executor: return f"⚠️ Bilinmeyen eylem: {eylem}"
    try:
        return "✅ " + executor(s, actor, parametreler)
    except sv.ServiceError as e:
        return f"❌ İşlem başarısız: {e}"
    except Exception as e:
        return f"❌ Beklenmeyen bir hata oldu: {e}"
