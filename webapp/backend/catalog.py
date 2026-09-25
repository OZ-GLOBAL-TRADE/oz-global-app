"""Kişiler (müşteri/tedarikçi) ve Ürünler (katalog) endpoint'leri. İş mantığı ve yetki jarvis.services'te
(add_partner, update_records, add_product…); burada yalnızca HTTP/JSON. Streamlit'teki kisiler.py / urunler.py'nin karşılığı."""
from fastapi import APIRouter, Depends, HTTPException

import req_detail
from deps import get_actor, rows as body_rows, text
from jarvis import pipeline as pl, services as sv
from jarvis.db import session_scope
from jarvis.models import Partner, Product

router = APIRouter(prefix="/api")

IDENTITY_FIELDS = ("name", "short_code")  # düzenlenebilir ama update_records'tan geçmez (kendi kuralları var)
PARTNER_FIELDS = ("kind", "tax_no", "address", "email", "phone", "category", "keywords", "country", "notes")
PRODUCT_TEXT_FIELDS = ("category", "hs_code", "spec", "notes")


# ---------------------------------------------------------------- kişiler

def _partner_row(p, usage: dict | None = None) -> dict:
    u = (usage or {}).get(p.id, {})  # silme uyarısı için: bağlı REQ / satır / ürün sayıları
    return {"req_count": u.get("reqs", 0), "line_count": u.get("lines", 0), "product_count": u.get("products", 0),
            "id": p.id, "name": p.name, "short_code": p.short_code, "req_seq": p.req_seq, "kind": p.kind, "tax_no": p.tax_no,
            "address": p.address, "email": p.email, "phone": p.phone, "category": p.category, "keywords": p.keywords,
            "country": p.country, "notes": p.notes}


def _partner_type(value) -> str:
    if value not in ("customers", "suppliers"): raise HTTPException(400, "Geçersiz kişi türü.")
    return value


def _partner_payload(s, actor, kind: str) -> dict:
    partners = sv.list_partners(s, actor, customers=kind == "customers", suppliers=kind == "suppliers")
    usage = sv.partner_usage(s, actor)
    return {"partners": [_partner_row(p, usage) for p in partners], "can_edit": actor.role in pl.MANAGE_ROLES,
            "customer_kinds": pl.CUSTOMER_KINDS, "supplier_categories": pl.SUPPLIER_CATEGORIES}


@router.get("/partners")
def list_partners(type: str = "customers", actor: sv.Actor = Depends(get_actor)):
    kind = _partner_type(type)
    with session_scope() as s:
        return _partner_payload(s, actor, kind)


@router.post("/partners/update")
def update_partners(body: dict, actor: sv.Actor = Depends(get_actor)):
    """Tablodan toplu düzenleme (ad ve kod alanları hariç; kurallar sv.update_records'ta). rows: [{id, <yalnızca değişen alanlar>}]."""
    kind = _partner_type(body.get("type"))
    clean = []
    for r in body_rows(body, "rows"):
        if not isinstance(r.get("id"), int): raise HTTPException(400, "Geçersiz kayıt.")
        clean.append({"id": r["id"], **{k: (r[k] if isinstance(r[k], str) else "") for k in PARTNER_FIELDS + IDENTITY_FIELDS if k in r}})
    with session_scope() as s:
        changed = 0
        for r in clean:  # ad ve kısa kod ayrı kurallı servislerdedir (çakışma/normalleştirme); önce onlar, sonra sıradan alanlar
            p = s.get(Partner, r["id"])
            if not p: continue  # bilinmeyen kayıt: update_records da yok sayar
            if "name" in r:
                before = p.name
                sv.rename_partner(s, actor, p.id, r["name"])
                changed += p.name != before
            if "short_code" in r:
                before = p.short_code
                sv.change_short_code(s, actor, p.id, r["short_code"])
                changed += p.short_code != before
        changed += sv.update_records(s, actor, Partner, [{k: v for k, v in r.items() if k not in IDENTITY_FIELDS} for r in clean])
        return {**_partner_payload(s, actor, kind), "changed": changed}


@router.post("/partners/{partner_id}/delete")
def delete_partner(partner_id: int, body: dict, actor: sv.Actor = Depends(get_actor)):
    """Çöp kutusuna taşır (geri yüklenebilir). Yanıt: kişi listesinin yenisi (`type`: hangi liste açıksa)."""
    kind = _partner_type(body.get("type"))
    with session_scope() as s:
        p = sv.delete_partner(s, actor, partner_id)
        return {**_partner_payload(s, actor, kind), "removed": {"name": p.name}}


