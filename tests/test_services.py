import json
import re

import pytest
from sqlalchemy import select

from jarvis import db, pipeline as pl, seed, services as sv
from jarvis.models import Event, Partner, Product, Req
from jarvis.quote_pdf import render_quote_pdf


@pytest.fixture
def s(tmp_path):
    sv._LOGIN_ATTEMPTS.clear()  # süreç genelinde paylaşılan giriş kilidi; testler arasında sızmasın
    db.configure(f"sqlite:///{tmp_path / 'test.db'}")
    with db.session_scope() as session:
        seed.bootstrap(session)
        yield session


def actor(s, username):
    return sv.to_actor(next(u for u in sv.list_users(s) if u.username == username))


@pytest.fixture
def world(s):
    admin, eren, beyza, broker = (actor(s, n) for n in ("yusuf.oz", "eren.memisoglu", "beyza.yazar", "gumruk.ofis"))
    cust = sv.add_partner(s, admin, name="TİTRA TEKNOLOJİ", is_customer=True, short_code="TTRA", req_seq=16)
    prods = [sv.add_product(s, admin, name=n) for n in ("ESC", "Motor")]
    return dict(admin=admin, eren=eren, beyza=beyza, broker=broker, cust=cust, prods=prods)


def new_req(s, w, who="eren", **kw):
    return sv.create_req(s, w[who], customer_id=w["cust"].id, items=[(w["prods"][0].id, 10), (w["prods"][1].id, 6)], **kw)


def test_short_code_suggestion():
    assert sv.suggest_short_code("Altınay") == "ALTN"
    assert sv.suggest_short_code("ÖZGÜR Savunma") == "OZGR"


def test_partner_rules(s, world):
    with pytest.raises(sv.ServiceError, match="zaten kayıtlı"):
        sv.add_partner(s, world["admin"], name="titra teknoloji", is_customer=True)
    with pytest.raises(sv.ServiceError, match="kısa kodu"):
        sv.add_partner(s, world["admin"], name="Başka Firma", is_customer=True, short_code="ttra")
    with pytest.raises(sv.ServiceError, match="yetkiniz"):
        sv.add_partner(s, world["broker"], name="X", is_customer=True)
    auto = sv.add_partner(s, world["admin"], name="Altınay", is_customer=True)
    assert auto.short_code == "ALTN"
    assert sv.add_partner(s, world["admin"], name="Altın Ay Ltd", is_customer=True).short_code == "ALTN2"


def test_req_code_continues_from_existing_sequence(s, world):
    assert sv.next_req_code(s, world["cust"].id) == "TTRA_REQ_17"
    assert new_req(s, world).code == "TTRA_REQ_17"
    assert new_req(s, world, "beyza").code == "TTRA_REQ_18"


def test_failed_create_does_not_burn_a_number(s, world):
    with pytest.raises(sv.ServiceError):
        sv.create_req(s, world["eren"], customer_id=world["cust"].id, items=[(world["prods"][0].id, 0)])
    assert new_req(s, world).code == "TTRA_REQ_17"


def test_create_requires_customer_and_items(s, world):
    with pytest.raises(sv.ServiceError):
        sv.create_req(s, world["eren"], customer_id=world["cust"].id, items=[])
    with pytest.raises(sv.ServiceError):
        sv.create_req(s, world["broker"], customer_id=world["cust"].id, items=[(world["prods"][0].id, 1)])


def test_full_golden_thread(s, world):
    eren, broker = world["eren"], world["broker"]
    r = new_req(s, world)
    rid = r.id
    req = lambda: sv.get_req(s, eren, req_id=rid)

    # Fiyat girilmeden Gümrük'e geçilemez
    sv.advance_req(s, eren, req())
    with pytest.raises(sv.ServiceError) as e:
        sv.advance_req(s, eren, req())
    assert "Birim alış" in e.value.errors[0]
    sv.save_line_values(s, eren, req(), "unit_cost", [{"id": l.id, "value": v} for l, v in zip(req().lines, (132.95, 77.08))])
    sv.advance_req(s, eren, req())
    assert req().stage == "gumruk"

    # Gümrükçü kendi aşamasını girer, fiyat/teklif aşamasına dokunamaz
    with pytest.raises(sv.ServiceError):
        sv.save_line_values(s, broker, sv.get_req(s, broker, req_id=rid), "unit_cost", [])
    sv.save_line_values(s, broker, sv.get_req(s, broker, req_id=rid), "unit_customs", [{"id": l.id, "value": 0} for l in req().lines])
    sv.save_costs(s, broker, sv.get_req(s, broker, req_id=rid), [{"label": "Nakliye", "amount": 50}, {"label": "", "amount": None}])
    sv.advance_req(s, broker, sv.get_req(s, broker, req_id=rid))
    assert req().stage == "teklif" and len(req().costs) == 1
    with pytest.raises(sv.ServiceError, match="yetkiniz"):  # artık gümrükçünün görüş alanında değil
        sv.get_req(s, broker, req_id=rid)

    # Teklif: marj + iletildi işareti olmadan geçilemez
    sv.update_fields(s, eren, req(), margin_pct=20.0)
    with pytest.raises(sv.ServiceError):
        sv.advance_req(s, eren, req())
    sv.mark_quote_sent(s, eren, req())
    sv.advance_req(s, eren, req())
    assert req().stage == "karar"

    # Ret -> rafa; yeniden aç; onay -> sipariş
    with pytest.raises(sv.ServiceError, match="sebeb"):
        sv.decide(s, eren, req(), False)
    sv.decide(s, eren, req(), False, "Bütçe yok")
    assert req().status == "rafa" and req().shelved_reason == "Bütçe yok"
    sv.reopen_req(s, eren, req())
    assert req().status == "aktif" and req().decision is None and req().stage == "karar"
    sv.decide(s, eren, req(), True)
    assert req().stage == "siparis"

    with pytest.raises(sv.ServiceError):
        sv.advance_req(s, eren, req())
    sv.set_po_approved(s, eren, req(), True)
    sv.advance_req(s, eren, req())
    sv.advance_req(s, eren, req())
    assert req().stage == "teslim"

    with pytest.raises(sv.ServiceError) as e:
        sv.advance_req(s, eren, req())  # hiç teslimat yapılmadan tamamlanamaz
    assert "tam teslim" in e.value.errors[0]
    line1, line2 = req().lines
    sv.create_delivery(s, eren, req(), [{"line_id": line1.id, "qty": line1.qty}])  # kısmi (ön) teslimat: yalnızca 1. ürün
    with pytest.raises(sv.ServiceError) as e:
        sv.advance_req(s, eren, req())  # 2. ürün hâlâ teslim edilmedi
    assert "tam teslim" in e.value.errors[0]
    sv.create_delivery(s, eren, req(), [{"line_id": line2.id, "qty": line2.qty}])
    sv.advance_req(s, eren, req())
    assert req().status == "tamamlandi"

    kinds = [ev.kind for ev in sv.list_events(s, rid)]
    assert kinds.count("stage") == 7 and "create" in kinds and kinds.count("status") == 3


