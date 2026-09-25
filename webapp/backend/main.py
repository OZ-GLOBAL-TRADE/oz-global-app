"""Yeni arayüz için ince API katmanı. İş mantığına dokunmaz — jarvis/services.py, pipeline.py, analytics.py
aynen kullanılır; burada yalnızca HTTP + gerçek oturum (çerez) katmanı var. Çalıştırma:
    py -m uvicorn main:app --reload --port 8600 --app-dir webapp/backend
"""
import io
import json
import sys
import urllib.parse
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # jarvis/ paketine erişmek için proje köküne çık

import openpyxl
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response
from starlette.middleware.sessions import SessionMiddleware

import catalog
import trash
import req_detail
from deps import get_actor
from jarvis import analytics, config, fx, jarvis_chat, pipeline as pl, services as sv
from jarvis.db import init_db, session_scope
from jarvis.delivery_pdf import render_delivery_pdf
from jarvis.models import DeliveryDoc, Event, QuoteDoc
from jarvis.quote_pdf import render_quote_pdf

TR_TZ = timezone(timedelta(hours=3))  # Türkiye sabit UTC+3 (yaz saati uygulaması yok)
STATUS_FILTERS = {"aktif": pl.ACTIVE, "tamamlanan": pl.DONE, "rafa": pl.SHELVED, "tumu": None}

# ---- Yapılandırma (ortam değişkenleri; canlıda Render vb. "Environment" bölümünden) ----
# SESSION_SECRET  : oturum çerezini imzalar; canlıda ZORUNLU (en az 32 karakter, rastgele). Yoksa canlı mod açılmaz.
# WEB_ORIGINS     : arayüzün adresi/adresleri (virgülle), CORS için. Örn: https://erp.ozglobaltrade.com
# COOKIE_SAMESITE : lax (varsayılan; arayüz ve API aynı alan adının alt alanlarındaysa yeter: erp.* ve api.ozglobaltrade.com)
#                   none (yalnızca arayüz ve API FARKLI alan adlarındaysa; çerez Secure olur — canlıda alt alan kullanın).
# JARVIS_DEV_MODE : canlıda 0 (çerez yalnızca HTTPS'de gönderilir). Yerelde 1 kalabilir.
_DEV_SECRET = "dev-only-change-me"
SESSION_SECRET = config.get_config_val("SESSION_SECRET", _DEV_SECRET)
if not config.DEV_MODE and (SESSION_SECRET == _DEV_SECRET or len(SESSION_SECRET) < 32):
    # Bilinen/kısa bir anahtarla canlıya çıkılırsa herkes geçerli oturum çerezi üretebilir: hiç başlatma.
    raise RuntimeError("Canlı modda (JARVIS_DEV_MODE=0) SESSION_SECRET en az 32 karakterlik rastgele bir değer olmalı.")
WEB_ORIGINS = [o.strip() for o in config.get_config_val("WEB_ORIGINS", "http://localhost:3000").split(",") if o.strip()]
COOKIE_SAMESITE = config.get_config_val("COOKIE_SAMESITE", "lax").lower()
if COOKIE_SAMESITE not in ("lax", "none", "strict"): raise RuntimeError("COOKIE_SAMESITE lax, none ya da strict olmalı.")
if COOKIE_SAMESITE == "none" and config.DEV_MODE:
    raise RuntimeError("COOKIE_SAMESITE=none çerezin Secure olmasını gerektirir: JARVIS_DEV_MODE=0 ile birlikte kullanın.")


@asynccontextmanager
async def lifespan(_app):
    # Streamlit uygulamasının açılışta yaptığı işin aynısı: eksik tabloları/sütunları hazırlar (idempotent, yalnızca ekler)
    init_db()
    yield


app = FastAPI(title="Jarvis API", lifespan=lifespan)

# Oturum: imzalı, HttpOnly çerezde yalnızca user_id tutulur (Streamlit'teki st.session_state'in aksine,
# tarayıcı sert yenilemesinde/yeni sekmede DÜŞMEZ — eski sürümün bilinen eksiğiydi).
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, same_site=COOKIE_SAMESITE,
                   https_only=not config.DEV_MODE, max_age=60 * 60 * 24 * 14)
