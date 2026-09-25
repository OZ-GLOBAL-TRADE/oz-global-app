from types import SimpleNamespace

from sqlalchemy import select

from conftest import new_req
from jarvis import jarvis_chat, pipeline as pl, seed, services as sv


class _TextBlock:
    type = "text"

    def __init__(self, text): self.text = text


class _ToolUseBlock:
    type = "tool_use"

    def __init__(self, id, name, input): self.id, self.name, self.input = id, name, input


class _FakeMessages:
    def __init__(self, script): self.script, self.calls = list(script), []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        stop_reason, content = self.script.pop(0)
        return SimpleNamespace(stop_reason=stop_reason, content=content)


class _FakeClient:
    def __init__(self, script): self.messages = _FakeMessages(script)


def test_ask_without_api_key_returns_friendly_message(s, world, monkeypatch):
    monkeypatch.setattr(jarvis_chat, "_client", None)
    monkeypatch.setattr(jarvis_chat.config, "get_config_val", lambda *a, **k: "")
    reply, pending = jarvis_chat.ask(s, world["eren"], [], "merhaba")
    assert "CLAUDE_API_KEY" in reply and pending is None


def test_ask_runs_tool_then_returns_final_text(s, world, monkeypatch):
    req = new_req(s, world)  # TTRA_REQ_17, ESC 10 + Motor 6
    fake = _FakeClient([
        ("tool_use", [_ToolUseBlock("call_1", "get_req", {"req_kodu": req.code})]),
        ("end_turn", [_TextBlock(f"{req.code} şu anda Talep aşamasında.")]),
    ])
    monkeypatch.setattr(jarvis_chat, "client", lambda: fake)
    reply, pending = jarvis_chat.ask(s, world["eren"], [], f"{req.code} hangi aşamada?")
    assert reply == f"{req.code} şu anda Talep aşamasında." and pending is None
    assert len(fake.messages.calls) == 2
    tool_result = fake.messages.calls[1]["messages"][-1]["content"][0]
    assert '"asama": "1. Talep"' in tool_result["content"]


def test_ask_reports_unknown_req_as_tool_error_not_crash(s, world, monkeypatch):
    fake = _FakeClient([
        ("tool_use", [_ToolUseBlock("call_1", "get_req", {"req_kodu": "YOK_REQ_99"})]),
        ("end_turn", [_TextBlock("Böyle bir REQ bulamadım.")]),
    ])
    monkeypatch.setattr(jarvis_chat, "client", lambda: fake)
    reply, pending = jarvis_chat.ask(s, world["eren"], [], "YOK_REQ_99 nerede?")
    assert reply == "Böyle bir REQ bulamadım." and pending is None
    tool_result = fake.messages.calls[1]["messages"][-1]["content"][0]
    assert "hata" in tool_result["content"]


def test_ask_surfaces_pending_action_but_never_executes_it_itself(s, world, monkeypatch):
    eren, broker = world["eren"], world["broker"]
    req = new_req(s, world)
    seed._progress(s, req.id, "gumruk", eren, broker)
    fake = _FakeClient([
        ("tool_use", [_ToolUseBlock("call_1", "propose_advance_req", {"req_kodu": req.code})]),
        ("end_turn", [_TextBlock(f"{req.code}'ü ilerletmek üzereyim, onaylar mısınız?")]),
    ])
    monkeypatch.setattr(jarvis_chat, "client", lambda: fake)
    reply, pending = jarvis_chat.ask(s, eren, [], f"{req.code}'ü ilerlet")
    assert "onaylar mısınız" in reply
    assert pending == {"onay_gerekiyor": True, "eylem": "advance_req", "parametreler": {"req_kodu": req.code},
                       "aciklama": f"{req.code}'ü '3. Gümrük & Lojistik' aşamasından '4. Teklif' aşamasına ilerletmek"}
    assert sv.get_req(s, eren, req_id=req.id).stage == "gumruk"  # yalnızca öneri: veri hiç değişmedi


