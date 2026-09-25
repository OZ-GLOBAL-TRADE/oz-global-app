"""Yeni web arayüzünün API katmanı (webapp/backend) için regresyon testleri: gerçek HTTP yığını (FastAPI TestClient), geçici SQLite.
İş kuralları jarvis/ testlerinde; burada API'ye özgü şeyler sınanır — oturum, rol bazlı veri gizleme, hata biçimi (400 + errors),
yazma sonrası yenilenmiş detay, dışa aktarma, canlı-mod güvenlik korumaları."""
import importlib
import io
import os
import subprocess
import sys
from pathlib import Path

import openpyxl
import pytest
from fastapi.testclient import TestClient

from conftest import actor
from jarvis import config, services as sv

BACKEND = Path(__file__).resolve().parents[1] / "webapp" / "backend"
PASSWORD = "test-parola-123"
RATES = {"USD": 1.0, "EUR": 0.5, "TRY": 40.0}


@pytest.fixture
def api(s, monkeypatch):
    """`s` (conftest) geçici veritabanını kurar ve yapılandırır; burada uygulama aynı veritabanına bağlanır."""
    monkeypatch.setattr(config, "DEV_MODE", True)  # geliştirici makinede .env'de canlı mod açık olsa bile testler etkilenmesin
    sys.path.insert(0, str(BACKEND))
    main = importlib.import_module("main")
    monkeypatch.setattr(main.fx, "get_rates", lambda base="USD": RATES)  # ağa çıkma
    admin = actor(s, "yusuf.oz")
    for user in sv.list_users(s): sv.set_password(s, admin, user.id, PASSWORD)

    clients = []

    def login(username: str) -> TestClient:
        c = TestClient(main.app)
        c.__enter__()  # lifespan (init_db) çalışsın
        clients.append(c)
        assert c.post("/api/login", json={"username": username, "password": PASSWORD}).status_code == 200
        return c

    yield login
    for c in clients: c.__exit__(None, None, None)
    sys.path.remove(str(BACKEND))


def seed_req(admin_client, name="Test Müşteri A.Ş.", qty=4):
    """API'den müşteri + ürün + REQ açar; REQ kodunu döner."""
    r = admin_client.post("/api/customers", json={"name": name, "short_code": "TSTM", "req_seq": 0}).json()
    prod = admin_client.post("/api/catalog-products", json={"name": "Deneme Ürünü"}).json()["products"][0]
    customer = next(c for c in r["customers"] if c["name"] == name)
    res = admin_client.post("/api/reqs", json={"customer_id": customer["id"], "items": [{"product_id": prod["id"], "qty": qty}]})
    assert res.status_code == 200, res.text
    return res.json()["code"]


def to_gumruk(admin_client, code, unit_cost=10):
    """Talep → Fiyat → Gümrük aşamasına API üzerinden taşır (gümrükçünün GÖREBİLDİĞİ ilk aşama)."""
    admin_client.post(f"/api/reqs/{code}/advance")
    line = admin_client.get(f"/api/reqs/{code}").json()["lines"][0]
    res = admin_client.post(f"/api/reqs/{code}/fiyat", json={"lines": [{"id": line["id"], "unit_cost": unit_cost}], "advance": True})
    assert res.status_code == 200 and res.json()["stage"] == "gumruk", res.text
    return line


def to_teklif(admin_client, code, unit_cost=10):
    """Gümrük'ten de geçirip Teklif aşamasına taşır (gümrükçünün göremediği bir aşama)."""
    line = to_gumruk(admin_client, code, unit_cost)
    res = admin_client.post(f"/api/reqs/{code}/gumruk", json={"lines": [{"id": line["id"], "unit_customs": 0}], "costs": [], "advance": True})
    assert res.status_code == 200 and res.json()["stage"] == "teklif", res.text
    return line

# ---------------------------------------------------------------- oturum

def test_login_session_and_anonymous_access(api):
    anon = TestClient(sys.modules["main"].app)
    assert anon.get("/api/me").status_code == 401 and anon.get("/api/reqs").status_code == 401
    bad = anon.post("/api/login", json={"username": "yusuf.oz", "password": "yanlis"})
    assert bad.status_code == 401
    admin = api("yusuf.oz")
    me = admin.get("/api/me").json()
    assert me["username"] == "yusuf.oz" and me["role"] == "ADMIN"
    admin.post("/api/logout")
    assert admin.get("/api/me").status_code == 401