app.add_middleware(CORSMiddleware, allow_origins=WEB_ORIGINS, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


app.include_router(catalog.router)
app.include_router(trash.router)


@app.get("/healthz")
def healthz():
    """Barındırma sağlayıcısının canlılık kontrolü için; veritabanına dokunmaz, oturum gerektirmez."""
    return {"ok": True}

@app.post("/api/login")
def login(request: Request, body: dict):
    with session_scope() as s:
        try:
            actor = sv.authenticate(s, body.get("username", ""), body.get("password", ""))
        except sv.ServiceError as e:
            raise HTTPException(401, str(e))
    request.session["user_id"] = actor.id
    return {"id": actor.id, "username": actor.username, "name": actor.name, "role": actor.role}


@app.post("/api/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@app.get("/api/me")
def me(actor: sv.Actor = Depends(get_actor)):
    return {"id": actor.id, "username": actor.username, "name": actor.name, "role": actor.role,
            "role_label": pl.ROLE_LABELS[actor.role]}


DISPLAY_CURRENCIES = ["USD", "EUR", "TRY"]


@app.get("/api/panel")
def panel(currency: str = "USD", actor: sv.Actor = Depends(get_actor)):
    """Panel sayfasının tüm verisi (Streamlit panel.py'nin karşılığı). Hesaplar jarvis.analytics'te; burada yalnızca JSON.
    `currency`: 'Teklif & Kâr' bölümünün gösterim para birimi (tüm teklifler güncel kurla buna çevrilir).
    Kâr/teklif verisi yalnızca teklif aşamasını görebilen rollere verilir (gümrükçüye `financials: null`)."""
    if currency not in DISPLAY_CURRENCIES: raise HTTPException(400, "Geçersiz para birimi.")
    with session_scope() as s:
        reqs = sv.visible_reqs(s, actor)
        df = analytics.reqs_frame(reqs)
        if df.empty: return {"empty": True, "scope_all": actor.role in (pl.ADMIN, pl.TRADE_MANAGER)}
        active = df[df["Durum"] == pl.ACTIVE]
        count = lambda *stages: int(active["Aşama"].isin(stages).sum())
        durations = analytics.stage_durations(s, reqs)
        lead = analytics.lead_time_days(s, reqs)
        slowest = durations[durations["Adet"] > 0].sort_values("Ortalama Gün", ascending=False)
        show_money = pl.can_view_stage(actor.role, "teklif")
        recent = [{"code": r.code, "customer": r.customer.name, "owner": r.owner.name,
                   "stage_label": pl.STAGE_BY_KEY[r.stage].label if r.status == pl.ACTIVE else pl.STATUS_LABELS[r.status],
                   "teklif": pl.quote_for_req(r).total if show_money and r.margin_pct is not None else None,
                   "currency": r.currency, "updated_at": r.updated_at.isoformat()} for r in reqs[:12]]
        return {
            "empty": False, "scope_all": actor.role in (pl.ADMIN, pl.TRADE_MANAGER),
            "cards": {"aktif_talep": len(active), "fiyat_bekleyen": count("talep", "fiyat"), "gumrukte": count("gumruk"),
                      "teklif_karar": count("teklif", "karar"), "siparis_lojistik": count("siparis", "lojistik", "teslim")},
            "done": int((df["Durum"] == pl.DONE).sum()), "shelved": int((df["Durum"] == pl.SHELVED).sum()),
            "lead_time": analytics.fmt_duration(lead) if lead else None,
            "per_stage": [{"key": st.key, "label": st.label, "count": int((active["Aşama"] == st.key).sum())} for st in pl.STAGES],
            "durations": {
                # Tüm ortalamalar 1 günden kısaysa grafik saat cinsinden çizilir (Streamlit'teki gibi)
                "in_hours": bool(durations["Ortalama Gün"].max() < 1),
                "rows": [{"label": r["Aşama"], "days": float(r["Ortalama Gün"]), "hours": float(r["Ortalama Saat"]),
                          "text": r["Süre"], "count": int(r["Adet"])} for _, r in durations.iterrows()],
                "slowest": ({"label": slowest.iloc[0]["Aşama"], "text": slowest.iloc[0]["Süre"]}
                            if not slowest.empty and slowest.iloc[0]["Ortalama Gün"] > 0 else None),
            },
            "financials": analytics.financial_summary(df, analytics.product_frame(reqs), currency, fx.get_rates("USD")) if show_money else None,
            "recent": recent,
        }


@app.post("/api/panel/briefing")
def panel_briefing(actor: sv.Actor = Depends(get_actor)):
    """'📰 Günlük brifing üret': gerçek veriden deterministik maddeler + (anahtar varsa) Claude yorumu. Anahtar yoksa/hata olursa
    maddeler olduğu gibi döner (jarvis_chat.daily_briefing bunu zaten yapar)."""
    with session_scope() as s:
        reqs = sv.visible_reqs(s, actor)
        if not reqs: raise HTTPException(400, "Henüz REQ yok.")
        facts = analytics.briefing_facts(reqs, datetime.now(timezone.utc))
        return {"text": jarvis_chat.daily_briefing(s, actor, facts),
                "generated_at": datetime.now(TR_TZ).strftime("%d.%m.%Y %H:%M")}

def _req_row(r, show_amount: bool) -> dict:
    row = {
        "code": r.code, "customer": r.customer.name, "owner": r.owner.name,
        "status": r.status, "stage": r.stage,
        "stage_label": pl.STAGE_BY_KEY[r.stage].label if r.status == pl.ACTIVE else pl.STATUS_LABELS[r.status],
        "waiting": pl.STAGE_BY_KEY[r.stage].waiting if r.status == pl.ACTIVE else None,
        "line_count": len(r.lines), "updated_at": r.updated_at.isoformat(),
        "teklif": None, "currency": r.currency,
    }
    if show_amount and r.margin_pct is not None:
        row["teklif"] = pl.quote_for_req(r).total
    return row


@app.get("/api/reqs")
def list_reqs(request: Request, status: str = "aktif", q: str = "", actor: sv.Actor = Depends(get_actor)):
    if status not in STATUS_FILTERS: raise HTTPException(400, "Geçersiz durum filtresi.")
    with session_scope() as s:
        reqs = sv.visible_reqs(s, actor)
        query = q.strip().lower()
        if query:
            reqs = [r for r in reqs if query in r.code.lower() or query in r.customer.name.lower()
                    or any(query in l.name.lower() for l in r.lines)]
        wanted = STATUS_FILTERS[status]
        reqs = [r for r in reqs if wanted is None or r.status == wanted]
        show_amount = pl.can_view_stage(actor.role, "teklif")
        return {"reqs": [_req_row(r, show_amount) for r in reqs], "can_view_amount": show_amount,
                "can_create": actor.role in pl.MANAGE_ROLES, "stages": [{"key": st.key, "label": st.label} for st in pl.STAGES]}


XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@app.post("/api/reqs/export")
def export_reqs(body: dict, actor: sv.Actor = Depends(get_actor)):
    """Seçili REQ'leri Excel'e aktarır (Streamlit'teki 'Seçilenleri indir'). Yalnızca kullanıcının zaten görebildiği
    REQ'ler (`visible_reqs`) dahil edilir; Teklif sütunu yalnızca teklif aşamasını görebilen rollere verilir. Teklif tutarı
    Streamlit'teki metin yerine sayısal hücredir (Excel'de toplanabilsin), para birimi ayrı sütundur."""
    codes = body.get("codes")
    if not isinstance(codes, list) or not codes or not all(isinstance(c, str) for c in codes) or len(codes) > 1000:
        raise HTTPException(400, "Dışa aktarılacak REQ seçin.")
    order = {c: i for i, c in enumerate(codes)}
    show_amount = pl.can_view_stage(actor.role, "teklif")
    with session_scope() as s:
        reqs = sorted((r for r in sv.visible_reqs(s, actor) if r.code in order), key=lambda r: order[r.code])
        if not reqs: raise HTTPException(404, "Seçili REQ bulunamadı.")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Talepler"
        ws.append(["REQ", "Müşteri", "Yönetici", "Aşama", "Kimde", "Kalem", "Güncelleme"] + (["Teklif", "Para Birimi"] if show_amount else []))
        for r in reqs:
            row = _req_row(r, show_amount)
            updated = r.updated_at if r.updated_at.tzinfo else r.updated_at.replace(tzinfo=timezone.utc)  # SQLite naive → UTC
            ws.append([row["code"], row["customer"], row["owner"], row["stage_label"], row["waiting"] or "-", row["line_count"],
                       updated.astimezone(TR_TZ).strftime("%d.%m.%Y %H:%M")] + ([row["teklif"], row["currency"]] if show_amount else []))
        for col, width in zip("ABCDEFGHI", (18, 30, 20, 24, 22, 8, 18, 14, 12)): ws.column_dimensions[col].width = width
        buf = io.BytesIO()
        wb.save(buf)
    return _download(buf.getvalue(), "talepler.xlsx", XLSX_TYPE)

# ---------------------------------------------------------------- yeni REQ (REQ'e bağlı olmayan endpoint'ler)

def _new_req_options(s, actor: sv.Actor) -> dict:
    """Yeni REQ diyaloğunun seçenekleri: müşteriler (her biri için bir sonraki otomatik REQ kodu ile), katalog, sabitler."""
    return {
        "customers": [{"id": c.id, "name": c.name, "short_code": c.short_code, "next_code": sv.next_req_code(s, c.id)}
                      for c in sv.list_partners(s, actor, customers=True)],
        "products": [{"id": p.id, "name": p.name, "hs_code": p.hs_code} for p in sv.list_products(s, actor)],
        "currencies": pl.CURRENCIES, "delivery_types": pl.DELIVERY_TYPES,
    }


@app.get("/api/new-req/options")
def new_req_options(actor: sv.Actor = Depends(get_actor)):
    if actor.role not in pl.MANAGE_ROLES: raise HTTPException(403, "REQ açma yetkiniz yok.")
    with session_scope() as s:
        return _new_req_options(s, actor)


@app.post("/api/customers")
def add_customer(body: dict, actor: sv.Actor = Depends(get_actor)):
    """Yeni REQ diyaloğundaki 'Yeni müşteri ekle' (talepler.py::_new_req_dialog ile aynı alanlar). Yenilenmiş seçenekleri döner."""
    seq = req_detail.to_float(body.get("req_seq"))
    if seq is not None and (seq < 0 or seq != int(seq)): raise HTTPException(400, "Son REQ no 0 ya da pozitif bir tam sayı olmalı.")
    with session_scope() as s:
        sv.add_partner(s, actor, name=_text(body, "name"), is_customer=True, short_code=_text(body, "short_code"),
                       req_seq=int(seq or 0), tax_no=_text(body, "tax_no"), address=_text(body, "address"))
        return _new_req_options(s, actor)


@app.post("/api/catalog-products")
def add_catalog_product_global(body: dict, actor: sv.Actor = Depends(get_actor)):
    with session_scope() as s:
        sv.add_product(s, actor, name=_text(body, "name"), hs_code=_text(body, "hs_code"))
        return _new_req_options(s, actor)


@app.post("/api/reqs")
def create_req(body: dict, actor: sv.Actor = Depends(get_actor)):
    """Yeni REQ açar; kod sunucuda atomik üretilir (`MÜŞTERİKODU_REQ_NN`). Ürün satırlarında adet açıkça verilmelidir
    (Streamlit'teki gibi sessizce 1'e düşmez)."""
    customer_id, items = body.get("customer_id"), _rows(body, "items")
    if not isinstance(customer_id, int): raise HTTPException(400, "Bir müşteri seçin.")
    chosen = []
    for r in items:
        if r.get("product_id") is None: continue  # ürünü seçilmemiş boş satır atılır
        q = req_detail.to_float(r.get("qty"))
        if not isinstance(r["product_id"], int) or q is None or q <= 0: raise HTTPException(400, "Seçili her ürünün adedi 0'dan büyük olmalı.")
        chosen.append((r["product_id"], q))
    with session_scope() as s:
        req = sv.create_req(s, actor, customer_id=customer_id, items=chosen, currency=body.get("currency") or "USD",
                            delivery_type=body.get("delivery_type") or pl.DELIVERY_TYPES[0], notes=_text(body, "notes"))
        return {"code": req.code}


def _download(data: bytes, filename: str, media_type: str) -> Response:
    """Her zaman 'attachment' + nosniff: kullanıcının yüklediği dosya (ör. .html) API'nin kendi adresinden, oturum çerezinin
    geçerli olduğu bir kökenden servis edildiği için tarayıcıda satır içi (inline) açılıp betik çalıştıramamalı."""
    return Response(data, media_type=media_type, headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{urllib.parse.quote(filename)}",
        "X-Content-Type-Options": "nosniff"})


@app.get("/api/reqs/{code}")
def get_req(code: str, actor: sv.Actor = Depends(get_actor)):
    with session_scope() as s:
        try:
            req = sv.get_req(s, actor, code=code)
        except sv.ServiceError as e:
            raise HTTPException(404, str(e))
        return req_detail.build(s, actor, req)


# ---------------------------------------------------------------- REQ yazma işlemleri
# Hepsi ince sarmalayıcıdır: yetki ve iş kuralı jarvis.services'te. İş kuralı hatası (ServiceError) 400 döner ve
# `errors` listesini taşır (ör. kapı eksikleri). Başarıda yenilenmiş REQ detayı döner; frontend durumu bununla değiştirir.

@app.exception_handler(sv.ServiceError)
def service_error_handler(request: Request, exc: sv.ServiceError):
    return JSONResponse(status_code=400, content={"detail": str(exc), "errors": exc.errors})


def _write(code: str, actor: sv.Actor, fn):
    with session_scope() as s:
        try:
            req = sv.get_req(s, actor, code=code)
        except sv.ServiceError as e:
            raise HTTPException(404, str(e))
        result = fn(s, req)
        if isinstance(result, str): code = result  # fn REQ kodunu değiştirdi (numara düzeltme): yenilenmiş REQ yeni kodla okunur
        s.expire_all()  # oturum expire_on_commit=False ile açık; servislerin dokunmadığı koleksiyonlar bayat kalmasın
        try:
            fresh = sv.get_req(s, actor, code=code)
        except sv.ServiceError:
            # İşlem başarılı ama REQ artık bu rolün görüş alanı dışında (ör. gümrükçü kendi aşamasını ilerletti — gümrükçü
            # yalnızca Gümrük/Lojistik aşamasındaki REQ'leri görür). Hata değil: frontend listeye döner.
            return {"hidden": True}
        return req_detail.build(s, actor, fresh)


def _text(body: dict, key: str) -> str:
    v = body.get(key)
    return v.strip() if isinstance(v, str) else ""


@app.post("/api/reqs/{code}/advance")
def advance_req(code: str, actor: sv.Actor = Depends(get_actor)):
    return _write(code, actor, lambda s, req: sv.advance_req(s, actor, req))


@app.post("/api/reqs/{code}/move-back")
def move_back(code: str, body: dict, actor: sv.Actor = Depends(get_actor)):
    return _write(code, actor, lambda s, req: sv.move_back(s, actor, req, _text(body, "reason")))


@app.post("/api/reqs/{code}/shelve")
def shelve_req(code: str, body: dict, actor: sv.Actor = Depends(get_actor)):
    return _write(code, actor, lambda s, req: sv.shelve_req(s, actor, req, _text(body, "reason")))


@app.post("/api/reqs/{code}/reopen")
def reopen_req(code: str, actor: sv.Actor = Depends(get_actor)):
    return _write(code, actor, lambda s, req: sv.reopen_req(s, actor, req))


@app.post("/api/reqs/{code}/decision")
def decide(code: str, body: dict, actor: sv.Actor = Depends(get_actor)):
    return _write(code, actor, lambda s, req: sv.decide(s, actor, req, bool(body.get("approved")), _text(body, "reason")))


@app.post("/api/reqs/{code}/siparis")
def save_siparis(code: str, body: dict, actor: sv.Actor = Depends(get_actor)):
    """talepler.py::_panel_siparis ile aynı adımlar: müşteri PO no'yu kaydet, satın alma onayı değiştiyse uygula,
    istenirse ilerlet. Adımlar sırayla çalışır ve ilk hatada durur (önceki adımlar zaten kaydedilmiş olur)."""
    def run(s, req):
        sv.update_fields(s, actor, req, customer_po_no=_text(body, "customer_po_no"))
        approved = bool(body.get("po_approved"))
        if approved != (req.po_approved_at is not None): sv.set_po_approved(s, actor, req, approved)
        if body.get("advance"): sv.advance_req(s, actor, req)
    return _write(code, actor, run)


def _rows(body: dict, key: str) -> list[dict]:
    rows = body.get(key)
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows): raise HTTPException(400, f"'{key}' listesi geçersiz.")
    return rows


