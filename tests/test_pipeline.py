from types import SimpleNamespace as NS

import pytest

from jarvis import pipeline as pl


def line(name, qty, cost=None, customs=None, logistics=None):
    return NS(name=name, qty=qty, unit_cost=cost, unit_customs=customs, unit_logistics=logistics)


def extra(kind, amount):
    return NS(kind=kind, amount=amount)


TTRA_17 = [line("ESC", 10, 132.95, 0), line("Motor", 6, 77.08, 0), line("Rx", 2, 176.72, 0), line("VTX", 7, 90.72, 0)]


def test_quote_matches_odoo_ttra_req_17():
    # Odoo: 2.780,46 maliyet, %20 kâr -> 3.336,552 teklif, 556,092 kâr (marj maliyet üzerinden).
    q = pl.calculate_quote(TTRA_17, [], 20, 20)
    assert q.cost_total == 2780.46
    assert q.total == pytest.approx(3336.552, abs=0.05)
    assert q.profit == pytest.approx(556.092, abs=0.05)
    assert q.total == round(sum(r["line_total"] for r in q.rows), 2)
    assert q.grand_total == round(q.total + q.tax, 2)


def test_margin_is_markup_on_cost():
    q = pl.calculate_quote([line("A", 1, 100, 0)], [], 25, 0)
    assert q.total == 125.0 and q.profit == 25.0


def test_extra_costs_are_allocated_and_included():
    lines = [line("A", 2, 100, 10), line("B", 1, 50, 0)]
    q = pl.calculate_quote(lines, [extra("diger", 30.0)], 0, 0)
    assert q.cost_products == 250.0 and q.cost_customs == 20.0 and q.cost_other == 30.0
    assert q.cost_total == 300.0
    assert q.total == pytest.approx(300.0, abs=0.02)


def test_extra_costs_without_prices_are_split_by_quantity():
    q = pl.calculate_quote([line("A", 3), line("B", 1)], [extra("diger", 40.0)], 0, 0)
    assert [r["line_total"] for r in q.rows] == [30.0, 10.0]


def test_empty_quote_is_zero():
    q = pl.calculate_quote([], [], None, None)
    assert q.total == 0 and q.cost_total == 0 and q.grand_total == 0


def req(**kw):
    base = dict(customer_id=1, lines=[line("A", 1, 10, 1)], costs=[], margin_pct=20.0, logistics_margin_pct=None, tax_pct=20.0,
                tax_enabled=True, logistics_mode="dahil", quote_sent_at=None, decision=None, po_approved_at=None)
    return NS(**{**base, **kw})


def test_gate_talep():
    assert pl.check_gate("talep", req()) == []
    assert pl.check_gate("talep", req(lines=[]))
    assert pl.check_gate("talep", req(customer_id=None))
    assert pl.check_gate("talep", req(lines=[line("A", 0)]))


def test_gate_fiyat_needs_positive_unit_cost():
    assert pl.check_gate("fiyat", req()) == []
    assert pl.check_gate("fiyat", req(lines=[line("A", 1, None, None)]))
    assert pl.check_gate("fiyat", req(lines=[line("A", 1, 0, None)]))


def test_gate_gumruk_distinguishes_empty_from_zero():
    assert pl.check_gate("gumruk", req(lines=[line("A", 1, 10, None)]))
    assert pl.check_gate("gumruk", req(lines=[line("A", 1, 10, 0)])) == []


def test_gate_teklif_needs_margin_and_sent_flag():
    from datetime import datetime
    assert pl.check_gate("teklif", req(margin_pct=None))
    assert pl.check_gate("teklif", req())  # marj var ama iletildi işaretlenmemiş
    assert pl.check_gate("teklif", req(quote_sent_at=datetime.now())) == []
    assert pl.check_gate("teklif", req(quote_sent_at=datetime.now(), lines=[line("A", 1, 0, 0)]))  # teklif tutarı 0


def test_gate_karar_and_siparis():
    from datetime import datetime
    assert pl.check_gate("karar", req())
    assert pl.check_gate("karar", req(decision="ret"))
    assert pl.check_gate("karar", req(decision="onay")) == []
    assert pl.check_gate("siparis", req())
    assert pl.check_gate("siparis", req(po_approved_at=datetime.now())) == []


def test_visibility_rules():
    r = NS(owner_id=5, status="aktif", stage="gumruk")
    assert pl.can_view_req(1, pl.ADMIN, r)
    # GEÇİCİ (kullanıcı yetkilendirme modülüne kadar): TRADE_MANAGER artık sahiplikten bağımsız her REQ'i görür.
    assert pl.can_view_req(5, pl.TRADE_MANAGER, r) and pl.can_view_req(6, pl.TRADE_MANAGER, r)
    assert pl.can_view_req(9, pl.CUSTOMS_BROKER, r)
    assert not pl.can_view_req(9, pl.CUSTOMS_BROKER, NS(owner_id=5, status="aktif", stage="teklif"))
    assert not pl.can_view_req(9, pl.CUSTOMS_BROKER, NS(owner_id=5, status="rafa", stage="gumruk"))