def test_execute_action_actually_advances_and_respects_gate(s, world):
    eren = world["eren"]
    req = new_req(s, world)
    jarvis_chat.execute_action(s, eren, "advance_req", {"req_kodu": req.code})
    assert sv.get_req(s, eren, req_id=req.id).stage == "fiyat"  # talep -> fiyat: kapısız

    blocked = jarvis_chat.execute_action(s, eren, "advance_req", {"req_kodu": req.code})
    assert blocked.startswith("❌") and sv.get_req(s, eren, req_id=req.id).stage == "fiyat"  # birim alış girilmeden ilerleyemez

    sv.save_line_values(s, eren, req, "unit_cost", [{"id": l.id, "value": 10} for l in req.lines])
    ok = jarvis_chat.execute_action(s, eren, "advance_req", {"req_kodu": req.code})
    assert ok.startswith("✅") and sv.get_req(s, eren, req_id=req.id).stage == "gumruk"


def test_execute_action_update_shipment(s, world):
    admin = world["admin"]
    shp = sv.create_shipment(s, admin, awb_no="23512345678", carrier="Turkish Cargo")
    result = jarvis_chat.execute_action(s, admin, "update_shipment",
                                        {"kargo_kodu": shp.code, "current_location": "Istanbul Havalimanı"})
    assert result.startswith("✅")
    assert sv.get_shipment(s, admin, code=shp.code).current_location == "Istanbul Havalimanı"


def test_req_detail_hides_margin_and_quote_from_broker_but_not_manager(s, world):
    eren, broker = world["eren"], world["broker"]
    req = new_req(s, world)
    seed._progress(s, req.id, "karar", eren, broker)  # "teklif" aşamasının kendi işlemlerinin (marj, teklif no) çalışması için bir sonraki hedefe ilerlet
    req = sv.get_req(s, eren, req_id=req.id)

    manager_view = jarvis_chat._req_detail(req, eren)
    assert manager_view["kar_marji_pct"] == 20.0 and "son_teklif" in manager_view

    broker_view = jarvis_chat._req_detail(req, broker)
    assert "kar_marji_pct" not in broker_view and "son_teklif" not in broker_view and "po_numarasi" not in broker_view
    assert broker_view["urunler"][0]["birim_alis"] is not None  # gümrükçü birim alışı zaten fiyat sekmesinde görür


def test_greeting_uses_ask_with_empty_history_and_falls_back_without_client(s, world, monkeypatch):
    eren = world["eren"]
    monkeypatch.setattr(jarvis_chat, "_client", None)
    monkeypatch.setattr(jarvis_chat.config, "get_config_val", lambda *a, **k: "")
    assert "CLAUDE_API_KEY" in jarvis_chat.greeting(s, eren)

    captured = {}

    def fake_ask(s_, actor_, history, prompt):
        captured["history"], captured["prompt"] = history, prompt
        return "Merhaba! 3 aktif REQ var.", None

    monkeypatch.setattr(jarvis_chat, "client", lambda: object())  # greeting() only checks truthiness before delegating to ask()
    monkeypatch.setattr(jarvis_chat, "ask", fake_ask)
    assert jarvis_chat.greeting(s, eren) == "Merhaba! 3 aktif REQ var."
    assert captured["history"] == [] and "company_overview" in captured["prompt"]


def test_company_overview_reports_bottleneck_and_hides_money_from_broker(s, world):
    eren, broker = world["eren"], world["broker"]
    r1 = new_req(s, world, "eren")
    seed._progress(s, r1.id, "karar", eren, broker)  # bir REQ'i ilerlet: teklif/kâr verisi ve aşama dağılımı oluşsun
    new_req(s, world, "eren")  # ikinci REQ "talep" aşamasında kalsın

    manager_view = jarvis_chat._tool_company_overview(s, eren, {})
    assert manager_view["TOPLAM_aktif_req_sayisi"] == 2
    breakdown = manager_view[jarvis_chat.STAGE_BREAKDOWN_KEY]
    assert sum(breakdown.values()) == 2  # aşama dağılımının toplamı, TOPLAM_aktif_req_sayisi'na eşit olmalı
    assert breakdown["1. Talep"] == 1 and breakdown["5. Müşteri Kararı"] == 1  # her aşama kendi gerçek sayısını taşır
    assert "para_birimi_bazinda_teklif_kar" in manager_view and "USD" in manager_view["para_birimi_bazinda_teklif_kar"]

    broker_view = jarvis_chat._tool_company_overview(s, broker, {})
    assert "para_birimi_bazinda_teklif_kar" not in broker_view  # gümrükçüye kâr/teklif toplamı gösterilmez