@app.post("/api/reqs/{code}/req-number")
def fix_req_number(code: str, body: dict, actor: sv.Actor = Depends(get_actor)):
    """Başlıktaki '✏️ Düzelt': yalnızca SAYI değişir (önek müşterinin kısa kodu). Yanıttaki detayın `code` alanı yeni koddur
    (frontend eski adresten yenisine geçer)."""
    n = req_detail.to_float(body.get("number"))
    if n is None or n != int(n): raise HTTPException(400, "REQ numarası tam sayı olmalı.")
    return _write(code, actor, lambda s, req: sv.update_req_number(s, actor, req, int(n)))


@app.post("/api/reqs/{code}/currency")
def fix_currency(code: str, body: dict, actor: sv.Actor = Depends(get_actor)):
    return _write(code, actor, lambda s, req: sv.update_currency(s, actor, req, _text(body, "currency")))


@app.post("/api/reqs/{code}/qtys")
def fix_qtys(code: str, body: dict, actor: sv.Actor = Depends(get_actor)):
    """Adet düzeltme (Talep dışındaki aşamalarda 'Adetleri düzelt'). lines: [{id, qty}]; teslim edilen/kargoya ayrılan miktarın
    altına inilemez (serviste)."""
    lines = _rows(body, "lines")
    return _write(code, actor, lambda s, req: sv.update_line_qtys(
        s, actor, req, [{"id": r.get("id"), "qty": req_detail.to_float(r.get("qty"))} for r in lines]))


