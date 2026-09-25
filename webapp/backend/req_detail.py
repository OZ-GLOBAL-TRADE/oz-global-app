"""REQ detay sayfası için JSON serileştirici. İş mantığı içermez: veriyi jarvis.services/pipeline'dan alır, yalnızca
rolün görebildiği aşamaların verisini JSON'a koyar. Gizleme burada tek yerde yapılır — yetkisiz bir rolün göremediği
aşamanın alanları (kâr marjı, teklif, PO no, teslimat vb.) yanıta HİÇ girmez; frontend'e "gizle" demek yerine
frontend'in elinde o veri hiç olmaz (Streamlit'te panel hiç çizilmiyordu, buradaki karşılığı bu)."""
import json
from types import SimpleNamespace as NS

from jarvis import pipeline as pl, services as sv


def _iso(dt):
    return dt.isoformat() if dt else None


def _margin_label(row: dict) -> str:
    """talepler.py::_margin_label ile birebir aynı metin."""
    if row["kind"] == "lojistik":
        return f"Lojistik marjı %{row['margin_pct']:g}" if row["margin_pct"] is not None else "-"
    if row["override"]:
        return "Sabit fiyat"
    return f"%{row['margin_pct']:g}" if row["margin_pct"] is not None else "-"


def _stepper(req) -> list[dict]:
    idx, cells = pl.stage_index(req.stage), []
    for i, stage in enumerate(pl.STAGES):
        if i < idx or req.status == pl.DONE: state = "done"
        elif i == idx and req.status == pl.ACTIVE: state = "now"
        else: state = "todo"
        cells.append({"key": stage.key, "label": stage.label, "state": state})
    return cells


def _quote_docs(s, actor, req) -> list[dict]:
    return [{"id": d.id, "number": d.number, "issued_at": _iso(d.issued_at), "currency": d.currency,
             "total": d.total, "grand_total": d.grand_total, "is_latest": i == 0}
            for i, d in enumerate(sv.list_quotes(s, actor, req))]


def _teklif_section(s, actor, req) -> dict:
    """Yalnızca teklif aşamasını görebilen roller (MANAGE_ROLES) için çağrılır."""
    section = {
        "margin_pct": req.margin_pct, "tax_enabled": req.tax_enabled, "tax_pct": req.tax_pct, "valid_days": req.valid_days,
        "payment_terms": req.payment_terms, "logistics_mode": req.logistics_mode,
        "logistics_mode_label": pl.LOGISTICS_MODES[req.logistics_mode], "logistics_margin_pct": req.logistics_margin_pct,
        "quote_sent_at": _iso(req.quote_sent_at), "missing_unit_cost": any(l.unit_cost is None for l in req.lines),
        "quote": None, "hint": None, "quotes": _quote_docs(s, actor, req),
    }
    # Ürün bazlı fiyatlandırma tablosu (düzenleme formu için): satır maliyeti + satıra özel marj / doğrudan fiyat
    cost_only = pl.calculate_quote(req.lines, req.costs, 0, 0, req.logistics_mode)
    section["line_pricing"] = [{"id": l.id, "name": l.name, "qty": l.qty, "cost": cost_only.rows[i]["cost"],
                                "margin_pct": l.margin_pct, "sale_price_override": l.sale_price_override}
                               for i, l in enumerate(req.lines)]
    if req.margin_pct is None: return section  # Streamlit'teki gibi: marj girilmediyse hesap gösterilmez
    q = pl.quote_for_req(req)
    section["hint"] = pl.delivery_hint(req.delivery_type, q.cost_customs)
    section["quote"] = quote_dict(q)
    return section


def quote_dict(q) -> dict:
    return {
        "cost_products": q.cost_products, "cost_customs": q.cost_customs, "cost_logistics": q.cost_logistics,
        "cost_other": q.cost_other, "cost_total": q.cost_total, "profit": q.profit, "total": q.total, "tax": q.tax,
        "grand_total": q.grand_total,
        "rows": [{"name": r["name"], "qty": r["qty"], "unit_cost": (r["cost"] / r["qty"]) if r["qty"] else 0.0,
                  "unit_price": r["unit_price"], "line_total": r["line_total"], "margin_label": _margin_label(r),
                  "kind": r["kind"]} for r in q.rows],
    }