def test_managers_see_all_reqs(s, world):
    """GEÇİCİ (kullanıcı yetkilendirme modülüne kadar): her yönetici her REQ'i görür, birbirine görev atayabilsin diye."""
    r = new_req(s, world, "eren")
    assert [x.id for x in sv.visible_reqs(s, world["eren"])] == [r.id]
    assert [x.id for x in sv.visible_reqs(s, world["beyza"])] == [r.id]
    assert sv.get_req(s, world["beyza"], req_id=r.id).id == r.id  # artık sahibi olmasa da açabilir
    assert len(sv.visible_reqs(s, world["admin"])) == 1


def test_stage_edit_locking(s, world):
    eren = world["eren"]
    req = new_req(s, world)
    with pytest.raises(sv.ServiceError, match="yalnızca"):
        sv.save_line_values(s, eren, req, "unit_customs", [])  # Talep aşamasında gümrük girilemez
    with pytest.raises(sv.ServiceError):
        sv.update_fields(s, eren, req, margin_pct=30)  # marj yalnızca Teklif aşamasında


def test_move_back_clears_later_confirmations(s, world):
    eren = world["eren"]
    req = new_req(s, world)
    seed._progress(s, req.id, "siparis", eren, world["broker"])
    req = sv.get_req(s, eren, req_id=req.id)
    assert req.stage == "siparis" and req.decision == "onay" and req.quote_sent_at
    with pytest.raises(sv.ServiceError, match="sebeb"):
        sv.move_back(s, eren, req, "")
    sv.move_back(s, eren, req, "Müşteri fiyatı değiştirdi")
    sv.move_back(s, eren, req, "Marj düşecek")
    req = sv.get_req(s, eren, req_id=req.id)
    assert req.stage == "teklif" and req.quote_sent_at is None and req.decision is None


def test_save_items_edits_adds_removes_and_resets_price_on_product_change(s, world):
    eren, (p1, p2) = world["eren"], world["prods"]
    p3 = sv.add_product(s, world["admin"], name="VTX")
    req = new_req(s, world)
    l1, l2 = req.lines
    l1.unit_cost = 99.0
    s.commit()
    sv.save_items(s, eren, req, [{"id": l1.id, "product_id": p3.id, "qty": 4}, {"id": None, "product_id": p1.id, "qty": 2}])
    req = sv.get_req(s, eren, req_id=req.id)
    assert [(l.name, l.qty) for l in req.lines] == [("VTX", 4), ("ESC", 2)]
    assert req.lines[0].unit_cost is None  # ürün değişince eski fiyat geçersiz
    with pytest.raises(sv.ServiceError, match="Adet"):
        sv.save_items(s, eren, req, [{"id": None, "product_id": p1.id, "qty": 0}])
    assert len(sv.get_req(s, eren, req_id=req.id).lines) == 2  # hatalı kayıt hiçbir şeyi değiştirmedi


def test_broker_may_only_edit_hs_code(s, world):
    p = world["prods"][0]
    sv.update_records(s, world["broker"], Product, [{"id": p.id, "hs_code": "8501.31", "category": "HACK"}])
    s.refresh(p)
    assert p.hs_code == "8501.31" and p.category == ""
    with pytest.raises(sv.ServiceError):
        sv.update_records(s, world["broker"], Partner, [{"id": world["cust"].id, "notes": "x"}])


def test_demo_seed_and_purge(s):
    seed.load_demo(s)
    reqs = sv.visible_reqs(s, actor(s, "yusuf.oz"))
    assert sorted(r.stage for r in reqs) == sorted(seed.DEMO_STAGES)
    assert all(len(sv.visible_reqs(s, actor(s, u))) == 8 for u in ("eren.memisoglu", "beyza.yazar", "eren.zorman", "zerrin.oz"))  # GEÇİCİ: her yönetici tüm demo REQ'leri görür
    assert sorted(r.stage for r in sv.visible_reqs(s, actor(s, "gumruk.ofis"))) == ["gumruk", "lojistik"]
    seed.purge_demo(s)
    assert s.scalars(select(Req)).all() == [] and s.scalars(select(Event)).all() == []
    assert s.scalars(select(Partner)).all() == [] and s.scalars(select(Product)).all() == []
    assert len(sv.list_users(s)) == len(seed.BASE_USERS)  # kullanıcılar korunur


def test_history_hides_pricing_events_from_broker(s, world):
    req = new_req(s, world)
    seed._progress(s, req.id, "karar", world["eren"], world["broker"])
    admin_msgs = [e.message for e in sv.list_events(s, req.id, world["admin"])]
    broker_msgs = [e.message for e in sv.list_events(s, req.id, world["broker"])]
    assert any("margin_pct" in m for m in admin_msgs)          # marj değişikliği yöneticiye görünür
    assert not any("margin_pct" in m or "Teklif" in m and "iletildi" in m for m in broker_msgs)  # gümrükçüden gizli
    assert any("Birim gümrük masrafları" in m for m in broker_msgs)  # kendi aşamasındaki kayıt görünür
    assert any(e.kind == "stage" for e in sv.list_events(s, req.id, world["broker"]))  # aşama geçişleri görünür