@app.post("/api/reqs/{code}/delete")
def delete_req(code: str, actor: sv.Actor = Depends(get_actor)):
    """REQ'i çöp kutusuna taşır (geri yüklenebilir). Yanıt {"hidden": true}: REQ artık görünmez, arayüz listeye döner."""
    return _write(code, actor, lambda s, req: sv.delete_req(s, actor, req))


@app.post("/api/reqs/{code}/customer")
def change_customer(code: str, body: dict, actor: sv.Actor = Depends(get_actor)):
    """REQ'i başka müşteriye taşır (REQ kodu DEĞİŞMEZ; kod için /req-number). Teklif/teslimat makbuzu varsa servis reddeder."""
    cid = body.get("customer_id")
    if not isinstance(cid, int): raise HTTPException(400, "Bir müşteri seçin.")
    return _write(code, actor, lambda s, req: sv.change_req_customer(s, actor, req, cid))


@app.post("/api/reqs/{code}/meta")
def update_meta(code: str, body: dict, actor: sv.Actor = Depends(get_actor)):
    """REQ notu ve/veya teslimat tipi (her aşamada). Gövdede yalnızca gönderilen alanlar değişir."""
    kw = {}
    if "notes" in body: kw["notes"] = body["notes"] if isinstance(body["notes"], str) else ""
    if "delivery_type" in body: kw["delivery_type"] = body["delivery_type"] if isinstance(body["delivery_type"], str) else ""
    if not kw: raise HTTPException(400, "Değiştirilecek bir alan gönderilmedi.")
    return _write(code, actor, lambda s, req: sv.update_req_meta(s, actor, req, **kw))