def test_healthz_needs_no_session(api):
    assert TestClient(sys.modules["main"].app).get("/healthz").json() == {"ok": True}


# ---------------------------------------------------------------- REQ: hata biçimi, kapı, gizleme

def test_new_req_gate_errors_and_refreshed_detail(api):
    admin = api("yusuf.oz")
    code = seed_req(admin)
    assert code == "TSTM_REQ_01"
    detail = admin.get(f"/api/reqs/{code}").json()
    assert detail["stage"] == "talep" and detail["can_advance"] and len(detail["lines"]) == 1

    # fiyat girilmeden Fiyat aşamasından çıkılamaz: 400 + tek tek eksikler
    assert admin.post(f"/api/reqs/{code}/advance").json()["stage"] == "fiyat"
    blocked = admin.post(f"/api/reqs/{code}/advance")
    assert blocked.status_code == 400 and blocked.json()["errors"] and "Birim alış" in blocked.json()["errors"][0]

    line = detail["lines"][0]
    ok = admin.post(f"/api/reqs/{code}/fiyat", json={"lines": [{"id": line["id"], "unit_cost": 10.5, "supplier_id": None}], "advance": True})
    assert ok.status_code == 200 and ok.json()["stage"] == "gumruk" and ok.json()["lines"][0]["unit_cost"] == 10.5  # yenilenmiş detay döner


def test_multistep_failure_keeps_earlier_steps_and_reports_gate(api):
    admin = api("yusuf.oz")
    code = seed_req(admin)
    admin.post(f"/api/reqs/{code}/advance")  # fiyat
    line = admin.get(f"/api/reqs/{code}").json()["lines"][0]
    r = admin.post(f"/api/reqs/{code}/fiyat", json={"lines": [{"id": line["id"], "unit_cost": None}], "advance": True})
    assert r.status_code == 400
    # başarısız ilerletmeye rağmen (boş fiyat) kayıt adımı çalıştı ve REQ aşamada kaldı
    assert admin.get(f"/api/reqs/{code}").json()["stage"] == "fiyat"


def test_broker_sees_no_pricing_data_and_cannot_manage(api):
    admin, broker = api("yusuf.oz"), api("gumruk.ofis")
    code = seed_req(admin)
    line = admin.get(f"/api/reqs/{code}").json()["lines"][0]
    admin.post(f"/api/reqs/{code}/advance")  # → fiyat
    admin.post(f"/api/reqs/{code}/fiyat", json={"lines": [{"id": line["id"], "unit_cost": 5}], "advance": True})  # → gümrük
    d = broker.get(f"/api/reqs/{code}").json()
    assert d["stage"] == "gumruk" and d["visible_stages"] == ["talep", "fiyat", "gumruk"]
    assert d["teklif"] is None and d["karar"] is None and d["siparis"] is None and d["teslim"] is None
    assert not d["can_manage"] and not d["can_shelve"] and not d["can_move_back"] and not d["can_fix"]
    assert broker.post(f"/api/reqs/{code}/shelve", json={"reason": "Bütçe yok"}).status_code == 400

    # gümrükçü kendi aşamasını ilerletince REQ görüş alanından çıkar: hata değil, {"hidden": true}
    res = broker.post(f"/api/reqs/{code}/gumruk", json={"lines": [{"id": line["id"], "unit_customs": 0}], "costs": [], "advance": True})
    assert res.status_code == 200 and res.json() == {"hidden": True}
    assert broker.get(f"/api/reqs/{code}").status_code == 404
    assert broker.post(f"/api/reqs/{code}/advance").status_code == 404


def test_preview_does_not_persist_and_hides_margins_from_broker(api):
    admin = api("yusuf.oz")
    code = seed_req(admin, qty=10)
    line = to_teklif(admin, code)
    before = admin.get(f"/api/reqs/{code}").json()["updated_at"]
    p = admin.post(f"/api/reqs/{code}/preview", json={"lines": [{"id": line["id"], "margin_pct": 50}], "teklif": {"margin_pct": 20, "tax_pct": 20, "tax_enabled": True, "logistics_mode": "dahil"}}).json()
    assert p["quote"]["total"] == 150.0 and p["quote"]["rows"][0]["margin_label"] == "%50"  # satır marjı varsayılanı geçer
    assert admin.get(f"/api/reqs/{code}").json()["updated_at"] == before  # önizleme hiçbir şey yazmaz