def test_saving_unchanged_extra_costs_does_not_spam_history(s, world):
    eren, broker = world["eren"], world["broker"]
    req = new_req(s, world)
    seed._progress(s, req.id, "gumruk", eren, broker)
    req = sv.get_req(s, broker, req_id=req.id)
    rows = [{"label": "Nakliye", "amount": 50.0}]
    sv.save_costs(s, broker, req, rows)
    before = len(sv.list_events(s, req.id))
    sv.save_costs(s, broker, sv.get_req(s, broker, req_id=req.id), rows)
    assert len(sv.list_events(s, req.id)) == before


def test_split_costs_tax_toggle_delivery_type_and_logistics_mode(s, world):
    eren, broker = world["eren"], world["broker"]
    req = new_req(s, world)
    sv.update_fields(s, eren, req, delivery_type="Kapı Teslim")
    with pytest.raises(sv.ServiceError, match="teslimat"):
        sv.update_fields(s, eren, req, delivery_type="Uçakla")
    seed._progress(s, req.id, "gumruk", eren, broker)
    req = sv.get_req(s, broker, req_id=req.id)
    assert req.delivery_type == "Kapı Teslim" and req.stage == "gumruk"
    sv.save_line_values(s, broker, req, "unit_customs", [{"id": l.id, "value": 3.0} for l in req.lines])
    sv.save_line_values(s, broker, req, "unit_logistics", [{"id": l.id, "value": 2.0} for l in req.lines])
    with pytest.raises(sv.ServiceError, match="türü"):
        sv.save_costs(s, broker, req, [{"label": "x", "amount": 1, "kind": "bilinmez"}])
    sv.save_costs(s, broker, req, [{"label": "Nakliye", "amount": 100, "kind": "lojistik"}, {"label": "Ekspertiz", "amount": 20, "kind": "gumruk"}])
    sv.advance_req(s, broker, sv.get_req(s, broker, req_id=req.id))

    req = sv.get_req(s, eren, req_id=req.id)
    sv.update_fields(s, eren, req, margin_pct=10.0, tax_enabled=False, logistics_mode="ayri")
    with pytest.raises(sv.ServiceError, match="gösterim"):
        sv.update_fields(s, eren, req, logistics_mode="x")
    q = pl.quote_for_req(sv.get_req(s, eren, req_id=req.id))
    assert q.tax == 0 and q.grand_total == q.total
    assert q.cost_customs == 16 * 3.0 + 20 and q.cost_logistics == 16 * 2.0 + 100
    assert [r["kind"] for r in q.rows][-1] == "lojistik"


def test_completed_reqs_stay_visible(s, world):
    req = new_req(s, world)
    seed._progress(s, req.id, "teslim", world["eren"], world["broker"])
    req = sv.get_req(s, world["eren"], req_id=req.id)
    for line in req.lines: sv.create_delivery(s, world["eren"], req, [{"line_id": line.id, "qty": line.qty}])
    sv.advance_req(s, world["eren"], sv.get_req(s, world["eren"], req_id=req.id))
    assert [r.status for r in sv.visible_reqs(s, world["eren"])] == ["tamamlandi"]
    assert [r.status for r in sv.visible_reqs(s, world["admin"])] == ["tamamlandi"]


def _at_teklif(s, w, who="eren"):
    """REQ'yi Teklif aşamasına taşır ve kâr marjını girer."""
    req = new_req(s, w, who)
    seed._progress(s, req.id, "teklif", w[who], w["broker"])
    req = sv.get_req(s, w[who], req_id=req.id)
    sv.update_fields(s, w[who], req, margin_pct=20.0)
    return sv.get_req(s, w[who], req_id=req.id)


def test_quote_numbering_revisions_and_idempotence(s, world):
    admin, eren, beyza = world["admin"], world["eren"], world["beyza"]
    sv.update_company(s, admin, quote_seq=203)  # Odoo'daki son numaradan devam
    req = _at_teklif(s, world)
    q1 = sv.issue_quote(s, eren, req)
    assert re.fullmatch(r"OZ\d{6}204", q1.number) and q1.version == 1
    assert sv.issue_quote(s, eren, req).id == q1.id                   # aynı içerik: yeni teklif açılmaz
    sv.update_fields(s, eren, req, margin_pct=25.0)
    q2 = sv.issue_quote(s, eren, req)
    assert q2.number == q1.number + "-R2" and q2.version == 2         # içerik değişince revizyon
    assert [q.number for q in sv.list_quotes(s, eren, req)] == [q2.number, q1.number]
    other = sv.issue_quote(s, beyza, _at_teklif(s, world, "beyza"))
    assert other.number.endswith("205") and sv.get_company(s, admin).quote_seq == 205


def test_mark_quote_sent_issues_a_matching_quote_and_broker_has_no_access(s, world):
    req = _at_teklif(s, world)
    sv.mark_quote_sent(s, world["eren"], req)
    assert len(sv.list_quotes(s, world["eren"], req)) == 1
    assert sv.list_quotes(s, world["broker"], req) == []
    with pytest.raises(sv.ServiceError):
        sv.issue_quote(s, world["broker"], req)


def test_quote_needs_margin_and_snapshot_has_no_internal_data(s, world):
    req = new_req(s, world)
    seed._progress(s, req.id, "teklif", world["eren"], world["broker"])
    req = sv.get_req(s, world["eren"], req_id=req.id)
    with pytest.raises(sv.ServiceError, match="marj"):
        sv.issue_quote(s, world["eren"], req)
    sv.update_fields(s, world["eren"], req, margin_pct=20.0)
    data = json.loads(sv.issue_quote(s, world["eren"], req).snapshot)
    assert not {"margin_pct", "cost_total", "profit", "cost"} & set(data)
    assert all(set(r) == {"name", "spec", "qty", "unit_price", "line_total"} for r in data["rows"])
    pdf = render_quote_pdf(data)
    assert pdf.startswith(b"%PDF")


def test_demo_quotes_do_not_consume_real_numbering(s, world):
    seed.load_demo(s)
    assert sv.get_company(s, world["admin"]).quote_seq == 0
    assert sv.issue_quote(s, world["eren"], _at_teklif(s, world)).number.endswith("001")