@app.post("/api/reqs/{code}/notes/{note_id}/delete")
def delete_note(code: str, note_id: int, actor: sv.Actor = Depends(get_actor)):
    """Not/görevi siler (gizler); yazan kişi ya da yönetici. Başka REQ'in notu bu adresle silinemez."""
    def run(s, req):
        event = s.get(Event, note_id)
        if not event or event.req_id != req.id: raise HTTPException(404, "Not bulunamadı.")
        sv.delete_note(s, actor, note_id)
    return _write(code, actor, run)


@app.post("/api/reqs/{code}/talep")
def save_talep(code: str, body: dict, actor: sv.Actor = Depends(get_actor)):
    """talepler.py::_panel_talep ile aynı adımlar: teslimat tipi + ürün satırları (+ istenirse ilerlet).
    items: [{id?, product_id, qty}] — ürünü seçilmemiş satırlar atılır, listede olmayan mevcut satırlar silinir."""
    items = _rows(body, "items")
    def run(s, req):
        sv.update_fields(s, actor, req, delivery_type=body.get("delivery_type"))
        sv.save_items(s, actor, req, [{"id": r.get("id"), "product_id": r.get("product_id"),
                                       "qty": req_detail.to_float(r.get("qty"))} for r in items])
        if body.get("advance"): sv.advance_req(s, actor, req)
    return _write(code, actor, run)