def test_execute_action_full_pipeline_via_propose_style_actions(s, world):
    """execute_action ile bütün REQ döngüsünü (advance/decide/PO onayı/teklif iletildi/tam teslimat) yürütür —
    tıpkı test_full_golden_thread gibi ama Jarvis AI'ın gerçekten çağıracağı execute_action() üzerinden."""
    eren, broker = world["eren"], world["broker"]
    req = new_req(s, world)
    exec_ = lambda eylem, **p: jarvis_chat.execute_action(s, eren, eylem, {"req_kodu": req.code, **p})

    assert exec_("advance_req").startswith("✅")  # talep -> fiyat
    sv.save_line_values(s, eren, req, "unit_cost", [{"id": l.id, "value": 10} for l in req.lines])
    assert exec_("advance_req").startswith("✅")  # fiyat -> gumruk
    sv.save_line_values(s, broker, req, "unit_customs", [{"id": l.id, "value": 0} for l in req.lines])
    assert exec_("advance_req").startswith("✅")  # gumruk -> teklif
    sv.update_fields(s, eren, req, margin_pct=20.0)
    assert exec_("mark_quote_sent").startswith("✅")
    assert exec_("advance_req").startswith("✅")  # teklif -> karar
    assert exec_("decide", onaylandi=True, sebep="").startswith("✅")  # karar -> siparis
    assert exec_("set_po_approved", onaylandi=True).startswith("✅")
    assert exec_("advance_req").startswith("✅")  # siparis -> lojistik
    assert exec_("advance_req").startswith("✅")  # lojistik -> teslim
    assert exec_("create_full_delivery", delivered_by="", delivered_to="").startswith("✅")
    assert exec_("advance_req").startswith("✅")  # tüm ürünler tam teslim: tamamlanır
    assert sv.get_req(s, eren, req_id=req.id).status == "tamamlandi"


def test_execute_action_decide_reject_shelves_with_reason(s, world):
    eren, broker = world["eren"], world["broker"]
    req = new_req(s, world)
    seed._progress(s, req.id, "karar", eren, broker)
    result = jarvis_chat.execute_action(s, eren, "decide", {"req_kodu": req.code, "onaylandi": False, "sebep": "Bütçe yok"})
    assert result.startswith("✅")
    req = sv.get_req(s, eren, req_id=req.id)
    assert req.status == "rafa" and req.shelved_reason == "Bütçe yok"


def test_execute_action_move_back_shelve_reopen(s, world):
    eren, broker = world["eren"], world["broker"]
    req = new_req(s, world)
    seed._progress(s, req.id, "gumruk", eren, broker)
    assert jarvis_chat.execute_action(s, eren, "move_back", {"req_kodu": req.code, "sebep": "Yanlış fiyat"}).startswith("✅")
    assert sv.get_req(s, eren, req_id=req.id).stage == "fiyat"

    assert jarvis_chat.execute_action(s, eren, "shelve_req", {"req_kodu": req.code, "sebep": "Müşteri vazgeçti"}).startswith("✅")
    assert sv.get_req(s, eren, req_id=req.id).status == "rafa"

    assert jarvis_chat.execute_action(s, eren, "reopen_req", {"req_kodu": req.code}).startswith("✅")
    assert sv.get_req(s, eren, req_id=req.id).status == "aktif"


def test_execute_action_update_currency(s, world):
    eren = world["eren"]
    req = new_req(s, world)
    result = jarvis_chat.execute_action(s, eren, "update_currency", {"req_kodu": req.code, "para_birimi": "EUR"})
    assert result.startswith("✅") and sv.get_req(s, eren, req_id=req.id).currency == "EUR"