def test_company_settings_are_admin_only_and_quote_seq_never_goes_back(s, world):
    with pytest.raises(sv.ServiceError, match="yetkiniz"):
        sv.update_company(s, world["eren"], phone="1")
    company = sv.update_company(s, world["admin"], quote_seq=10, quote_prefix="oz-x", legal_name="OZ A.Ş.")
    assert company.quote_prefix == "OZX" and company.legal_name == "OZ A.Ş."
    sv.issue_quote(s, world["eren"], _at_teklif(s, world))
    with pytest.raises(sv.ServiceError, match="geriye"):
        sv.update_company(s, world["admin"], quote_seq=5)


def test_po_number_auto_generated_on_approval_and_stable_on_toggle(s, world):
    admin, eren, broker = world["admin"], world["eren"], world["broker"]
    sv.update_company(s, admin, po_seq=3)  # Odoo'daki son PO numarasından devam
    req = new_req(s, world)
    seed._progress(s, req.id, "siparis", eren, broker)
    req = sv.get_req(s, eren, req_id=req.id)
    assert req.po_number is None
    sv.set_po_approved(s, eren, req, True)
    req = sv.get_req(s, eren, req_id=req.id)
    assert re.fullmatch(r"P\d{6}004", req.po_number)
    first_number = req.po_number

    sv.set_po_approved(s, eren, req, False)   # onayı geri al
    sv.set_po_approved(s, eren, req, True)    # tekrar onayla: aynı PO no korunur, yeni numara tüketilmez
    req = sv.get_req(s, eren, req_id=req.id)
    assert req.po_number == first_number and sv.get_company(s, admin).po_seq == 4


def test_po_number_cleared_and_reissued_after_move_back(s, world):
    eren, broker = world["eren"], world["broker"]
    req = new_req(s, world)
    seed._progress(s, req.id, "siparis", eren, broker)
    req = sv.get_req(s, eren, req_id=req.id)
    sv.set_po_approved(s, eren, req, True)
    old_po = sv.get_req(s, eren, req_id=req.id).po_number
    req = sv.get_req(s, eren, req_id=req.id)
    sv.move_back(s, eren, req, "Fiyat revize edilecek")
    req = sv.get_req(s, eren, req_id=req.id)
    assert req.stage == "karar" and req.po_number is None and req.po_approved_at is None
    sv.decide(s, eren, req, True)
    req = sv.get_req(s, eren, req_id=req.id)
    sv.set_po_approved(s, eren, req, True)
    assert sv.get_req(s, eren, req_id=req.id).po_number != old_po  # yeni bir PO numarası üretildi, eskisi tekrar kullanılmadı


def test_demo_po_does_not_consume_real_sequence(s, world):
    eren, broker = world["eren"], world["broker"]
    req = new_req(s, world, is_demo=True)
    seed._progress(s, req.id, "siparis", eren, broker)
    req = sv.get_req(s, eren, req_id=req.id)
    sv.set_po_approved(s, eren, req, True)
    req = sv.get_req(s, eren, req_id=req.id)
    assert req.po_number == f"DEMO-{req.code}"
    assert sv.get_company(s, world["admin"]).po_seq == 0


def test_line_margin_and_price_override_saved_only_in_teklif_stage(s, world):
    eren, broker = world["eren"], world["broker"]
    req = new_req(s, world)
    with pytest.raises(sv.ServiceError, match="yalnızca"):
        sv.save_line_values(s, eren, req, "margin_pct", [])  # Talep aşamasında henüz yazılamaz
    seed._progress(s, req.id, "teklif", eren, broker)
    req = sv.get_req(s, eren, req_id=req.id)
    l1, l2 = req.lines
    sv.save_line_values(s, eren, req, "margin_pct", [{"id": l1.id, "value": 35.0}])
    sv.save_line_values(s, eren, req, "sale_price_override", [{"id": l2.id, "value": 250.0}])
    sv.update_fields(s, eren, req, margin_pct=20.0, logistics_margin_pct=15.0)
    req = sv.get_req(s, eren, req_id=req.id)
    assert req.lines[0].margin_pct == 35.0 and req.lines[1].sale_price_override == 250.0 and req.logistics_margin_pct == 15.0
    q = pl.quote_for_req(req)
    assert q.rows[0]["margin_pct"] == 35.0 and q.rows[1]["override"] is True and q.rows[1]["unit_price"] == 250.0


def test_quote_snapshot_never_reveals_line_margin_or_override(s, world):
    eren, broker = world["eren"], world["broker"]
    req = new_req(s, world)
    seed._progress(s, req.id, "teklif", eren, broker)
    req = sv.get_req(s, eren, req_id=req.id)
    sv.save_line_values(s, eren, req, "sale_price_override", [{"id": req.lines[0].id, "value": 999.0}])
    sv.update_fields(s, eren, req, margin_pct=20.0)
    doc = sv.issue_quote(s, eren, sv.get_req(s, eren, req_id=req.id))
    data = json.loads(doc.snapshot)
    assert not {"margin_pct", "override", "cost"} & set(data["rows"][0])


def test_line_supplier_selection_only_in_talep_or_fiyat_stage(s, world):
    eren, broker = world["eren"], world["broker"]
    req = new_req(s, world)
    supplier = sv.add_partner(s, world["admin"], name="ACME Parts", is_supplier=True, email="sales@acme.test")
    sv.set_line_supplier(s, eren, req, req.lines[0].id, supplier.id)  # Talep aşamasında izinli
    assert sv.get_req(s, eren, req_id=req.id).lines[0].supplier.name == "ACME Parts"

    seed._progress(s, req.id, "gumruk", eren, broker)
    req = sv.get_req(s, eren, req_id=req.id)
    with pytest.raises(sv.ServiceError, match="Talep veya Fiyat"):
        sv.set_line_supplier(s, eren, req, req.lines[0].id, supplier.id)
    other = new_req(s, world, "eren")
    with pytest.raises(sv.ServiceError, match="Geçersiz tedarikçi"):
        sv.set_line_supplier(s, eren, other, other.lines[0].id, world["cust"].id)  # müşteri, tedarikçi değil


