"""Çöp kutusu (Silinenler): silinen REQ / müşteri / tedarikçi / ürünleri listeler, geri yükler, kalıcı siler. İş kuralları ve yetki
jarvis.services'te (delete_*, restore_*, purge_*): geri yükleme yönetici rollerinde; KALICI silme yalnızca ADMIN'de ve adı/kodu
yazarak onayla. Buradaki uç noktalar yalnızca HTTP/JSON."""
from fastapi import APIRouter, Depends, HTTPException

from deps import get_actor, text
from jarvis import pipeline as pl, services as sv
from jarvis.db import session_scope
from jarvis.models import Req

router = APIRouter(prefix="/api/trash")
KINDS = ("reqs", "customers", "suppliers", "products")


def _kind(value: str) -> str:
    if value not in KINDS: raise HTTPException(404, "Geçersiz tür.")
    return value


def _users(s) -> dict[int, str]:
    return {u.id: u.name for u in sv.list_users(s)}


def _payload(s, actor, kind: str) -> dict:
    names = _users(s)
    who = lambda rec: names.get(rec.deleted_by) if rec.deleted_by else None
    when = lambda rec: rec.deleted_at.isoformat() if rec.deleted_at else None
    items: list[dict] = []
    if kind == "reqs":
        for r in sv.list_deleted_reqs(s, actor):
            stage = pl.STAGE_BY_KEY[r.stage].label if r.status == pl.ACTIVE else pl.STATUS_LABELS[r.status]
            items.append({"ident": r.code, "title": r.code, "subtitle": f"{r.customer.name} · {stage} · {len(r.lines)} kalem",
                          "deleted_at": when(r), "deleted_by": who(r), "blocked": None})
    elif kind in ("customers", "suppliers"):
        partners = sv.list_partners(s, actor, customers=kind == "customers", suppliers=kind == "suppliers", deleted=True)
        # Müşteriye bağlı REQ varsa (silinmiş olanlar dahil) kalıcı silinemez: nedenini önceden göster
        counts = {}
        if kind == "customers":
            from sqlalchemy import func, select
            counts = dict(s.execute(select(Req.customer_id, func.count(Req.id)).where(Req.company_id == actor.company_id).group_by(Req.customer_id)).all())
        for p in partners:
            detail = (f"Kod: {p.short_code}" if kind == "customers" else p.category or "-")
            n = counts.get(p.id, 0)
            items.append({"ident": str(p.id), "title": p.name, "subtitle": detail, "deleted_at": when(p), "deleted_by": who(p),
                          "blocked": f"{n} REQ bağlı (silinmiş olanlar dahil); REQ'ler kalıcı silinmeden kalıcı silinemez." if n else None})
    else:
        for p in sv.list_products(s, actor, deleted=True):
            items.append({"ident": str(p.id), "title": p.name, "subtitle": f"{p.category or '-'} · GTİP {p.hs_code or '-'}",
                          "deleted_at": when(p), "deleted_by": who(p), "blocked": None})
    return {"items": items, "can_purge": actor.role == pl.ADMIN}


@router.get("/{kind}")
def list_trash(kind: str, actor: sv.Actor = Depends(get_actor)):
    kind = _kind(kind)
    with session_scope() as s:
        return _payload(s, actor, kind)


def _int(ident: str) -> int:
    if not ident.isdigit(): raise HTTPException(404, "Kayıt bulunamadı.")
    return int(ident)


@router.post("/{kind}/{ident}/restore")
def restore(kind: str, ident: str, actor: sv.Actor = Depends(get_actor)):
    kind = _kind(kind)
    with session_scope() as s:
        if kind == "reqs": sv.restore_req(s, actor, _deleted_req(s, actor, ident))
        elif kind == "products": sv.restore_product(s, actor, _int(ident))
        else: sv.restore_partner(s, actor, _int(ident))
        return _payload(s, actor, kind)


@router.post("/{kind}/{ident}/purge")
def purge(kind: str, ident: str, body: dict, actor: sv.Actor = Depends(get_actor)):
    """Geri dönüşsüz. `confirm`: REQ için REQ kodu, diğerleri için kaydın adı (servis aynen eşleşmeyi zorlar)."""
    kind = _kind(kind)
    confirm = text(body, "confirm")
    with session_scope() as s:
        if kind == "reqs": sv.purge_req(s, actor, _deleted_req(s, actor, ident), confirm)
        elif kind == "products": sv.purge_product(s, actor, _int(ident), confirm)
        else: sv.purge_partner(s, actor, _int(ident), confirm)
        return _payload(s, actor, kind)


def _deleted_req(s, actor, code: str):
    try:
        return sv.get_req(s, actor, code=code, include_deleted=True)
    except sv.ServiceError as e:
        raise HTTPException(404, str(e))