def test_execute_action_create_shipment_and_add_item(s, world):
    admin = world["admin"]
    req = new_req(s, world)  # ESC 10, Motor 6
    r1 = jarvis_chat.execute_action(s, admin, "create_shipment", {"awb_no": "23512345678", "tasiyici": "Turkish Cargo"})
    assert r1.startswith("✅") and "CRG_01" in r1

    proposal = jarvis_chat._tool_propose_add_shipment_item(s, admin, {"kargo_kodu": "CRG_01", "req_kodu": req.code, "urun_adi": "ESC"})
    assert proposal["onay_gerekiyor"] and proposal["parametreler"]["adet"] == 10

    r2 = jarvis_chat.execute_action(s, admin, "add_shipment_item", proposal["parametreler"])
    assert r2.startswith("✅")
    shp = sv.get_shipment(s, admin, code="CRG_01")
    assert len(shp.items) == 1 and shp.items[0].qty == 10


def test_propose_add_shipment_item_rejects_ambiguous_or_unknown_product(s, world):
    admin = world["admin"]
    req = new_req(s, world)  # ESC ve Motor içerir
    sv.create_shipment(s, admin)
    ambiguous = jarvis_chat._tool_propose_add_shipment_item(s, admin, {"kargo_kodu": "CRG_01", "req_kodu": req.code, "urun_adi": ""})
    assert "hata" in ambiguous  # boş arama: hiçbir üründe eşleşme yok (0 eşleşme de reddedilir)
    unknown = jarvis_chat._tool_propose_add_shipment_item(s, admin, {"kargo_kodu": "CRG_01", "req_kodu": req.code, "urun_adi": "yoktur-boyle-urun"})
    assert "hata" in unknown
    single = jarvis_chat._tool_propose_add_shipment_item(s, admin, {"kargo_kodu": "CRG_01", "req_kodu": req.code, "urun_adi": "ESC"})
    assert single["onay_gerekiyor"]


def test_execute_action_add_partner_and_add_product(s, world):
    admin = world["admin"]
    r1 = jarvis_chat.execute_action(s, admin, "add_partner", {"ad": "Yeni Müşteri A.Ş.", "tip": "musteri", "ulke": "Türkiye"})
    assert r1.startswith("✅")
    assert sv.list_partners(s, admin, customers=True)[-1].name == "Yeni Müşteri A.Ş."

    r2 = jarvis_chat.execute_action(s, admin, "add_product", {"ad": "Yeni Test Ürünü", "kategori": "Elektronik"})
    assert r2.startswith("✅")
    assert any(p.name == "Yeni Test Ürünü" for p in sv.list_products(s, admin))


def test_propose_decide_requires_reason_on_reject_and_propose_move_back_requires_reason(s, world):
    eren, broker = world["eren"], world["broker"]
    req = new_req(s, world)
    seed._progress(s, req.id, "karar", eren, broker)
    assert "hata" in jarvis_chat._tool_propose_decide(s, eren, {"req_kodu": req.code, "onaylandi": False})
    ok = jarvis_chat._tool_propose_decide(s, eren, {"req_kodu": req.code, "onaylandi": True})
    assert ok["onay_gerekiyor"]

    req2 = new_req(s, world)
    assert "hata" in jarvis_chat._tool_propose_move_back(s, eren, {"req_kodu": req2.code})  # sebepsiz + zaten ilk aşamada


def test_propose_create_full_delivery_blocks_wrong_stage_and_already_delivered(s, world):
    eren, broker = world["eren"], world["broker"]
    req = new_req(s, world)
    assert "hata" in jarvis_chat._tool_propose_create_full_delivery(s, eren, {"req_kodu": req.code})  # henüz teslim aşamasında değil

    seed._progress(s, req.id, "teslim", eren, broker)
    req = sv.get_req(s, eren, req_id=req.id)
    proposal = jarvis_chat._tool_propose_create_full_delivery(s, eren, {"req_kodu": req.code})
    assert proposal["onay_gerekiyor"]
    sv.create_delivery(s, eren, req, [{"line_id": l.id, "qty": l.qty} for l in req.lines])
    assert "hata" in jarvis_chat._tool_propose_create_full_delivery(s, eren, {"req_kodu": req.code})  # zaten tam teslim