def test_search_suppliers_reconciles_ai_response_with_real_pool(s, world, monkeypatch):
    admin = world["admin"]
    good = sv.add_partner(s, admin, name="Acme Motors", is_supplier=True, category="İtki", email="a@acme.test", country="China")
    req = new_req(s, world)  # ESC, Motor

    def fake_match(items, suppliers):
        assert len(items) == 2 and {p["name"] for p in suppliers} == {"Acme Motors"}
        return [{"talep": "ESC", "tedarikci_id": good.id, "tedarikci": "Acme Motors", "eposta": "wrong@ignored.test", "ulke": "CN", "aciklama": "uygun"},
               {"talep": "Motor", "tedarikci_id": 999999, "tedarikci": "Hayalet Firma", "eposta": "x@x.test", "ulke": "-", "aciklama": "yok"}], ""

    monkeypatch.setattr(sv.ai, "match_suppliers", fake_match)
    matches, error = sv.search_suppliers(s, world["eren"], req)
    assert error == "" and len(matches) == 1  # uydurma tedarikçi havuzda yok, elenir
    assert matches[0]["eposta"] == "a@acme.test"  # e-posta AI'dan değil, bizim kayıttan alınır


def test_search_suppliers_propagates_ai_error(s, world, monkeypatch):
    monkeypatch.setattr(sv.ai, "match_suppliers", lambda items, suppliers: ([], "Gemini API anahtarı bulunamadı"))
    matches, error = sv.search_suppliers(s, world["eren"], new_req(s, world))
    assert matches == [] and "Gemini" in error


def test_sale_price_override_of_zero_is_treated_as_not_set(s, world):
    eren, broker = world["eren"], world["broker"]
    req = new_req(s, world)
    seed._progress(s, req.id, "teklif", eren, broker)
    req = sv.get_req(s, eren, req_id=req.id)
    line = req.lines[0]
    sv.save_line_values(s, eren, req, "sale_price_override", [{"id": line.id, "value": 250.0}])
    assert sv.get_req(s, eren, req_id=req.id).lines[0].sale_price_override == 250.0
    sv.save_line_values(s, eren, req, "sale_price_override", [{"id": line.id, "value": 0}])
    reloaded = sv.get_req(s, eren, req_id=req.id).lines[0]
    assert reloaded.sale_price_override is None  # 0 kaydedilmedi, "boş" sayıldı
    q = pl.quote_for_req(sv.get_req(s, eren, req_id=req.id))
    assert q.rows[0]["override"] is False


def test_issued_quote_carries_req_reference_and_auto_payment_description(s, world):
    eren, broker = world["eren"], world["broker"]
    sv.update_company(s, world["admin"], quote_seq=0)
    req = new_req(s, world)
    seed._progress(s, req.id, "teklif", eren, broker)
    req = sv.get_req(s, eren, req_id=req.id)
    sv.update_fields(s, eren, req, margin_pct=20.0)
    doc = sv.issue_quote(s, eren, sv.get_req(s, eren, req_id=req.id))
    data = json.loads(doc.snapshot)
    assert data["reference"] == req.code
    assert data["payment_ref"] == "OZ" + doc.number[-3:]


def test_new_shipment_defaults_to_ankara_and_can_be_changed(s, world):
    admin = world["admin"]
    shipment = sv.create_shipment(s, admin, awb_no="123")
    assert shipment.delivery_address == "Ankara Merkez Ofis"
    sv.update_shipment(s, admin, shipment, delivery_address="İzmir Depo")
    assert sv.get_shipment(s, admin, shipment_id=shipment.id).delivery_address == "İzmir Depo"
    explicit = sv.create_shipment(s, admin, delivery_address="Bursa Şube")
    assert explicit.delivery_address == "Bursa Şube"  # açıkça verilen adres varsayılanı ezmez


def test_refresh_dhl_tracking_updates_location_and_rejects_other_carriers(s, world, monkeypatch):
    admin = world["admin"]
    dhl = sv.create_shipment(s, admin, awb_no="7777777770", carrier="DHL Express")
    other = sv.create_shipment(s, admin, awb_no="235123456789", carrier="Turkish Cargo")

    with pytest.raises(sv.ServiceError, match="yalnızca"):
        sv.refresh_dhl_tracking(s, admin, other)

    monkeypatch.setattr(sv.config, "get_config_val", lambda key, default="": "" if key == "DHL_API_KEY" else default)
    with pytest.raises(sv.ServiceError, match="DHL_API_KEY"):
        sv.refresh_dhl_tracking(s, admin, dhl)

    monkeypatch.setattr(sv.config, "get_config_val", lambda key, default="": "fake-key" if key == "DHL_API_KEY" else default)
    monkeypatch.setattr(sv.tracking, "fetch_dhl_status", lambda awb, key: {"location": "ISTANBUL, TR", "description": "Transit"})
    desc = sv.refresh_dhl_tracking(s, admin, dhl)
    reloaded = sv.get_shipment(s, admin, shipment_id=dhl.id)
    assert desc == "Transit" and reloaded.current_location == "ISTANBUL, TR" and reloaded.last_tracked_at is not None
    assert "Transit" in reloaded.notes


def test_tracking_url_templates():
    assert pl.tracking_url("DHL Express", "37-1862 3215") == "https://www.dhl.com/tr-en/home/tracking.html?submit=1&tracking-id=3718623215"
    assert pl.tracking_url("Turkish Cargo", "235123") == "https://www.turkishcargo.com/en/cargo-tracking"
    assert pl.tracking_url("Özel Hat", "123") is None