@app.post("/api/reqs/{code}/catalog-product")
def add_catalog_product(code: str, body: dict, actor: sv.Actor = Depends(get_actor)):
    """Katalogda olmayan ürünü hızlıca ekler (Talep panelindeki '＋ Katalogda olmayan ürün ekle'); REQ'e satır eklemez,
    yalnızca ürün listesi yenilenir."""
    name, hs = _text(body, "name"), _text(body, "hs_code")
    return _write(code, actor, lambda s, req: sv.add_product(s, actor, name=name, hs_code=hs))


@app.post("/api/reqs/{code}/deliveries")
def create_delivery(code: str, body: dict, actor: sv.Actor = Depends(get_actor)):
    """Teslimat makbuzu (kısmi/tam). rows: [{line_id, qty}]. REQ'i tamamlamak için ardından /advance çağrılır."""
    rows = _rows(body, "rows")
    return _write(code, actor, lambda s, req: sv.create_delivery(
        s, actor, req, [{"line_id": r.get("line_id"), "qty": req_detail.to_float(r.get("qty"))} for r in rows],
        _text(body, "delivered_by"), _text(body, "delivered_to")))


@app.post("/api/reqs/{code}/fiyat")
def save_fiyat(code: str, body: dict, actor: sv.Actor = Depends(get_actor)):
    """talepler.py::_panel_fiyat ile aynı adımlar: tedarikçi seçimi + birim alış, istenirse ilerlet.
    lines: [{id, unit_cost, supplier_id}]."""
    lines = _rows(body, "lines")
    def run(s, req):
        sv.save_line_suppliers(s, actor, req, [{"id": r.get("id"), "supplier_id": r.get("supplier_id")} for r in lines])
        sv.save_line_values(s, actor, req, "unit_cost", [{"id": r.get("id"), "value": req_detail.to_float(r.get("unit_cost"))} for r in lines])
        if body.get("advance"): sv.advance_req(s, actor, req)
    return _write(code, actor, run)