def test_attachment_download_is_forced_attachment_and_permission_checked(api):
    admin, broker = api("yusuf.oz"), api("gumruk.ofis")
    code = seed_req(admin)
    up = admin.post(f"/api/reqs/{code}/attachments?filename=x.html", content=b"<script>1</script>", headers={"Content-Type": "text/html"})
    att = up.json()["attachments"][0]
    dl = admin.get(f"/api/attachments/{att['id']}")
    # kullanıcının yüklediği .html API kökeninde satır içi açılıp betik çalıştırmasın
    assert dl.status_code == 200 and dl.headers["content-disposition"].startswith("attachment") and dl.headers["x-content-type-options"] == "nosniff"
    assert TestClient(sys.modules["main"].app).get(f"/api/attachments/{att['id']}").status_code == 401

    # Gümrükçü REQ'i yalnızca Gümrük ve Lojistik aşamalarında görür; dosya da REQ ile aynı kuralı izler
    url = f"/api/attachments/{att['id']}"
    assert broker.get(url).status_code == 404            # Talep aşaması: göremez
    to_gumruk(admin, code)
    assert broker.get(url).status_code == 200            # Gümrük aşaması: görür
    line = admin.get(f"/api/reqs/{code}").json()["lines"][0]
    admin.post(f"/api/reqs/{code}/gumruk", json={"lines": [{"id": line["id"], "unit_customs": 0}], "costs": [], "advance": True})
    assert broker.get(url).status_code == 404            # Teklif aşaması: yine göremez

# ---------------------------------------------------------------- liste, dışa aktarma, panel

def test_list_export_excel_respects_visibility(api):
    admin, broker = api("yusuf.oz"), api("gumruk.ofis")
    a = seed_req(admin, "Birinci A.Ş.")
    listing = admin.get("/api/reqs?status=tumu").json()
    assert [r["code"] for r in listing["reqs"]] == [a] and listing["can_create"] and listing["can_view_amount"]

    res = admin.post("/api/reqs/export", json={"codes": [a, "YOK_REQ_9"]})
    assert res.status_code == 200 and "attachment" in res.headers["content-disposition"]
    rows = list(openpyxl.load_workbook(io.BytesIO(res.content)).active.values)
    assert rows[0][:2] == ("REQ", "Müşteri") and rows[0][-2:] == ("Teklif", "Para Birimi") and [r[0] for r in rows[1:]] == [a]

    # gümrükçü talep aşamasındaki REQ'yi görmez → dışa aktarma 404, liste boş
    assert broker.get("/api/reqs?status=tumu").json()["reqs"] == []
    assert broker.post("/api/reqs/export", json={"codes": [a]}).status_code == 404
    assert admin.post("/api/reqs/export", json={"codes": []}).status_code == 400


def test_panel_currency_conversion_and_broker_gets_no_financials(api):
    admin, broker = api("yusuf.oz"), api("gumruk.ofis")
    code = seed_req(admin, qty=10)
    line = to_teklif(admin, code)
    admin.post(f"/api/reqs/{code}/teklif", json={"teklif": {"margin_pct": 20, "tax_enabled": True, "tax_pct": 20, "valid_days": 30, "payment_terms": "", "logistics_mode": "dahil"}, "lines": [{"id": line["id"]}], "action": "save"})

    usd = admin.get("/api/panel?currency=USD").json()
    assert usd["financials"]["total_offer"] == 120.0 and usd["financials"]["total_profit"] == 20.0 and usd["cards"]["aktif_talep"] == 1
    eur = admin.get("/api/panel?currency=EUR").json()["financials"]
    assert eur["total_offer"] == 60.0 and eur["rates"]["EUR"] == 0.5  # 1 USD = 0,5 EUR
    assert admin.get("/api/panel?currency=GBP").status_code == 400

    # REQ Teklif aşamasında → gümrükçü onu hiç görmez (panel boş); görse bile teklif/kâr verisi gelmezdi
    bp = broker.get("/api/panel").json()
    assert bp["empty"] is True and "financials" not in bp


# ---------------------------------------------------------------- kişiler / ürünler

