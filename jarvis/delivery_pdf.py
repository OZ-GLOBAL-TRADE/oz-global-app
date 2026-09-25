"""Teslimat makbuzu PDF'i (OUT/NNNN). Girdi, DeliveryDoc.snapshot içeriğidir; fiyat/maliyet hiç bulunmaz — yalnızca
ürün adı ve adet. Düzen, kullanıcının paylaştığı gerçek Odoo teslimat fişiyle eşleşecek şekilde tasarlandı (yalnızca
tarih, saat yok; öneki OUT olan tek bir kod, ikinci bir belge kodu yok)."""
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


def _qty(v) -> str:
    return f"{v:g} Adet".replace(".", ",")


def _p(text, style) -> Paragraph:
    return Paragraph(escape(str(text or "")).replace("\n", "<br/>"), style)


def render_delivery_pdf(data: dict) -> bytes:
    _register_fonts()
    base = ParagraphStyle("base", fontName="Roboto", fontSize=9, leading=12, textColor=INK)
    small = ParagraphStyle("small", parent=base, fontSize=8, leading=10.5, textColor=MUTED)
    bold = ParagraphStyle("bold", parent=base, fontName="Roboto-Bold")
    right = ParagraphStyle("right", parent=base, alignment=TA_RIGHT)
    wordmark = ParagraphStyle("wordmark", parent=base, fontName="Roboto-Bold", fontSize=13, leading=16, textColor=ACCENT)
    title = ParagraphStyle("title", parent=base, fontName="Roboto-Bold", fontSize=20, leading=24, textColor=ACCENT)
    meta_label = ParagraphStyle("meta_label", parent=small, fontName="Roboto-Bold", textColor=ACCENT)
    th = ParagraphStyle("th", parent=base, fontName="Roboto-Bold", textColor=colors.white)
    th_right = ParagraphStyle("th_right", parent=th, alignment=TA_RIGHT)
    sign_label = ParagraphStyle("sign_label", parent=small, fontName="Roboto-Bold", textColor=ACCENT)

    company, customer = data.get("company", {}), data.get("customer", {})

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Roboto", 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(15 * mm, 10 * mm, f"{data['number']}  ·  {company.get('name', '')}")
        canvas.drawRightString(A4[0] - 15 * mm, 10 * mm, f"Sayfa {doc.page}")
        canvas.restoreState()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=18 * mm,
                            title=f"Teslimat {data['number']}", author=company.get("name", ""))
    width = A4[0] - 30 * mm

    address_cell = [_p("Teslim Adresi:", meta_label), _p(customer.get("name", ""), bold)]
    if customer.get("address"): address_cell.append(_p(customer["address"], base))
    header = Table([["", address_cell]], colWidths=[width * 0.45, width * 0.55])
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))

    story = [_p(company.get("brand") or company.get("name", ""), wordmark), Spacer(1, 5 * mm), header,
            Spacer(1, 8 * mm), _p(data["number"], title), Spacer(1, 5 * mm)]

    meta_cols = [("Sipariş:", data.get("order_ref", "-")), ("Sevkiyat Tarihi:", data["issued_at"]), ("Müşteri Referansı:", data.get("reference", "-"))]
    meta = Table([[_p(k, meta_label) for k, _ in meta_cols], [_p(v, base) for _, v in meta_cols]], colWidths=[width / 3] * 3)
    meta.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 1), (-1, 1), 2), ("BOTTOMPADDING", (0, 0), (-1, 0), 1)]))
    story += [meta, Spacer(1, 7 * mm)]

    thead = [_p("ÜRÜN", th), _p("SIPARIŞ EDİLEN", th_right), _p("TESLİM EDİLEN", th_right)]
    rows = [thead]
    for r in data["rows"]:
        rows.append([_p(r["name"], bold), _p(_qty(r["ordered"]), right), _p(_qty(r["delivered"]), right)])
    table = Table(rows, colWidths=[width * 0.5, width * 0.25, width * 0.25])
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), ACCENT), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("LINEBELOW", (0, 1), (-1, -1), 0.4, LINE), ("LINEBELOW", (0, -1), (-1, -1), 0.8, ACCENT),
                               ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    story += [table, Spacer(1, 20 * mm)]

    sign = Table([[_p("Teslim Eden:", sign_label), _p("Teslim Alan:", sign_label)],
                 [_p(data.get("delivered_by") or "", base), _p(data.get("delivered_to") or "", base)]],
                colWidths=[width * 0.45, width * 0.45])
    sign.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 1), (-1, 1), 10)]))
    story.append(sign)

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