@app.post("/api/reqs/{code}/gumruk")
def save_gumruk(code: str, body: dict, actor: sv.Actor = Depends(get_actor)):
    """talepler.py::_panel_gumruk ile aynı adımlar. lines: [{id, unit_customs, unit_logistics}], costs: [{label, amount, kind}]."""
    lines, costs = _rows(body, "lines"), _rows(body, "costs")
    def run(s, req):
        sv.save_line_values(s, actor, req, "unit_customs", [{"id": r.get("id"), "value": req_detail.to_float(r.get("unit_customs"))} for r in lines])
        sv.save_line_values(s, actor, req, "unit_logistics", [{"id": r.get("id"), "value": req_detail.to_float(r.get("unit_logistics"))} for r in lines])
        sv.save_costs(s, actor, req, [{"label": r.get("label"), "amount": req_detail.to_float(r.get("amount")), "kind": r.get("kind")} for r in costs])
        if body.get("advance"): sv.advance_req(s, actor, req)
    return _write(code, actor, run)


@app.post("/api/reqs/{code}/teklif")
def save_teklif(code: str, body: dict, actor: sv.Actor = Depends(get_actor)):
    """talepler.py::_panel_teklif ile aynı adımlar. Önce alanlar + satır marjı/doğrudan fiyat kaydedilir, sonra `action`:
    'save' (yalnızca kaydet) | 'pdf' (teklif PDF'i oluştur) | 'sent' (iletildi işaretle ve Karar'a geç)."""
    t, lines, action = body.get("teklif"), _rows(body, "lines"), body.get("action", "save")
    if not isinstance(t, dict): raise HTTPException(400, "'teklif' alanı geçersiz.")
    if action not in ("save", "pdf", "sent"): raise HTTPException(400, "Geçersiz eylem.")
    f = req_detail.to_float
    if (f(t.get("valid_days")) or 0) < 1: raise HTTPException(400, "Geçerlilik en az 1 gün olmalı.")
    def run(s, req):
        # Alan adları Streamlit'tekiyle aynı; geçersiz/boş sayı None olur ve services.update_fields kuralları uygulanır
        sv.update_fields(s, actor, req, margin_pct=f(t.get("margin_pct")), logistics_margin_pct=f(t.get("logistics_margin_pct")),
                         tax_enabled=bool(t.get("tax_enabled")), tax_pct=f(t.get("tax_pct")) or 0.0,
                         valid_days=int(f(t.get("valid_days")) or 0), payment_terms=_text(t, "payment_terms"),
                         logistics_mode=t.get("logistics_mode"))
        sv.save_line_values(s, actor, req, "margin_pct", [{"id": r.get("id"), "value": f(r.get("margin_pct"))} for r in lines])
        sv.save_line_values(s, actor, req, "sale_price_override", [{"id": r.get("id"), "value": f(r.get("sale_price_override"))} for r in lines])
        if action == "pdf": sv.issue_quote(s, actor, req)
        elif action == "sent":
            sv.mark_quote_sent(s, actor, req)
            sv.advance_req(s, actor, req)
    return _write(code, actor, run)


@app.post("/api/reqs/{code}/preview")
def preview_calc(code: str, body: dict, actor: sv.Actor = Depends(get_actor)):
    """Kaydedilmemiş form değerleriyle canlı maliyet/teklif hesabı; hiçbir şey yazmaz. Yetkisiz rol teklif verisi almaz."""
    with session_scope() as s:
        try:
            req = sv.get_req(s, actor, code=code)
        except sv.ServiceError as e:
            raise HTTPException(404, str(e))
        return req_detail.preview(actor, req, body)


