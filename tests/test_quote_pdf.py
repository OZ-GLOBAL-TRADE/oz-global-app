import io

import pytest

from jarvis.quote_pdf import render_quote_pdf

pypdf = pytest.importorskip("pypdf")

ROWS = [{"name": "FLYCOLOR X-Cross HV3 ESC", "spec": "5-12S · 120A", "qty": 10, "unit_price": 165.9, "line_total": 1659.0},
        {"name": "Lojistik & Nakliye", "spec": "", "qty": 1, "unit_price": 250.0, "line_total": 250.0}]


def data(tax_on: bool) -> dict:
    total = 1909.0
    tax = round(total * 0.2, 2) if tax_on else 0.0
    return {"number": "OZ260921204", "reference": "TTRA_REQ_17", "payment_ref": "OZ204", "issued_at": "21.09.2026", "valid_until": "21.10.2026",
            "currency": "USD", "delivery_type": "Kapı Teslim", "payment_terms": "%50 peşin", "tax_enabled": tax_on,
            "tax_pct": 20.0 if tax_on else 0.0, "rows": ROWS, "total": total, "tax": tax, "grand_total": round(total + tax, 2),
            "customer": {"name": "TİTRA TEKNOLOJİ A.Ş.", "address": "Çankaya / ANKARA", "tax_no": "8450621288", "email": "x@y.com"},
            "company": {"name": "OZ HAVACILIK ve SAVUNMA SAN. TİC A.Ş.", "brand": "OZ Global Trade", "address": "Ankara", "tax_info": "",
                       "phone": "", "email": "", "website": "", "bank_info": "IBAN: TR00 0000"}}


def text_of(pdf: bytes) -> str:
    return "\n".join(page.extract_text() for page in pypdf.PdfReader(io.BytesIO(pdf)).pages)


def test_pdf_matches_reference_layout_fields():
    pdf = render_quote_pdf(data(True))
    text = text_of(pdf)
    assert pdf.startswith(b"%PDF")
    for expected in ("OZ Global Trade", "Teklif # OZ260921204", "TTRA_REQ_17", "TİTRA TEKNOLOJİ A.Ş.", "VKN/TCKN: 8450621288",
                     "10 Adet", "Kapı Teslim", "1.659,00 USD", "GENEL TOPLAM", "2.290,80 USD", "IBAN: TR00 0000", "Ödeme Açıklaması: OZ204",
                     "Ödeme Koşulu: %50 peşin", "Teslim Türü: Kapı Teslim"):
        assert expected in text, expected
    assert "Para Birimi" not in text and "MÜŞTERİ" not in text  # eski üst meta alanları kaldırıldı


def test_pdf_without_tax_shows_single_total_row():
    text = text_of(render_quote_pdf(data(False)))
    assert "GENEL TOPLAM" not in text and "KDV %20" not in text and "Ara Toplam" not in text
    assert "Toplam" in text and "1.909,00 USD" in text
    assert text.count("1.909,00 USD") == 1  # toplam yalnızca bir kez görünür (eski sürümde iki kez basan hata düzeltildi)


def test_pdf_never_shows_internal_pricing_words():
    text = text_of(render_quote_pdf(data(True))).lower()
    for word in ("maliyet", "kâr", "marj", "profit"):
        assert word not in text


def test_payment_terms_multiline_shown_as_single_semicolon_joined_line():
    d = data(True)
    d["payment_terms"] = "%50 peşin\n%50 sevkiyat öncesi"
    text = text_of(render_quote_pdf(d))
    assert "Ödeme Koşulları: %50 peşin; %50 sevkiyat öncesi" in text


def test_bank_section_still_shows_delivery_type_when_bank_and_terms_are_empty():
    d = data(True)
    d["payment_terms"], d["company"] = "", {**d["company"], "bank_info": ""}
    text = text_of(render_quote_pdf(d))
    assert "BANKA BİLGİLERİ" in text and "Teslim Türü: Kapı Teslim" in text
    assert "Ödeme Koşulu" not in text
