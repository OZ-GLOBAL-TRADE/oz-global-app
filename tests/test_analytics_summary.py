import json

from conftest import new_req
from jarvis import analytics, services as sv

RATES = {"USD": 1.0, "EUR": 0.5, "TRY": 40.0}  # 1 USD = 0.5 EUR = 40 TRY


def _price(s, req):
    """ESC 10 + Motor 6, birim alış 10, marj %25 → maliyet 160, teklif 200, kâr 40 (kendi para biriminde)."""
    for line in req.lines: line.unit_cost, line.unit_customs = 10.0, 0.0
    req.margin_pct = 25.0
    s.commit()


def _frames(s, world):
    reqs = sv.visible_reqs(s, world["admin"])
    return analytics.reqs_frame(reqs), analytics.product_frame(reqs)


def test_financial_summary_converts_every_currency_to_display_currency(s, world):
    usd, eur = new_req(s, world), new_req(s, world, currency="EUR")
    _price(s, usd), _price(s, eur)
    df, prods = _frames(s, world)

    r = analytics.financial_summary(df, prods, "USD", RATES)
    assert r["priced"] and r["missing"] == 0
    assert r["total_offer"] == 200 + 400  # 200 USD + 200 EUR (= 400 USD)
    assert r["total_profit"] == 40 + 80
    assert r["margin_on_cost_pct"] == 25.0  # kâr / maliyet
    assert r["rates"] == {"EUR": 0.5, "TRY": 40.0}

    r = analytics.financial_summary(df, prods, "TRY", RATES)
    assert r["total_offer"] == 200 * 40 + 200 / 0.5 * 40  # 8000 + 16000


def test_financial_summary_without_rates_counts_only_matching_currency_and_reports_the_rest(s, world):
    _price(s, new_req(s, world)), _price(s, new_req(s, world, currency="EUR"))
    df, prods = _frames(s, world)
    r = analytics.financial_summary(df, prods, "USD", None)
    assert r["total_offer"] == 200 and r["missing"] == 1 and r["rates"] is None


def test_financial_summary_excludes_shelved_and_unpriced_and_reports_unpriced_state(s, world):
    a, b = new_req(s, world), new_req(s, world)
    df, prods = _frames(s, world)
    assert analytics.financial_summary(df, prods, "USD", RATES) == {"priced": False}  # hiçbiri fiyatlanmadı

    _price(s, a), _price(s, b)
    sv.shelve_req(s, world["admin"], b, "Bütçe yok")
    df, prods = _frames(s, world)
    assert analytics.financial_summary(df, prods, "USD", RATES)["total_offer"] == 200  # rafa kaldırılan hariç


def test_financial_summary_win_rate_groups_and_months(s, world):
    a, b = new_req(s, world, "eren"), new_req(s, world, "beyza")
    _price(s, a), _price(s, b)
    a.decision, b.decision = "onay", "ret"
    s.commit()
    df, prods = _frames(s, world)
    r = analytics.financial_summary(df, prods, "USD", RATES)
    assert r["win_rate_pct"] == 50 and r["decided"] == 2 and r["wins"] == 1
    assert {m["name"] for m in r["by_manager"]} == {"Eren Memişoğlu", "Beyza Yazar"} and all(m["offer"] == 200 for m in r["by_manager"])
    assert [c["name"] for c in r["by_customer"]] == ["TİTRA TEKNOLOJİ"] and r["by_customer"][0]["offer"] == 400
    assert len(r["monthly"]) == 1 and r["monthly"][0]["opened"] == 2 and r["monthly"][0]["offer"] == 400


def test_product_summary_ranks_by_profit_and_is_json_safe_with_zero_cost_lines(s, world):
    req = new_req(s, world)
    for line in req.lines: line.unit_cost, line.unit_customs = 10.0, 0.0
    req.lines[1].unit_cost = 0.0  # maliyeti 0 olan ürün: marj tanımsız (NaN) → JSON'da None olmalı
    req.margin_pct = 25.0
    s.commit()
    df, prods = _frames(s, world)
    r = analytics.financial_summary(df, prods, "USD", RATES)
    json.dumps(r, allow_nan=False)  # NaN sızarsa ValueError verir (FastAPI de aynı şekilde 500 verirdi)
    top = r["products"]["top_profit"]
    assert [p["name"] for p in top] == ["ESC", "Motor"] and top[0]["margin_pct"] == 25.0
    assert next(p for p in r["products"]["table"] if p["name"] == "Motor")["margin_pct"] is None
    assert all(p["name"] != "Motor" for p in r["products"]["lowest_margin"])  # marjı tanımsız olan sıralamaya girmez