def test_partial_delivery_across_two_receipts_and_over_delivery_guard(s, world):
    eren, broker = world["eren"], world["broker"]
    req = new_req(s, world)  # ESC qty=10, Motor qty=6
    seed._progress(s, req.id, "teslim", eren, broker)
    req = sv.get_req(s, eren, req_id=req.id)
    esc, motor = req.lines

    with pytest.raises(sv.ServiceError, match="en fazla"):
        sv.create_delivery(s, eren, req, [{"line_id": esc.id, "qty": 11}])  # sipariş edilenden fazla
    with pytest.raises(sv.ServiceError, match="en az bir"):
        sv.create_delivery(s, eren, req, [{"line_id": esc.id, "qty": 0}])  # hiç adet yok

    doc1 = sv.create_delivery(s, eren, req, [{"line_id": esc.id, "qty": 4}, {"line_id": motor.id, "qty": 6}], delivered_to="Ahmet Yılmaz")
    assert doc1.number.startswith("OUT/") and doc1.delivered_to == "Ahmet Yılmaz"
    req = sv.get_req(s, eren, req_id=req.id)
    assert pl.delivered_qty(req, esc.id) == 4 and pl.delivered_qty(req, motor.id) == 6

    with pytest.raises(sv.ServiceError, match="en fazla"):
        sv.create_delivery(s, eren, req, [{"line_id": esc.id, "qty": 7}])  # kalan yalnızca 6 (10-4)
    doc2 = sv.create_delivery(s, eren, req, [{"line_id": esc.id, "qty": 6}])  # tam kalanı: sorunsuz
    assert doc2.number != doc1.number and doc2.number.endswith("2")  # ayrı numara, sayaç ilerledi

    req = sv.get_req(s, eren, req_id=req.id)
    assert pl.delivered_qty(req, esc.id) == 10.0
    assert sv.list_deliveries(s, eren, req)[0].id == doc2.id  # en yeni başta
    sv.advance_req(s, eren, req)  # artık tüm ürünler tam teslim: tamamlanabilir
    assert sv.get_req(s, eren, req_id=req.id).status == "tamamlandi"


def test_delivery_only_in_teslim_stage_and_wrong_line_rejected(s, world):
    eren, broker = world["eren"], world["broker"]
    req = new_req(s, world)
    with pytest.raises(sv.ServiceError, match="yalnızca"):
        sv.create_delivery(s, eren, req, [{"line_id": req.lines[0].id, "qty": 1}])  # Talep aşamasında henüz olmaz
    other = new_req(s, world, "eren")
    seed._progress(s, req.id, "teslim", eren, broker)
    req = sv.get_req(s, eren, req_id=req.id)
    with pytest.raises(sv.ServiceError, match="Geçersiz REQ satırı"):
        sv.create_delivery(s, eren, req, [{"line_id": other.lines[0].id, "qty": 1}])  # başka REQ'in satırı


def test_delivery_snapshot_has_no_pricing_and_pdf_renders(s, world):
    eren, broker = world["eren"], world["broker"]
    req = new_req(s, world)
    seed._progress(s, req.id, "teslim", eren, broker)
    req = sv.get_req(s, eren, req_id=req.id)
    quote_number = req.quotes[0].number
    doc = sv.create_delivery(s, eren, req, [{"line_id": l.id, "qty": l.qty} for l in req.lines])
    data = json.loads(doc.snapshot)
    assert data["order_ref"] == quote_number and data["reference"] == req.code  # müşteriye "Sipariş" olarak teklif no gösterilir
    assert not {"cost", "margin_pct", "unit_price"} & set(data["rows"][0])
    from jarvis.delivery_pdf import render_delivery_pdf
    pdf = render_delivery_pdf(data)
    assert pdf.startswith(b"%PDF")


def test_delivery_numbering_cannot_go_backwards(s, world):
    admin, eren, broker = world["admin"], world["eren"], world["broker"]
    req = new_req(s, world)
    seed._progress(s, req.id, "teslim", eren, broker)
    req = sv.get_req(s, eren, req_id=req.id)
    sv.create_delivery(s, eren, req, [{"line_id": req.lines[0].id, "qty": req.lines[0].qty}])  # gerçek bir teslimat: sayaç artık kullanımda
    with pytest.raises(sv.ServiceError, match="geriye"):
        sv.update_company(s, admin, delivery_seq=0)
    sv.update_company(s, admin, delivery_prefix="teslim", delivery_seq=99)  # ileri almak serbest
    assert sv.get_company(s, admin).delivery_prefix == "TESLIM"


def test_carrier_tracking_url_and_manual_awb_flag():
    assert pl.carrier_needs_manual_awb("Turkish Cargo") is True
    assert pl.carrier_needs_manual_awb("DHL Express") is False
    assert pl.carrier_needs_manual_awb("Bilinmeyen") is False


def test_exw_delivery_type_available_and_selectable(s, world):
    eren = world["eren"]
    req = new_req(s, world, delivery_type="Fabrika Teslim (EXW)")
    assert req.delivery_type == "Fabrika Teslim (EXW)"
    sv.update_fields(s, eren, req, delivery_type="Kapı Teslim")
    assert sv.get_req(s, eren, req_id=req.id).delivery_type == "Kapı Teslim"


def test_update_currency_corrects_regardless_of_stage_and_guards_role(s, world):
    eren, broker = world["eren"], world["broker"]
    req = new_req(s, world)
    seed._progress(s, req.id, "gumruk", eren, broker)  # aşamadan bağımsız çalışmalı
    req = sv.get_req(s, eren, req_id=req.id)
    assert req.currency == "USD"
    with pytest.raises(sv.ServiceError, match="yetkiniz"):
        sv.update_currency(s, broker, req, "EUR")  # gümrükçü düzeltemez
    with pytest.raises(sv.ServiceError, match="Geçersiz"):
        sv.update_currency(s, eren, req, "GBP")
    sv.update_currency(s, eren, req, "EUR")
    assert sv.get_req(s, eren, req_id=req.id).currency == "EUR"
    sv.update_currency(s, eren, req, "EUR")  # aynı değer: sessizce no-op, hata yok