def to_float(v):
    """JSON'dan gelen sayıyı float'a çevirir; boş/geçersiz/NaN → None."""
    if v is None or isinstance(v, bool): return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def preview(actor, req, body: dict) -> dict:
    """Kaydedilmemiş form değerleriyle canlı hesap (Streamlit'teki 'patched satırlar → calculate_quote' önizlemesinin
    karşılığı). Hesap tek kaynaktan (pipeline.calculate_quote) yapılır, frontend'de tekrar yazılmaz. Hiçbir şey kaydetmez.
    body: {lines: [{id, unit_cost?, unit_customs?, unit_logistics?, margin_pct?, sale_price_override?}],
           costs: [{label, amount, kind}], teklif: {margin_pct, logistics_margin_pct, tax_enabled, tax_pct, logistics_mode}}"""
    given = {int(l["id"]): l for l in body.get("lines") or [] if isinstance(l, dict) and l.get("id") is not None}

    def pick(line, key):
        src = given.get(line.id)
        return to_float(src.get(key)) if src is not None and key in src else getattr(line, key)

    def clean_override(v):  # 0 ya da altı "boş" sayılır (services.save_line_values ile aynı kural)
        return None if v is not None and v <= 0 else v

    lines = [NS(name=l.name, qty=l.qty, unit_cost=pick(l, "unit_cost"), unit_customs=pick(l, "unit_customs"),
                unit_logistics=pick(l, "unit_logistics"), margin_pct=pick(l, "margin_pct"),
                sale_price_override=clean_override(pick(l, "sale_price_override"))) for l in req.lines]
    if isinstance(body.get("costs"), list):
        costs = [NS(kind=c.get("kind") if c.get("kind") in pl.COST_KINDS else "diger", amount=to_float(c.get("amount")) or 0.0)
                 for c in body["costs"] if isinstance(c, dict) and (c.get("label") or to_float(c.get("amount")) is not None)]
    else:
        costs = list(req.costs)

    cost_view = pl.calculate_quote(lines, costs, 0, 0, "dahil")
    result = {"cost_summary": {"products": cost_view.cost_products, "customs": cost_view.cost_customs,
                               "logistics": cost_view.cost_logistics, "other": cost_view.cost_other},
              "hint": pl.delivery_hint(req.delivery_type, cost_view.cost_customs), "quote": None,
              "line_costs": None}
    if not pl.can_view_stage(actor.role, "teklif"): return result  # marj/teklif verisi yetkisiz role hiç dönmez

    t = body.get("teklif") if isinstance(body.get("teklif"), dict) else {}
    margin = to_float(t["margin_pct"]) if "margin_pct" in t else req.margin_pct
    mode = t.get("logistics_mode") if t.get("logistics_mode") in pl.LOGISTICS_MODES else req.logistics_mode
    per_line = pl.calculate_quote(lines, costs, 0, 0, mode)
    result["line_costs"] = [r["cost"] for r in per_line.rows if r["kind"] == "urun"]
    if margin is None: return result
    tax_on = bool(t["tax_enabled"]) if "tax_enabled" in t else req.tax_enabled
    tax = to_float(t["tax_pct"]) if "tax_pct" in t else req.tax_pct
    logi = to_float(t["logistics_margin_pct"]) if "logistics_margin_pct" in t else req.logistics_margin_pct
    q = pl.calculate_quote(lines, costs, margin, (tax or 0.0) if tax_on else 0.0, mode, logi)
    result["quote"] = quote_dict(q)
    result["hint"] = pl.delivery_hint(req.delivery_type, q.cost_customs)
    result["missing_unit_cost"] = any(l.unit_cost is None for l in lines)
    return result


def _teslim_section(s, actor, req) -> dict:
    rows = []
    for l in req.lines:
        delivered = pl.delivered_qty(req, l.id)
        rows.append({"line_id": l.id, "name": l.name, "ordered": l.qty, "delivered": delivered,
                     "remaining": (l.qty or 0) - delivered})
    docs = []
    for d in sv.list_deliveries(s, actor, req):
        snap = json.loads(d.snapshot)
        docs.append({"id": d.id, "number": d.number, "issued_at": _iso(d.issued_at),
                     "total_qty": sum(r["delivered"] for r in snap["rows"]),
                     "delivered_by": d.delivered_by, "delivered_to": d.delivered_to})
    return {"rows": rows, "deliveries": docs, "customer": req.customer.name,
            "all_delivered": all(r["delivered"] >= (r["ordered"] or 0) - 1e-9 for r in rows)}