def test_write_actions_never_mutate_when_only_proposed_not_executed(s, world):
    eren, broker = world["eren"], world["broker"]
    req = new_req(s, world)
    seed._progress(s, req.id, "gumruk", eren, broker)
    before = sv.get_req(s, eren, req_id=req.id).stage
    jarvis_chat._tool_propose_advance_req(s, eren, {"req_kodu": req.code})
    jarvis_chat._tool_propose_move_back(s, eren, {"req_kodu": req.code, "sebep": "test"})
    assert sv.get_req(s, eren, req_id=req.id).stage == before  # yalnızca öneri çağrıları: hiçbir şey değişmedi


def test_company_overview_bottleneck_ignores_near_zero_durations_and_reports_real_ones(s, world):
    """Gerçek bir kullanıcı hatasını yeniden üretir: 1. Talep gibi neredeyse tüm REQ'lerin bir noktada
    geçtiği bir aşama, ortalama süre neredeyse sıfır olsa bile en yüksek 'Adet'e sahip olabilir — bu bir
    darboğaz DEĞİLDİR. Yalnızca gerçekten >=1 gün süren bir aşama darboğaz olarak raporlanmalı."""
    from datetime import timedelta

    from jarvis.models import Event
    eren, broker = world["eren"], world["broker"]
    for _ in range(3):  # birkaç REQ'i hızlıca (aynı an, sıfıra yakın süreyle) "talep" aşamasından geçir
        seed._progress(s, new_req(s, world).id, "fiyat", eren, broker)

    overview = jarvis_chat._tool_company_overview(s, eren, {})
    key = [k for k in overview if k.startswith("en_buyuk_darbogaz")][0]
    assert overview[key] is None  # tüm geçişler anlık: gerçek bir darboğaz yok

    # Bir REQ'i "fiyat" aşamasında gerçekten 3 gün bekletmiş gibi simüle et: "fiyat"a GİRİŞ anını (yani
    # "talep"ten çıkış event'ini) 3 gün geriye al — süre, bu event'ten "fiyat"tan çıkış event'ine kadar
    # geçen zaman olarak hesaplanıyor (bkz. analytics.stage_durations).
    slow_req = new_req(s, world)
    seed._progress(s, slow_req.id, "gumruk", eren, broker)
    entry_event = s.scalars(select(Event).where(Event.req_id == slow_req.id, Event.from_stage == "talep")).first()
    entry_event.created_at = entry_event.created_at - timedelta(days=3)
    s.commit()

    overview2 = jarvis_chat._tool_company_overview(s, eren, {})
    bottleneck = overview2[key]
    assert bottleneck is not None and bottleneck["asama"] == "2. Fiyat Araştırması" and bottleneck["ortalama_bekleme_gunu"] >= 1.0
    count_key = [k for k in bottleneck if k.startswith("bu_asamadan_BUGUNE")][0]
    assert bottleneck[count_key] == 1  # yalnızca bu REQ o aşamadan geçti — "şu an orada kaç REQ var" ile karıştırılmamalı


def test_tool_list_reqs_respects_visibility_and_filters(s, world):
    eren, beyza, broker = world["eren"], world["beyza"], world["broker"]
    r1 = new_req(s, world, "eren")
    r2 = new_req(s, world, "beyza")
    # GEÇİCİ (kullanıcı yetkilendirme modülüne kadar): yöneticiler artık sahiplikten bağımsız tüm REQ'leri görür.
    out = jarvis_chat._tool_list_reqs(s, eren, {})
    assert out["toplam"] == 2 and {r["kod"] for r in out["reqler"]} == {r1.code, r2.code}

    out_broker = jarvis_chat._tool_list_reqs(s, broker, {})
    assert out_broker["toplam"] == 0  # broker "talep" aşamasındaki REQ'leri göremez

    out2 = jarvis_chat._tool_list_reqs(s, eren, {"arama": "yok-boyle-bir-sey"})
    assert out2["toplam"] == 0


def test_daily_briefing_without_key_returns_plain_facts(s, world, monkeypatch):
    monkeypatch.setattr(jarvis_chat, "client", lambda: None)
    out = jarvis_chat.daily_briefing(s, world["admin"], ["Aktif REQ: 3.", "Karar bekleyen: X_REQ_01"])
    assert "- Aktif REQ: 3." in out and "- Karar bekleyen: X_REQ_01" in out and "CLAUDE_API_KEY" in out