@app.post("/api/reqs/{code}/notes")
def add_note(code: str, body: dict, actor: sv.Actor = Depends(get_actor)):
    assignee = body.get("assignee_id")
    if assignee is not None and not isinstance(assignee, int): raise HTTPException(400, "Geçersiz kullanıcı.")
    return _write(code, actor, lambda s, req: sv.add_note(s, actor, req, _text(body, "text"), assignee_id=assignee))


def _task_action(code: str, task_id: int, actor: sv.Actor, action):
    def run(s, req):
        event = s.get(Event, task_id)
        if not event or event.req_id != req.id: raise HTTPException(404, "Görev bulunamadı.")
        action(s, actor, task_id)
    return _write(code, actor, run)


@app.post("/api/reqs/{code}/tasks/{task_id}/complete")
def complete_task(code: str, task_id: int, actor: sv.Actor = Depends(get_actor)):
    return _task_action(code, task_id, actor, sv.complete_task)


@app.post("/api/reqs/{code}/tasks/{task_id}/cancel")
def cancel_task(code: str, task_id: int, actor: sv.Actor = Depends(get_actor)):
    return _task_action(code, task_id, actor, sv.cancel_task)


@app.post("/api/reqs/{code}/attachments")
async def upload_attachment(code: str, request: Request, filename: str, actor: sv.Actor = Depends(get_actor)):
    """Ham gövde yükleme (multipart değil): dosya baytları gövdede, ad sorgu parametresinde, tür Content-Type'ta —
    ek bir bağımlılık (python-multipart) gerektirmez. Boyut sınırı gövde okunmadan önce Content-Length ile de kontrol edilir."""
    if int(request.headers.get("content-length") or 0) > pl.MAX_ATTACHMENT_BYTES:
        raise HTTPException(413, f"Dosya çok büyük (en fazla {pl.MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB).")
    data = await request.body()
    ctype = request.headers.get("content-type") or "application/octet-stream"
    return await run_in_threadpool(_write, code, actor, lambda s, req: sv.upload_req_attachment(s, actor, req, filename, ctype, data))


@app.delete("/api/reqs/{code}/attachments/{attachment_id}")
def delete_attachment(code: str, attachment_id: int, actor: sv.Actor = Depends(get_actor)):
    def run(s, req):
        att = sv.get_attachment(s, actor, attachment_id)
        if att.req_id != req.id: raise HTTPException(404, "Belge bulunamadı.")
        sv.delete_attachment(s, actor, attachment_id)
    return _write(code, actor, run)


@app.get("/api/attachments/{attachment_id}")
def download_attachment(attachment_id: int, actor: sv.Actor = Depends(get_actor)):
    with session_scope() as s:
        try:
            att = sv.get_attachment(s, actor, attachment_id)
            # get_attachment yalnızca şirketi kontrol eder; REQ dosyası için REQ'i görme yetkisi de şart
            if att.req_id is None: raise sv.ServiceError("Belge bulunamadı.")
            sv.get_req(s, actor, req_id=att.req_id)
        except sv.ServiceError as e:
            raise HTTPException(404, str(e))
        return _download(att.data, att.filename, att.content_type or "application/octet-stream")


@app.get("/api/quotes/{quote_id}/pdf")
def download_quote_pdf(quote_id: int, actor: sv.Actor = Depends(get_actor)):
    with session_scope() as s:
        doc = s.get(QuoteDoc, quote_id)
        if not doc or doc.company_id != actor.company_id or not pl.can_view_stage(actor.role, "teklif"):
            raise HTTPException(404, "Teklif bulunamadı.")
        try:
            sv.get_req(s, actor, req_id=doc.req_id)
        except sv.ServiceError as e:
            raise HTTPException(404, str(e))
        return _download(render_quote_pdf(json.loads(doc.snapshot)), f"{doc.number}.pdf", "application/pdf")


@app.get("/api/deliveries/{delivery_id}/pdf")
def download_delivery_pdf(delivery_id: int, actor: sv.Actor = Depends(get_actor)):
    with session_scope() as s:
        doc = s.get(DeliveryDoc, delivery_id)
        if not doc or doc.company_id != actor.company_id or not pl.can_view_stage(actor.role, "teslim"):
            raise HTTPException(404, "Teslimat makbuzu bulunamadı.")
        try:
            sv.get_req(s, actor, req_id=doc.req_id)
        except sv.ServiceError as e:
            raise HTTPException(404, str(e))
        return _download(render_delivery_pdf(json.loads(doc.snapshot)),
                         f"{doc.number.replace('/', '_')}.pdf", "application/pdf")