def build(s, actor, req) -> dict:
    role = actor.role
    can = lambda key: pl.can_view_stage(role, key)
    products = {p.id: p for p in sv.list_products(s, actor)}
    events = sv.list_events(s, req.id, actor)
    # Katalogdan silinmiş bir ürün mevcut satırlarda kalır: bilgisi ilişkiden okunur, Talep formunda da seçenek olarak yer alır
    prod = lambda l: products.get(l.product_id) or (l.product if l.product_id else None)
    line_products = {p.id: p for p in (prod(l) for l in req.lines) if p}
    line_suppliers = {l.supplier_id: l.supplier for l in req.lines if l.supplier}

    visible = [k for k in pl.visible_stages(role) if pl.stage_index(k) <= pl.stage_index(req.stage)]
    current = req.stage if req.stage in visible else visible[-1]
    cost_view = pl.calculate_quote(req.lines, req.costs, 0, 0, "dahil")  # yalnızca maliyet toplamları (marj/teklif içermez)

    detail = {
        "code": req.code, "customer": req.customer.name, "owner": req.owner.name, "status": req.status,
        "status_label": pl.STATUS_LABELS[req.status], "stage": req.stage, "stage_label": pl.STAGE_BY_KEY[req.stage].label,
        "waiting": pl.STAGE_BY_KEY[req.stage].waiting if req.status == pl.ACTIVE else None,
        "currency": req.currency, "delivery_type": req.delivery_type, "notes": req.notes,
        "shelved_reason": req.shelved_reason if req.status == pl.SHELVED else None,
        "created_at": _iso(req.created_at), "updated_at": _iso(req.updated_at),
        "stepper": _stepper(req), "visible_stages": visible, "current_stage": current,
        "can_edit_current": req.status == pl.ACTIVE and pl.can_edit_stage(role, current),
        # Yazma bayrakları: yetki kararı yine servis katmanında verilir (burası yalnızca düğmeleri göstermek/gizlemek için)
        "can_advance": req.status == pl.ACTIVE and pl.can_edit_stage(role, req.stage),
        "can_manage": role in pl.MANAGE_ROLES,
        "can_move_back": req.status == pl.ACTIVE and role in pl.MANAGE_ROLES and pl.prev_stage(req.stage) is not None,
        "can_shelve": req.status == pl.ACTIVE and role in pl.MANAGE_ROLES,
        "can_reopen": req.status == pl.SHELVED and role in pl.MANAGE_ROLES,
        "can_fix": req.status == pl.ACTIVE and role in pl.MANAGE_ROLES,  # REQ no / para birimi / adet / müşteri / not düzeltme
        "can_delete": role in pl.MANAGE_ROLES,  # çöp kutusuna taşıma (kargoya bağlıysa servis reddeder)
        "currencies": pl.CURRENCIES,
        "customer_id": req.customer_id,
        # Müşteri değiştirme: teklif/teslimat makbuzu çıktıysa servis reddeder; arayüz nedenini önceden göstersin
        "customer_change_blocked": bool(req.quotes or req.deliveries),
        "customer_options": [{"id": c.id, "name": c.name} for c in sv.list_partners(s, actor, customers=True)]
                            if req.status == pl.ACTIVE and role in pl.MANAGE_ROLES else [],
        "next_stage_label": pl.STAGE_BY_KEY[pl.next_stage(req.stage)].label if pl.next_stage(req.stage) else None,
        "move_back_reasons": pl.MOVE_BACK_REASONS, "shelve_reasons": pl.SHELVE_REASONS,
        "assignable_users": [{"id": u.id, "name": u.name} for u in sv.list_assignable_users_for_req(s, actor, req)],
        # Talep / Fiyat / Gümrük / Lojistik aşamaları tüm rollere açık (pipeline.STAGES) — ortak veri
        "lines": [{"id": l.id, "name": l.name, "qty": l.qty,
                   "hs_code": prod(l).hs_code if prod(l) else "",
                   "catalog_last_cost": prod(l).last_cost if prod(l) else None,
                   "unit_cost": l.unit_cost, "unit_customs": l.unit_customs, "unit_logistics": l.unit_logistics,
                   "supplier": l.supplier.name if l.supplier else None, "supplier_id": l.supplier_id, "product_id": l.product_id} for l in req.lines],
        # Talep formu için katalog (yalnızca Talep aşamasında, düzenleme yetkisi varsa) ve teslimat tipleri
        "product_options": [{"id": p.id, "name": p.name, "hs_code": p.hs_code} for p in {**products, **line_products}.values()]
                           if req.status == pl.ACTIVE and req.stage == "talep" and pl.can_edit_stage(role, "talep") else [],
        "delivery_types": pl.DELIVERY_TYPES,
        # Düzenleme formları için seçenekler (yalnızca ilgili aşamada, düzenleme yetkisi varsa)
        "supplier_options": [{"id": p.id, "name": p.name} for p in {**{x.id: x for x in sv.list_partners(s, actor, suppliers=True)}, **line_suppliers}.values()]
                            if req.status == pl.ACTIVE and req.stage in ("talep", "fiyat") and pl.can_edit_stage(role, req.stage) else [],
        "cost_kinds": [{"key": k, "label": v} for k, v in pl.COST_KINDS.items()],
        "logistics_modes": [{"key": k, "label": v} for k, v in pl.LOGISTICS_MODES.items()],
        "margin_warn_pct": pl.MARGIN_WARN_PCT,
        "costs": [{"label": c.label, "kind": c.kind, "kind_label": pl.COST_KINDS.get(c.kind, "Diğer"), "amount": c.amount}
                  for c in req.costs],
        "cost_summary": {"products": cost_view.cost_products, "customs": cost_view.cost_customs,
                         "logistics": cost_view.cost_logistics, "other": cost_view.cost_other},
        "delivery_hint": pl.delivery_hint(req.delivery_type, cost_view.cost_customs),
        "shipments": [{"code": sh.code, "logistics_status": sh.logistics_status, "awb_no": sh.awb_no,
                       "qty_here": sum(it.qty for it in sh.items if it.req_id == req.id)}
                      for sh in sv.req_shipments(s, actor, req)] if can("lojistik") else [],
        "teklif": _teklif_section(s, actor, req) if can("teklif") else None,
        "karar": {"decision": req.decision} if can("karar") else None,
        "siparis": {"customer_po_no": req.customer_po_no, "po_number": req.po_number,
                    "po_approved_at": _iso(req.po_approved_at)} if can("siparis") else None,
        "teslim": _teslim_section(s, actor, req) if can("teslim") else None,
    }

    notes_tasks = [e for e in events if e.kind in ("note", "task")]
    detail["open_tasks"] = sum(1 for e in notes_tasks if e.kind == "task" and not e.done_at and not e.cancelled_at)
    detail["notes_tasks"] = [{
        "id": e.id, "kind": e.kind, "created_at": _iso(e.created_at), "user": e.user.name if e.user else None,
        "assignee": e.assignee.name if e.assignee else None, "message": e.message,
        "state": ("done" if e.done_at else "cancelled" if e.cancelled_at else "open") if e.kind == "task" else None,
        "can_act": e.kind == "task" and (actor.id == e.assignee_id or role in pl.MANAGE_ROLES),
        "can_delete": actor.id == e.user_id or role in pl.MANAGE_ROLES,  # yazan kişi ya da yönetici (sv.delete_note aynısını zorlar)
        "done_at": _iso(e.done_at), "cancelled_at": _iso(e.cancelled_at),
    } for e in notes_tasks]
    detail["history"] = [{"kind": e.kind, "created_at": _iso(e.created_at), "user": e.user.name if e.user else None,
                          "message": e.message} for e in events if e.kind not in ("note", "task")][:60]
    detail["attachments"] = [{"id": a.id, "filename": a.filename, "size": a.size, "content_type": a.content_type,
                              "uploaded_at": _iso(a.uploaded_at)} for a in sv.list_req_attachments(s, actor, req)]
    return detail
