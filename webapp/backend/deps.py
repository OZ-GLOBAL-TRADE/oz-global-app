"""Ortak bağımlılıklar (main.py ve router modülleri kullanır; döngüsel içe aktarma olmasın diye ayrı dosyada)."""
from fastapi import HTTPException, Request

from jarvis import services as sv
from jarvis.db import session_scope
from jarvis.models import User


def get_actor(request: Request) -> sv.Actor:
    """Oturum çerezindeki kullanıcıyı gerçek `Actor`'a çevirir; oturum yoksa/geçersizse 401. Yetki kontrolleri hep services.py'de kalır."""
    user_id = request.session.get("user_id")
    if not user_id: raise HTTPException(401, "Giriş yapılmamış.")
    with session_scope() as s:
        user = s.get(User, user_id)
        if not user or not user.active:
            request.session.clear()
            raise HTTPException(401, "Oturum geçersiz.")
        return sv.to_actor(user)


def text(body: dict, key: str) -> str:
    """İstek gövdesinden kırpılmış metin; yoksa/metin değilse boş."""
    v = body.get(key)
    return v.strip() if isinstance(v, str) else ""


def rows(body: dict, key: str) -> list[dict]:
    """İstek gövdesinden nesne listesi; değilse 400."""
    v = body.get(key)
    if not isinstance(v, list) or not all(isinstance(r, dict) for r in v): raise HTTPException(400, f"'{key}' listesi geçersiz.")
    return v
