"""Canlı döviz kuru: Avrupa Merkez Bankası verisi (frankfurter.app, ücretsiz, anahtar gerekmez), USD baz
alınarak EUR/TRY çevrimi için. 1 saat önbelleğe alınır (her Panel render'ında ağa gitmesin diye). Kur
çekilemezse (ağ yok, servis kapalı) eski değeri (varsa) ya da None döner — çağıran taraf çökmemeli, yalnızca
"kur alınamadı" uyarısı göstermeli."""
import time

import requests

_TTL_SECONDS = 3600
_cache: dict = {"rates": None, "fetched_at": 0.0}


def get_rates(base: str = "USD") -> dict[str, float] | None:
    """{'USD': 1.0, 'EUR': 0.92, 'TRY': 34.1, ...} — 1 birim `base` kaç birim hedef para eder."""
    now = time.time()
    if _cache["rates"] and now - _cache["fetched_at"] < _TTL_SECONDS:
        return _cache["rates"]
    others = ",".join(c for c in ("EUR", "TRY", "USD") if c != base)
    try:
        resp = requests.get(f"https://api.frankfurter.app/latest?from={base}&to={others}", timeout=5)
        resp.raise_for_status()
        rates = {base: 1.0, **resp.json().get("rates", {})}
        _cache["rates"], _cache["fetched_at"] = rates, now
        return rates
    except Exception:
        return _cache["rates"]  # eski (varsa) değeri döndür, yoksa None


def to_usd(amount: float, currency: str, rates: dict[str, float]) -> float | None:
    """rates, get_rates("USD") ile gelmiş olmalı. Kur eksikse None döner (toplamlara dahil edilmemeli)."""
    if currency == "USD": return amount
    rate = rates.get(currency)
    return amount / rate if rate else None


def convert(amount: float, from_cur: str, to_cur: str, rates: dict[str, float]) -> float | None:
    """rates = get_rates("USD") (1 USD kaç birim). Herhangi iki para birimi arasında USD üzerinden çevirir."""
    if from_cur == to_cur: return amount
    usd, target = to_usd(amount, from_cur, rates), rates.get(to_cur)
    return usd * target if usd is not None and target else None