@router.post("/partners")
def add_partner(body: dict, actor: sv.Actor = Depends(get_actor)):
    """Yeni müşteri ya da tedarikçi (Streamlit'teki 'Yeni müşteri/tedarikçi ekle' formlarının alanları)."""
    if body.get("type") not in ("customer", "supplier"): raise HTTPException(400, "Geçersiz kişi türü.")
    is_customer = body["type"] == "customer"
    fields = {k: text(body, k) for k in PARTNER_FIELDS if k in body}
    extra: dict = {}
    if is_customer:
        seq = req_detail.to_float(body.get("req_seq"))
        if seq is not None and (seq < 0 or seq != int(seq)): raise HTTPException(400, "Son REQ no 0 ya da pozitif bir tam sayı olmalı.")
        extra = {"short_code": text(body, "short_code"), "req_seq": int(seq or 0)}
    with session_scope() as s:
        p = sv.add_partner(s, actor, name=text(body, "name"), is_customer=is_customer, is_supplier=not is_customer, **extra, **fields)
        added = {"name": p.name, "short_code": p.short_code}
        return {**_partner_payload(s, actor, "customers" if is_customer else "suppliers"), "added": added}


# ---------------------------------------------------------------- ürünler

def _product_row(p, usage: dict | None = None) -> dict:
    return {"line_count": (usage or {}).get(p.id, 0), "id": p.id, "name": p.name, "category": p.category, "hs_code": p.hs_code, "last_cost": p.last_cost,
            "spec": p.spec, "notes": p.notes, "default_supplier_id": p.default_supplier_id}


def _product_payload(s, actor) -> dict:
    manage = actor.role in pl.MANAGE_ROLES
    usage = sv.product_usage(s, actor)  # silme uyarısı için: ürünün kaç (silinmemiş) REQ satırında kullanıldığı
    return {
        "products": [_product_row(p, usage) for p in sv.list_products(s, actor)],
        "suppliers": [{"id": p.id, "name": p.name} for p in sv.list_partners(s, actor, suppliers=True)],
        "categories": pl.PRODUCT_CATEGORIES, "can_add": manage,
        # Gümrükçü yalnızca GTİP kodunu düzenleyebilir (services.update_records bunu ayrıca zorlar)
        "editable_fields": ["name", "category", "hs_code", "last_cost", "spec", "notes"] if manage else ["hs_code"] if actor.role == pl.CUSTOMS_BROKER else [],
    }


def _cost(value):
    """last_cost: boş → None; sayı değilse ya da negatifse 400."""
    if value is None or value == "": return None
    v = req_detail.to_float(value)
    if v is None or v < 0: raise HTTPException(400, "Son alış fiyatı geçerli, negatif olmayan bir sayı olmalı.")
    return v


@router.get("/products")
def list_products(actor: sv.Actor = Depends(get_actor)):
    with session_scope() as s:
        return _product_payload(s, actor)


@router.post("/products/update")
def update_products(body: dict, actor: sv.Actor = Depends(get_actor)):
    """rows: [{id, <yalnızca değişen alanlar>}] — ürün adı düzenlenemez."""
    clean = []
    for r in body_rows(body, "rows"):
        if not isinstance(r.get("id"), int): raise HTTPException(400, "Geçersiz kayıt.")
        row = {"id": r["id"], **{k: (r[k] if isinstance(r[k], str) else "") for k in PRODUCT_TEXT_FIELDS if k in r}}
        if "last_cost" in r: row["last_cost"] = _cost(r["last_cost"])
        if isinstance(r.get("name"), str): row["name"] = r["name"]
        clean.append(row)
    with session_scope() as s:
        changed = 0
        for r in clean:  # ad ayrı kurallı serviste (çakışma denetimi); sonra sıradan alanlar
            if "name" not in r: continue
            p = s.get(Product, r["id"])
            if not p: continue
            before = p.name
            sv.rename_product(s, actor, p.id, r["name"])
            changed += p.name != before
        changed += sv.update_records(s, actor, Product, [{k: v for k, v in r.items() if k != "name"} for r in clean])
        return {**_product_payload(s, actor), "changed": changed}


@router.post("/products/{product_id}/delete")
def delete_product(product_id: int, actor: sv.Actor = Depends(get_actor)):
    """Katalogdan kaldırır (çöp kutusu); mevcut REQ satırlarındaki ürün adı/bağlantı korunur."""
    with session_scope() as s:
        p = sv.delete_product(s, actor, product_id)
        return {**_product_payload(s, actor), "removed": {"name": p.name}}


@router.post("/products")
def add_product(body: dict, actor: sv.Actor = Depends(get_actor)):
    supplier_id = body.get("default_supplier_id")
    if supplier_id is not None and not isinstance(supplier_id, int): raise HTTPException(400, "Geçersiz tedarikçi.")
    with session_scope() as s:
        if supplier_id is not None and supplier_id not in {p.id for p in sv.list_partners(s, actor, suppliers=True)}:
            raise HTTPException(400, "Geçersiz tedarikçi.")  # servis bu alanı doğrulamaz; başka şirketin kaydı seçilemesin
        p = sv.add_product(s, actor, name=text(body, "name"), category=text(body, "category"), hs_code=text(body, "hs_code"),
                           spec=text(body, "spec"), last_cost=_cost(body.get("last_cost")), default_supplier_id=supplier_id)
        return {**_product_payload(s, actor), "added": {"name": p.name}}