def test_partners_and_products_edit_whitelists_and_roles(api):
    admin, broker = api("yusuf.oz"), api("gumruk.ofis")
    added = admin.post("/api/partners", json={"type": "customer", "name": "Kişi Testi Ltd.", "req_seq": 7, "email": "a@b.co"}).json()
    row = next(p for p in added["partners"] if p["name"] == "Kişi Testi Ltd.")
    assert row["req_seq"] == 7 and row["short_code"]

    upd = admin.post("/api/partners/update", json={"type": "customers", "rows": [{"id": row["id"], "email": "yeni@x.co", "name": "Yeni  Ad Ltd."}]}).json()
    after = next(p for p in upd["partners"] if p["id"] == row["id"])
    assert after["email"] == "yeni@x.co" and after["name"] == "Yeni Ad Ltd." and after["short_code"] == row["short_code"] and upd["changed"] == 2
    assert broker.post("/api/partners/update", json={"type": "customers", "rows": [{"id": row["id"], "email": "z@z.co"}]}).status_code == 400

    prod = admin.post("/api/products", json={"name": "Katalog Ürünü", "last_cost": 5}).json()["products"][0]
    assert broker.get("/api/products").json()["editable_fields"] == ["hs_code"]
    upd = broker.post("/api/products/update", json={"rows": [{"id": prod["id"], "hs_code": "8501.31", "category": "HACK"}]}).json()
    changed = next(p for p in upd["products"] if p["id"] == prod["id"])
    assert changed["hs_code"] == "8501.31" and changed["category"] != "HACK"  # gümrükçü yalnızca GTİP'i değiştirebilir
    assert admin.post("/api/products/update", json={"rows": [{"id": prod["id"], "last_cost": -1}]}).status_code == 400
    assert broker.post("/api/products/update", json={"rows": [{"id": prod["id"], "name": "Gümrükçü Adı"}]}).status_code == 400  # gümrükçü adı değiştiremez
    assert admin.post("/api/products", json={"name": "X", "default_supplier_id": 99999}).status_code == 400


# ---------------------------------------------------------------- canlı-mod güvenlik korumaları

@pytest.mark.parametrize("env,should_start", [
    ({"JARVIS_DEV_MODE": "0"}, False),                                        # gizli anahtar yok
    ({"JARVIS_DEV_MODE": "0", "SESSION_SECRET": "kisa"}, False),              # çok kısa
    ({"JARVIS_DEV_MODE": "0", "SESSION_SECRET": "dev-only-change-me"}, False),  # bilinen geliştirme anahtarı
    ({"JARVIS_DEV_MODE": "0", "SESSION_SECRET": "k" * 40}, True),
    ({"JARVIS_DEV_MODE": "1", "COOKIE_SAMESITE": "none"}, False),             # none, Secure çerez ister → canlı mod şart
])
def test_production_startup_guards(env, should_start, tmp_path):
    base = {k: v for k, v in os.environ.items() if k not in ("JARVIS_DEV_MODE", "SESSION_SECRET", "WEB_ORIGINS", "COOKIE_SAMESITE")}
    base["DATABASE_URL"] = f"sqlite:///{tmp_path / 'guard.db'}"  # asla gerçek veritabanına değil
    code = f"import sys; sys.path.insert(0, r'{BACKEND}'); sys.path.insert(0, r'{BACKEND.parents[1]}'); import main"
    r = subprocess.run([sys.executable, "-c", code], env={**base, **env}, capture_output=True, text=True, cwd=str(BACKEND.parents[1]))
    assert (r.returncode == 0) is should_start, r.stderr[-300:]


# ---------------------------------------------------------------- silme (çöp kutusu) ve düzeltmeler

def trash(client, kind):
    return client.get(f"/api/trash/{kind}").json()


def test_req_delete_trash_restore_and_admin_only_typed_purge(api):
    admin, eren, broker = api("yusuf.oz"), api("eren.memisoglu"), api("gumruk.ofis")
    code = seed_req(admin)
    assert eren.get(f"/api/reqs/{code}").json()["can_delete"] is True and broker.get("/api/reqs?status=tumu").json()["reqs"] == []

    res = eren.post(f"/api/reqs/{code}/delete")  # yönetici rolü silebilir
    assert res.status_code == 200 and res.json() == {"hidden": True}
    assert admin.get(f"/api/reqs/{code}").status_code == 404 and admin.get("/api/reqs?status=tumu").json()["reqs"] == []
    assert admin.post("/api/reqs/export", json={"codes": [code]}).status_code == 404  # dışa aktarma da silineni göstermez
    t = trash(admin, "reqs")
    assert [i["ident"] for i in t["items"]] == [code] and t["items"][0]["deleted_by"] == "Eren Memişoğlu" and t["can_purge"] is True
    assert trash(eren, "reqs")["can_purge"] is False
    assert broker.get("/api/trash/reqs").status_code == 400  # gümrükçü çöp kutusunu göremez

    # kalıcı silme: yalnızca admin + kodu aynen yazarak
    assert eren.post(f"/api/trash/reqs/{code}/purge", json={"confirm": code}).status_code == 400
    assert admin.post(f"/api/trash/reqs/{code}/purge", json={"confirm": "yanlis"}).status_code == 400
    assert trash(admin, "reqs")["items"]  # başarısız denemeler bir şey silmedi

    assert admin.post(f"/api/trash/reqs/{code}/restore").json()["items"] == []
    assert admin.get(f"/api/reqs/{code}").status_code == 200  # geri geldi
    admin.post(f"/api/reqs/{code}/delete")
    assert admin.post(f"/api/trash/reqs/{code}/purge", json={"confirm": code}).json()["items"] == []
    assert admin.post(f"/api/trash/reqs/{code}/restore").status_code == 404  # kalıcı silindi: geri dönüş yok