def test_authenticate_and_set_password(s, world):
    admin, eren = world["admin"], world["eren"]
    with pytest.raises(sv.ServiceError, match="Kullanıcı adı veya şifre hatalı"):
        sv.authenticate(s, "eren.memisoglu", "yanlis-sifre")  # sifre henuz belirlenmemis

    with pytest.raises(sv.ServiceError, match="yetkiniz"):
        sv.set_password(s, eren, eren.id, "gizlisifre")  # yalnizca admin sifre belirleyebilir
    with pytest.raises(sv.ServiceError, match="en az 8"):
        sv.set_password(s, admin, eren.id, "kisa1")

    sv.set_password(s, admin, eren.id, "gizlisifre123")
    actor = sv.authenticate(s, "eren.memisoglu", "gizlisifre123")
    assert actor.username == "eren.memisoglu"

    with pytest.raises(sv.ServiceError, match="Kullanıcı adı veya şifre hatalı"):
        sv.authenticate(s, "eren.memisoglu", "yanlis-sifre")
    with pytest.raises(sv.ServiceError, match="Kullanıcı adı veya şifre hatalı"):
        sv.authenticate(s, "yok-boyle-kullanici", "herhangi")


def test_authenticate_locks_out_after_repeated_failures(s, world):
    admin, eren = world["admin"], world["eren"]
    sv.set_password(s, admin, eren.id, "gizlisifre123")

    for _ in range(sv._LOGIN_MAX_ATTEMPTS):
        with pytest.raises(sv.ServiceError, match="Kullanıcı adı veya şifre hatalı"):
            sv.authenticate(s, "eren.memisoglu", "yanlis-sifre")

    with pytest.raises(sv.ServiceError, match="Çok fazla hatalı giriş denemesi"):
        sv.authenticate(s, "eren.memisoglu", "gizlisifre123")  # doğru şifre bile kilitliyken reddedilir

    with pytest.raises(sv.ServiceError, match="Kullanıcı adı veya şifre hatalı"):
        sv.authenticate(s, "beyza.yazar", "yanlis-sifre")  # başka kullanıcı adı kilitlenmemiş, kendi mesajı gelir


def test_add_note_plain_creates_note_event(s, world):
    eren = world["eren"]
    req = new_req(s, world)
    sv.add_note(s, eren, req, "Müşteri aradı")
    note = next(e for e in sv.list_events(s, req.id) if e.kind == "note")
    assert note.message == "Müşteri aradı" and note.assignee_id is None


def test_add_note_with_assignee_creates_task_and_completion_flow(s, world):
    eren, admin, broker = world["eren"], world["admin"], world["broker"]
    req = new_req(s, world)  # eren'in REQ'i; admin her REQ'i görebildiği için göreve atanabilir
    sv.add_note(s, eren, req, "Fiyatı kontrol et", assignee_id=admin.id)
    task = next(e for e in sv.list_events(s, req.id) if e.kind == "task")
    assert task.assignee_id == admin.id and task.done_at is None

    open_tasks = sv.list_my_open_tasks(s, admin)
    assert len(open_tasks) == 1 and open_tasks[0].id == task.id

    with pytest.raises(sv.ServiceError, match="yalnızca atanan"):
        sv.complete_task(s, broker, task.id)  # ne atanan kişi ne yönetici

    sv.complete_task(s, admin, task.id)  # atanan kişi kendi görevini tamamlayabilir
    task = next(e for e in sv.list_events(s, req.id) if e.kind == "task")
    assert task.done_at is not None
    assert sv.list_my_open_tasks(s, admin) == []


def test_complete_task_allowed_for_manage_roles_too(s, world):
    eren, admin = world["eren"], world["admin"]
    req = new_req(s, world)
    sv.add_note(s, eren, req, "Onay bekliyor", assignee_id=eren.id)  # eren kendi REQ'ine kendine görev atar
    task = next(e for e in sv.list_events(s, req.id) if e.kind == "task")
    sv.complete_task(s, admin, task.id)  # yönetici, atanan kişi olmasa da tamamlayabilir
    assert next(e for e in sv.list_events(s, req.id) if e.kind == "task").done_at is not None


def test_cancel_task(s, world):
    eren, admin, broker = world["eren"], world["admin"], world["broker"]
    req = new_req(s, world)
    sv.add_note(s, eren, req, "Gerek kalmadı", assignee_id=admin.id)
    task = next(e for e in sv.list_events(s, req.id) if e.kind == "task")

    with pytest.raises(sv.ServiceError, match="yalnızca atanan"):
        sv.cancel_task(s, broker, task.id)

    sv.cancel_task(s, admin, task.id)
    task = next(e for e in sv.list_events(s, req.id) if e.kind == "task")
    assert task.cancelled_at is not None and task.done_at is None
    assert sv.list_my_open_tasks(s, admin) == []

    sv.complete_task(s, admin, task.id)  # iptal edilmiş görev bir daha tamamlanamaz (no-op)
    assert next(e for e in sv.list_events(s, req.id) if e.kind == "task").done_at is None


def test_add_note_rejects_assignee_who_cannot_view_req(s, world):
    eren, broker = world["eren"], world["broker"]
    req = new_req(s, world)  # eren'in REQ'i, "talep" aşamasında — broker yalnızca gümrük/lojistik aşamasını görür
    with pytest.raises(sv.ServiceError, match="göremediği için"):
        sv.add_note(s, eren, req, "test", assignee_id=broker.id)


def test_list_assignable_users_for_req_scoped_to_viewers(s, world):
    eren = world["eren"]
    req = new_req(s, world)  # eren'in REQ'i, "talep" aşamasında (broker'ın gördüğü aşamalar dışında)
    names = {u.username for u in sv.list_assignable_users_for_req(s, eren, req)}
    # GEÇİCİ: tüm yöneticiler (sahiplikten bağımsız) + admin görebilir; broker "talep" aşamasını göremez.
    assert names == {"eren.memisoglu", "beyza.yazar", "eren.zorman", "zerrin.oz", "yusuf.oz"}


def test_add_note_rejects_assignee_from_other_company(s, world):
    from jarvis.models import Company, User
    eren = world["eren"]
    other_company = Company(code="OZ3", name="Başka Şirket")
    s.add(other_company)
    s.flush()
    other_user = User(company_id=other_company.id, username="disardan", name="Dışarıdan", role=pl.ADMIN)
    s.add(other_user)
    s.commit()
    req = new_req(s, world)
    with pytest.raises(sv.ServiceError, match="Geçersiz kullanıcı"):
        sv.add_note(s, eren, req, "test", assignee_id=other_user.id)