def test_broker_never_sees_pricing_stages():
    assert pl.visible_stages(pl.CUSTOMS_BROKER) == ["talep", "fiyat", "gumruk", "lojistik"]
    assert "teklif" in pl.visible_stages(pl.TRADE_MANAGER)


def test_stage_navigation():
    assert pl.next_stage("talep") == "fiyat" and pl.next_stage("teslim") is None
    assert pl.prev_stage("fiyat") == "talep" and pl.prev_stage("talep") is None


def test_customs_and_logistics_are_tracked_separately():
    lines = [line("A", 10, 100, 8, 5), line("B", 2, 50, 3, 1)]
    q = pl.calculate_quote(lines, [extra("gumruk", 40), extra("lojistik", 60), extra("diger", 10)], 0, 0)
    assert q.cost_products == 1100.0
    assert q.cost_customs == 126.0      # 10*8 + 2*3 + 40
    assert q.cost_logistics == 112.0    # 10*5 + 2*1 + 60
    assert q.cost_other == 10.0
    assert q.cost_total == 1348.0
    assert q.total == pytest.approx(1348.0, abs=0.05)


def test_separate_logistics_line_keeps_product_prices_and_total_unchanged():
    lines, extras = [line("A", 10, 100, 0, 5)], [extra("lojistik", 50)]
    included = pl.calculate_quote(lines, extras, 20, 0, "dahil")
    separate = pl.calculate_quote(lines, extras, 20, 0, "ayri")
    assert len(included.rows) == 1 and included.rows[0]["unit_price"] == 132.0   # (1000 + 100) x 1.2 / 10
    assert len(separate.rows) == 2 and separate.rows[0]["unit_price"] == 120.0   # ham fiyat x 1.2, lojistiksiz
    assert separate.rows[1]["name"] == "Lojistik & Nakliye" and separate.rows[1]["line_total"] == 120.0  # (50 + 50) x 1.2
    assert included.total == separate.total == 1320.0
    assert included.cost_total == separate.cost_total == 1100.0


def test_no_logistics_line_when_there_is_no_logistics_cost():
    assert len(pl.calculate_quote([line("A", 1, 100, 0)], [], 20, 0, "ayri").rows) == 1


def test_tax_can_be_switched_off_per_quote():
    r = NS(lines=[line("A", 1, 100, 0)], costs=[], margin_pct=0.0, logistics_margin_pct=None, tax_pct=20.0, tax_enabled=False, logistics_mode="dahil")
    q = pl.quote_for_req(r)
    assert q.tax == 0 and q.grand_total == q.total == 100.0
    r.tax_enabled = True
    q = pl.quote_for_req(r)
    assert q.tax == 20.0 and q.grand_total == 120.0


def test_delivery_hint_follows_the_customs_rule():
    assert pl.delivery_hint("Gümrük Teslim", 100.0)      # gümrük teslimde gümrük masrafı genelde eklenmez
    assert pl.delivery_hint("Kapı Teslim", 0.0)          # kapı teslimde eklenir
    assert pl.delivery_hint("Gümrük Teslim", 0.0) is None
    assert pl.delivery_hint("Kapı Teslim", 50.0) is None


def test_per_line_margin_overrides_default():
    lines = [line("A", 10, 100, 0), line("B", 5, 100, 0)]
    lines[0].margin_pct = 50.0   # A kendi marjını kullanır
    q = pl.calculate_quote(lines, [], 20, 0)
    assert q.rows[0]["unit_price"] == 150.0 and q.rows[0]["margin_pct"] == 50.0   # 100 x 1.5
    assert q.rows[1]["unit_price"] == 120.0 and q.rows[1]["margin_pct"] == 20.0   # 100 x 1.2 (REQ varsayılanı)


def test_sale_price_override_ignores_margin_but_keeps_cost_reporting():
    l = line("A", 4, 100, 10)
    l.sale_price_override = 130.0
    l.margin_pct = 999.0  # override varken marj tamamen yok sayılır
    q = pl.calculate_quote([l], [], 20, 0)
    row = q.rows[0]
    assert row["unit_price"] == 130.0 and row["line_total"] == 520.0 and row["override"] is True and row["margin_pct"] is None
    assert row["cost"] == 440.0          # maliyet marjdan bağımsız hesaplanmaya devam eder (iç raporlama için)
    assert q.cost_total == 440.0 and q.total == 520.0 and q.profit == 80.0


def test_logistics_margin_applies_only_to_separate_logistics_line():
    lines = [line("A", 10, 100, 0, 5)]
    default_only = pl.calculate_quote(lines, [], 20, 0, "ayri")
    with_own = pl.calculate_quote(lines, [], 20, 0, "ayri", logistics_margin_pct=100.0)
    assert default_only.rows[1]["unit_price"] == 60.0    # 50 x 1.2 (varsayılan marj)
    assert with_own.rows[1]["unit_price"] == 100.0        # 50 x 2.0 (kendi marjı)
    assert with_own.rows[0]["unit_price"] == default_only.rows[0]["unit_price"] == 120.0  # ürün marjı etkilenmez
    assert pl.calculate_quote(lines, [], 20, 0, "dahil", logistics_margin_pct=100.0).rows[0]["unit_price"] == 126.0  # 'dahil'de lojistik marjı yok sayılır (1050 x 1.2 / 10)