"""Müşteriye giden teklif PDF'i. Girdi, QuoteDoc.snapshot içeriğidir: maliyet ve kâr bilgisi burada hiç bulunmaz.
Düzen, kullanıcının paylaştığı gerçek Odoo teklif taslağıyla (iki sütunlu başlık, Referansınız/Tarih/Geçerlilik satırı,
en altta Banka Bilgileri + Ödeme Açıklaması + Ödeme Koşulu + Teslim Türü) eşleşecek şekilde tasarlandı."""
import io
import os
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "fonts")
INK, MUTED, LINE, ACCENT = colors.HexColor("#111827"), colors.HexColor("#6B7280"), colors.HexColor("#D1D5DB"), colors.HexColor("#1E293B")


def _register_fonts():
    if "Roboto" in pdfmetrics.getRegisteredFontNames(): return
    pdfmetrics.registerFont(TTFont("Roboto", os.path.join(FONT_DIR, "Roboto-Regular.ttf")))
    pdfmetrics.registerFont(TTFont("Roboto-Bold", os.path.join(FONT_DIR, "Roboto-Bold.ttf")))
    pdfmetrics.registerFontFamily("Roboto", normal="Roboto", bold="Roboto-Bold", italic="Roboto", boldItalic="Roboto-Bold")


def money(v, currency: str) -> str:
    text = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{text} {currency}"


def _qty(v) -> str:
    return f"{v:g} Adet".replace(".", ",")


def _p(text, style) -> Paragraph:
    return Paragraph(escape(str(text or "")).replace("\n", "<br/>"), style)


def render_quote_pdf(data: dict) -> bytes:
    _register_fonts()
    base = ParagraphStyle("base", fontName="Roboto", fontSize=9, leading=12, textColor=INK)
    small = ParagraphStyle("small", parent=base, fontSize=8, leading=10.5, textColor=MUTED)
    bold = ParagraphStyle("bold", parent=base, fontName="Roboto-Bold")
    right = ParagraphStyle("right", parent=base, alignment=TA_RIGHT)
    right_bold = ParagraphStyle("right_bold", parent=right, fontName="Roboto-Bold")
    wordmark = ParagraphStyle("wordmark", parent=base, fontName="Roboto-Bold", fontSize=13, leading=16, textColor=ACCENT)
    company_name = ParagraphStyle("company", parent=base, fontName="Roboto-Bold", fontSize=10, leading=13)
    title = ParagraphStyle("title", parent=base, fontName="Roboto-Bold", fontSize=20, leading=24, textColor=ACCENT)
    meta_label = ParagraphStyle("meta_label", parent=small, fontName="Roboto-Bold", textColor=ACCENT)
    th = ParagraphStyle("th", parent=base, fontName="Roboto-Bold", textColor=colors.white)
    th_right = ParagraphStyle("th_right", parent=th, alignment=TA_RIGHT)

    cur, company, customer = data["currency"], data.get("company", {}), data.get("customer", {})
    tax_on = data["tax_enabled"]

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Roboto", 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(15 * mm, 10 * mm, f"{data['number']}  ·  {company.get('name', '')}")
        canvas.drawRightString(A4[0] - 15 * mm, 10 * mm, f"Sayfa {doc.page}")
        canvas.restoreState()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=18 * mm,
                            title=f"Teklif {data['number']}", author=company.get("name", ""))
    width = A4[0] - 30 * mm
    story = [_p(company.get("brand") or company.get("name", ""), wordmark), Spacer(1, 5 * mm)]

    def party(name, address, tax_line):
        cell = [_p(name, company_name)]
        if address: cell.append(_p(address, base))
        if tax_line: cell.append(_p(tax_line, base))
        return cell

    us = party(company.get("name", ""), company.get("address", ""), company.get("tax_info", ""))
    them = party(customer.get("name", ""), customer.get("address", ""), f"VKN/TCKN: {customer['tax_no']}" if customer.get("tax_no") else "")
    header = Table([[us, them]], colWidths=[width * 0.5, width * 0.5])
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    story += [header, Spacer(1, 8 * mm), _p(f"Teklif # {data['number']}", title), Spacer(1, 5 * mm)]

    meta = Table([[_p("Referansınız:", meta_label), _p("Teklif Tarihi:", meta_label), _p("Geçerlilik:", meta_label)],
                 [_p(data.get("reference", "-"), base), _p(data["issued_at"], base), _p(data["valid_until"], base)]],
                colWidths=[width / 3] * 3)
    meta.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 1), (-1, 1), 2), ("BOTTOMPADDING", (0, 0), (-1, 0), 1)]))
    story += [meta, Spacer(1, 7 * mm)]

    widths = [0.05, 0.43, 0.13, 0.14, 0.09, 0.16] if tax_on else [0.05, 0.50, 0.14, 0.15, 0.16]
    thead = [_p("#", th), _p("Açıklama", th), _p("Miktar", th_right), _p("Birim Fiyat", th_right)]
    if tax_on: thead.append(_p("KDV", th_right))
    thead.append(_p("Tutar", th_right))
    rows = [thead]
    for i, r in enumerate(data["rows"], 1):
        name_cell = [_p(r["name"], bold)] + ([_p(r["spec"], small)] if r.get("spec") else [])
        row = [_p(i, base), name_cell, _p(_qty(r["qty"]), right), _p(money(r["unit_price"], cur), right)]
        if tax_on: row.append(_p(f"%{data['tax_pct']:g}", right))
        row.append(_p(money(r["line_total"], cur), right))
        rows.append(row)
    table = Table(rows, colWidths=[width * w for w in widths], repeatRows=1)
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), ACCENT), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("LINEBELOW", (0, 1), (-1, -1), 0.4, LINE), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    story += [table, Spacer(1, 4 * mm)]

    totals = []
    if tax_on:
        totals.append([_p("Ara Toplam (KDV hariç)", right), _p(money(data["total"], cur), right)])
        totals.append([_p(f"KDV %{data['tax_pct']:g}", right), _p(money(data["tax"], cur), right)])
        totals.append([_p("GENEL TOPLAM", right_bold), _p(money(data["grand_total"], cur), right_bold)])
    else:
        totals.append([_p("Toplam", right_bold), _p(money(data["total"], cur), right_bold)])
    box = Table(totals, colWidths=[width * 0.30, width * 0.22], hAlign="RIGHT")
    box.setStyle(TableStyle([("LINEABOVE", (0, -1), (-1, -1), 0.8, ACCENT), ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    story += [box, Spacer(1, 8 * mm)]

    story.append(_p(f"Bu teklif {data['valid_until']} tarihine kadar geçerlidir." + (" Fiyatlara KDV dahil değildir." if not tax_on else ""), small))

    bank_lines = [x for x in company.get("bank_info", "").splitlines() if x.strip()]
    term_lines = [x for x in (data.get("payment_terms") or "").splitlines() if x.strip()]
    bottom = bank_lines[:]
    if data.get("payment_ref"): bottom.append(f"Ödeme Açıklaması: {data['payment_ref']}")
    if len(term_lines) == 1: bottom.append(f"Ödeme Koşulu: {term_lines[0]}")
    elif term_lines: bottom.append("Ödeme Koşulları: " + "; ".join(term_lines))
    if data.get("delivery_type"): bottom.append(f"Teslim Türü: {data['delivery_type']}")
    if bottom:
        section_head = ParagraphStyle("section_head", parent=bold, fontSize=9.5, textColor=ACCENT, spaceBefore=8)
        story += [Spacer(1, 6 * mm), _p("BANKA BİLGİLERİ:", section_head)]
        story += [_p(line, base) for line in bottom]

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