def test_list_assignable_users_scoped_to_company(s, world):
    from jarvis.models import Company, User
    admin = world["admin"]
    other_company = Company(code="OZ4", name="Başka Şirket 2")
    s.add(other_company)
    s.flush()
    other_user = User(company_id=other_company.id, username="disardan2", name="Dışarıdan 2", role=pl.ADMIN)
    s.add(other_user)
    s.commit()
    usernames = [u.username for u in sv.list_assignable_users(s, admin)]
    assert "disardan2" not in usernames and "yusuf.oz" in usernames


def test_req_attachments_upload_list_download_delete_and_size_limit(s, world):
    eren = world["eren"]
    req = new_req(s, world)
    att = sv.upload_req_attachment(s, eren, req, "urun.pdf", "application/pdf", b"%PDF-fake")
    listed = sv.list_req_attachments(s, eren, req)
    assert len(listed) == 1 and listed[0].filename == "urun.pdf"
    full = sv.get_attachment(s, eren, att.id)
    assert full.data == b"%PDF-fake"
    sv.delete_attachment(s, eren, att.id)
    assert sv.list_req_attachments(s, eren, req) == []
    with pytest.raises(sv.ServiceError, match="çok büyük"):
        sv.upload_req_attachment(s, eren, req, "big.bin", "application/octet-stream", b"0" * (pl.MAX_ATTACHMENT_BYTES + 1))


def test_set_password_rejects_other_company_user(s, world):
    from jarvis.models import Company, User
    admin = world["admin"]
    other_company = Company(code="OZ2", name="Diğer Şirket")
    s.add(other_company)
    s.flush()
    other_user = User(company_id=other_company.id, username="baska.sirket", name="Başka Şirket Kullanıcısı", role=pl.ADMIN)
    s.add(other_user)
    s.commit()

    with pytest.raises(sv.ServiceError, match="bulunamadı"):
        sv.set_password(s, admin, other_user.id, "gizlisifre123")

def test_update_req_number_fixes_code_and_counter(s, world):
    eren, cust = world["eren"], world["cust"]
    r1 = new_req(s, world)  # TTRA_REQ_17 (müşterinin sayacı 16'dan başlıyor)
    assert sv.update_req_number(s, eren, r1, 12) == "TTRA_REQ_12"
    s.refresh(cust)
    assert cust.req_seq == 12  # son açılan REQ düzeltildi -> sayaç ona çekildi, sonraki 13 olur
    assert new_req(s, world).code == "TTRA_REQ_13"
    with pytest.raises(sv.ServiceError, match="zaten kullanılıyor"):
        sv.update_req_number(s, eren, r1, 13)
    sv.update_req_number(s, eren, r1, 30)  # sayaçtan büyük numara -> sayaç ilerler
    s.refresh(cust)
    assert cust.req_seq == 30
    with pytest.raises(sv.ServiceError, match="yetkiniz"):
        sv.update_req_number(s, world["broker"], r1, 31)


def test_update_line_qtys_any_stage_but_not_below_delivered(s, world):
    eren, broker = world["eren"], world["broker"]
    req = new_req(s, world)  # ESC 10, Motor 6
    seed._progress(s, req.id, "teslim", eren, broker)
    req = sv.get_req(s, eren, req_id=req.id)
    esc = req.lines[0]
    sv.create_delivery(s, eren, req, [{"line_id": esc.id, "qty": 4}])
    req = sv.get_req(s, eren, req_id=req.id)
    with pytest.raises(sv.ServiceError, match="altına inemez"):
        sv.update_line_qtys(s, eren, req, [{"id": esc.id, "qty": 3}])
    sv.update_line_qtys(s, eren, req, [{"id": esc.id, "qty": 4}])  # teslim edilen kadar düşürmek serbest
    req = sv.get_req(s, eren, req_id=req.id)
    assert req.lines[0].qty == 4 and req.stage == "teslim"
    assert any("Adet düzeltildi" in e.message for e in sv.list_events(s, req.id))


def test_save_line_suppliers_manual_pick(s, world):
    eren = world["eren"]
    acme = sv.add_partner(s, world["admin"], name="ACME Parts", is_supplier=True)
    req = new_req(s, world)
    sv.save_line_suppliers(s, eren, req, [{"id": req.lines[0].id, "supplier_id": acme.id}, {"id": req.lines[1].id, "supplier_id": None}])
    req = sv.get_req(s, eren, req_id=req.id)
    assert req.lines[0].supplier_id == acme.id and req.lines[1].supplier_id is None
    with pytest.raises(sv.ServiceError, match="Geçersiz tedarikçi"):
        sv.save_line_suppliers(s, eren, req, [{"id": req.lines[1].id, "supplier_id": world["cust"].id}])  # müşteri, tedarikçi değil


def test_analytics_durations_products_and_briefing(s, world):
    from datetime import datetime, timedelta, timezone
    from jarvis import analytics
    eren, broker = world["eren"], world["broker"]
    assert analytics.fmt_duration(0.1) == "2 saat 24 dk" and analytics.fmt_duration(2.25) == "2 gün 6 saat"
    assert analytics.fmt_duration(0) == "-" and analytics.fmt_duration(0.0001) == "1 dk"
    req = new_req(s, world)
    seed._progress(s, req.id, "karar", eren, broker)
    reqs = sv.visible_reqs(s, eren)
    prods = analytics.product_frame(reqs)
    assert set(prods["Ürün"]) == {"ESC", "Motor"} and (prods["Kâr"] > 0).all()
    assert abs(prods["Satış"].sum() - pl.quote_for_req(reqs[0]).total) < 0.05
    durations = analytics.stage_durations(s, reqs)
    assert list(durations.columns) == ["Aşama", "Ortalama Gün", "Ortalama Saat", "Süre", "Adet"]
    facts = analytics.briefing_facts(reqs, datetime.now(timezone.utc) + timedelta(days=10))
    assert any("Müşteri kararı bekleyen" in f and req.code in f for f in facts)
    assert any("güncellenmeyen" in f for f in facts)