def test_delete_blocked_for_shipment_linked_req(api):
    admin = api("yusuf.oz")
    code = seed_req(admin)
    line = admin.get(f"/api/reqs/{code}").json()["lines"][0]
    from jarvis import services as svc
    from jarvis.db import session_scope
    with session_scope() as s:
        a = svc.to_actor(next(u for u in svc.list_users(s) if u.username == "yusuf.oz"))
        shipment = svc.create_shipment(s, a)
        svc.add_shipment_item(s, a, shipment, line["id"], 1)
    res = admin.post(f"/api/reqs/{code}/delete")
    assert res.status_code == 400 and "kargoya bağlı" in res.json()["detail"]
    assert admin.get(f"/api/reqs/{code}").status_code == 200


def test_change_customer_and_meta_and_note_delete_endpoints(api):
    admin, eren, broker = api("yusuf.oz"), api("eren.memisoglu"), api("gumruk.ofis")
    code = seed_req(admin)
    other = admin.post("/api/customers", json={"name": "Diğer Firma", "short_code": "DGRF"}).json()["customers"]
    other_id = next(c["id"] for c in other if c["name"] == "Diğer Firma")
    third_id = next(c["id"] for c in admin.post("/api/customers", json={"name": "Üçüncü Firma", "short_code": "UCNC"}).json()["customers"] if c["name"] == "Üçüncü Firma")
    d = admin.get(f"/api/reqs/{code}").json()
    assert d["can_fix"] and {c["name"] for c in d["customer_options"]} >= {"Test Müşteri A.Ş.", "Diğer Firma"} and d["customer_change_blocked"] is False

    moved = eren.post(f"/api/reqs/{code}/customer", json={"customer_id": other_id}).json()
    assert moved["customer"] == "Diğer Firma" and moved["code"] == code  # REQ kodu değişmez
    assert admin.post(f"/api/reqs/{code}/customer", json={"customer_id": "x"}).status_code == 400

    to_teklif(admin, code)  # Teklif aşamasında not/teslimat tipi yine de düzeltilebilir
    meta = admin.post(f"/api/reqs/{code}/meta", json={"notes": " Yeni not ", "delivery_type": "Kapı Teslim"}).json()
    assert meta["notes"] == "Yeni not" and meta["delivery_type"] == "Kapı Teslim"
    assert admin.post(f"/api/reqs/{code}/meta", json={}).status_code == 400
    assert admin.post(f"/api/reqs/{code}/meta", json={"delivery_type": "Uzay"}).status_code == 400
    assert broker.post(f"/api/reqs/{code}/meta", json={"notes": "x"}).status_code == 404  # gümrükçü bu aşamadaki REQ'i görmez

    # teklif PDF'i çıkınca müşteri değiştirilemez ve arayüz bunu önceden bilir
    admin.post(f"/api/reqs/{code}/teklif", json={"teklif": {"margin_pct": 20, "tax_enabled": True, "tax_pct": 20, "valid_days": 30, "payment_terms": "", "logistics_mode": "dahil"}, "lines": [], "action": "pdf"})
    d = admin.get(f"/api/reqs/{code}").json()
    assert d["customer_change_blocked"] is True
    blocked = admin.post(f"/api/reqs/{code}/customer", json={"customer_id": third_id})
    assert blocked.status_code == 400 and "teklif ya da teslimat" in blocked.json()["detail"]
    assert admin.get(f"/api/reqs/{code}").json()["customer"] == "Diğer Firma"  # reddedilen işlem müşteriyi değiştirmedi

    # not silme: içerik gizlenir, silindiği kayda geçer; başka REQ'in notu bu adresle silinemez
    note = admin.post(f"/api/reqs/{code}/notes", json={"text": "Silinecek not"}).json()["notes_tasks"][0]
    assert note["can_delete"] is True
    prod_id = admin.get("/api/products").json()["products"][0]["id"]
    other_code = admin.post("/api/reqs", json={"customer_id": third_id, "items": [{"product_id": prod_id, "qty": 1}]}).json()["code"]
    assert admin.post(f"/api/reqs/{other_code}/notes/{note['id']}/delete").status_code == 404
    after = admin.post(f"/api/reqs/{code}/notes/{note['id']}/delete").json()
    assert all(n["message"] != "Silinecek not" for n in after["notes_tasks"]) and after["history"][0]["message"] == "Not silindi."


