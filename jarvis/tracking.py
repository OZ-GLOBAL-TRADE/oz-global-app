"""DHL resmi genel takip API'si (https://developer.dhl.com/api-reference/shipment-tracking-unified).
Uçtan uca doğrulanamadı: kendi DHL geliştirici anahtarımız yok; alan adları API belgelerine göre yazıldı, gerçek bir
anahtarla ilk denemede küçük bir alan uyuşmazlığı çıkarsa `_parse_event` fonksiyonunu güncellemek yeterli olur.
Turkish Cargo için belgelenmiş bir genel API yok; sitesi ağır bir JS uygulaması olduğundan kazıma (scraping) bilinçli
olarak yapılmadı (kırılgan/güvenilmez) — onun için yalnızca takip sayfasına bağlantı verilir (bkz. pipeline.tracking_url)."""
from datetime import datetime, timezone

import requests

DHL_ENDPOINT = "https://api-eu.dhl.com/track/shipments"


class TrackingError(Exception):
    pass


def _parse_event(shipment: dict) -> dict:
    status = shipment.get("status") or {}
    location = (status.get("location") or {}).get("address") or {}
    place = ", ".join(x for x in (location.get("addressLocality"), location.get("countryCode")) if x)
    when = status.get("timestamp")
    try:
        when_dt = datetime.fromisoformat(when.replace("Z", "+00:00")) if when else None
    except ValueError:
        when_dt = None
    return {"location": place or "-", "description": status.get("description") or status.get("statusCode") or "-", "timestamp": when_dt}


def fetch_dhl_status(awb_no: str, api_key: str) -> dict:
    """Başarıda {"location", "description", "timestamp"} döner. Anahtar/AWB hatalıysa veya DHL bu gönderiyi
    tanımıyorsa (taşıyıcı DHL değilse ya da numara yanlışsa) TrackingError fırlatır."""
    awb = (awb_no or "").strip()
    if not awb: raise TrackingError("AWB numarası girilmemiş.")
    try:
        resp = requests.get(DHL_ENDPOINT, params={"trackingNumber": awb}, headers={"DHL-API-Key": api_key}, timeout=10)
    except requests.RequestException as e:
        raise TrackingError(f"DHL'e bağlanılamadı: {e}") from e
    if resp.status_code == 404: raise TrackingError("DHL bu AWB numarasını bulamadı.")
    if resp.status_code == 401: raise TrackingError("DHL API anahtarı geçersiz.")
    if not resp.ok: raise TrackingError(f"DHL API hatası ({resp.status_code}).")
    try:
        shipments = resp.json().get("shipments") or []
    except ValueError as e:
        raise TrackingError("DHL yanıtı okunamadı.") from e
    if not shipments: raise TrackingError("DHL bu AWB için kayıt döndürmedi.")
    return _parse_event(shipments[0])


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