def test_partner_and_product_delete_rename_short_code_and_trash(api):
    admin, eren, broker = api("yusuf.oz"), api("eren.memisoglu"), api("gumruk.ofis")
    code = seed_req(admin, "Silinecek Müşteri")
    cust = next(p for p in admin.get("/api/partners?type=customers").json()["partners"] if p["name"] == "Silinecek Müşteri")
    assert cust["req_count"] == 1  # silme uyarısı için bağlı REQ sayısı

    # kısa kod değişimi yalnızca yeni REQ'leri etkiler
    upd = eren.post("/api/partners/update", json={"type": "customers", "rows": [{"id": cust["id"], "short_code": "yeni"}]}).json()
    assert next(p for p in upd["partners"] if p["id"] == cust["id"])["short_code"] == "YENI" and admin.get(f"/api/reqs/{code}").json()["code"] == code

    dup = admin.post("/api/partners", json={"type": "customer", "name": "Ad Çakışması"}).json()["partners"]
    clash = admin.post("/api/partners/update", json={"type": "customers", "rows": [{"id": next(p["id"] for p in dup if p["name"] == "Ad Çakışması"), "name": "silinecek müşteri"}]})
    assert clash.status_code == 400 and "zaten" in clash.json()["detail"]

    # silme → listeden kaybolur, çöp kutusunda görünür; REQ'i olan müşteri kalıcı silinemez
    res = eren.post(f"/api/partners/{cust['id']}/delete", json={"type": "customers"}).json()
    assert all(p["id"] != cust["id"] for p in res["partners"])
    assert [i["title"] for i in trash(admin, "customers")["items"]] == ["Silinecek Müşteri"] and "1 REQ bağlı" in trash(admin, "customers")["items"][0]["blocked"]
    assert admin.post(f"/api/trash/customers/{cust['id']}/purge", json={"confirm": "Silinecek Müşteri"}).status_code == 400
    assert admin.post(f"/api/reqs", json={"customer_id": cust["id"], "items": []}).status_code == 400  # silinmiş müşteriye REQ açılamaz
    admin.post(f"/api/trash/customers/{cust['id']}/restore")
    assert any(p["id"] == cust["id"] for p in admin.get("/api/partners?type=customers").json()["partners"])
    assert broker.post(f"/api/partners/{cust['id']}/delete", json={"type": "customers"}).status_code == 400

    # ürün: ad düzenleme, silme, çöp kutusu, kalıcı silme (satır adı korunur)
    prod = next(p for p in admin.get("/api/products").json()["products"] if p["name"] == "Deneme Ürünü")
    assert prod["line_count"] == 1
    renamed = eren.post("/api/products/update", json={"rows": [{"id": prod["id"], "name": "Deneme Ürünü v2"}]}).json()
    assert any(p["name"] == "Deneme Ürünü v2" for p in renamed["products"]) and renamed["changed"] == 1
    eren.post(f"/api/products/{prod['id']}/delete")
    assert all(p["id"] != prod["id"] for p in admin.get("/api/products").json()["products"])
    d = admin.get(f"/api/reqs/{code}").json()
    assert d["lines"][0]["name"] == "Deneme Ürünü" and d["lines"][0]["product_id"] == prod["id"]  # REQ satırı bozulmadı
    assert admin.post(f"/api/trash/products/{prod['id']}/purge", json={"confirm": "Deneme Ürünü v2"}).json()["items"] == []
    assert admin.get(f"/api/reqs/{code}").json()["lines"][0]["name"] == "Deneme Ürünü"  # kalıcı silinse de satır adı kalır
