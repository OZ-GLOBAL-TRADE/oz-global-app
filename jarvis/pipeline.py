"""Golden Thread iş kuralları: aşamalar, yetkiler, geçiş kapıları ve teklif hesabı.
Bu modül veritabanına ve Streamlit'e bağlı değildir; yalnızca ORM nesneleri veya benzeri alanlara bakar."""
import re
from dataclasses import dataclass

ADMIN, TRADE_MANAGER, CUSTOMS_BROKER = "ADMIN", "TRADE_MANAGER", "CUSTOMS_BROKER"
ROLE_LABELS = {ADMIN: "Yönetici (Admin)", TRADE_MANAGER: "Ürün Yöneticisi", CUSTOMS_BROKER: "Gümrük"}
MANAGE_ROLES = (ADMIN, TRADE_MANAGER)
ALL_ROLES = (ADMIN, TRADE_MANAGER, CUSTOMS_BROKER)

ACTIVE, DONE, SHELVED = "aktif", "tamamlandi", "rafa"
STATUS_LABELS = {ACTIVE: "Aktif", DONE: "Tamamlandı", SHELVED: "Rafa Kaldırıldı"}
CURRENCIES = ["USD", "EUR", "TRY"]

# Kişiler / Ürünler sayfalarındaki seçenek listeleri (Streamlit ve yeni web arayüzü aynı listeyi kullanır)
CUSTOMER_KINDS = ["Savunma", "Sivil", "Ticari", "Kurumsal"]
SUPPLIER_CATEGORIES = ["Savunma", "Elektronik", "İtki & Güç", "Mekanik", "Diğer"]
PRODUCT_CATEGORIES = ["Savunma", "Elektronik", "İtki", "Mekanik", "Diğer"]

MARGIN_WARN_PCT = 60.0  # varsayılan kâr marjı bunun üstündeyse arayüz "alışılmadık derecede yüksek" uyarısı gösterir

# "Önceki aşamaya dön" / "Rafa kaldır" / ret için sık kullanılan sebepler; "Diğer" seçilince serbest metin istenir.
MOVE_BACK_REASONS = ["Tedarikçi fiyatı değiştirdi", "Müşteri talebi değişti", "Hesaplama/veri hatası", "Eksik bilgi girilmiş", "Diğer"]
SHELVE_REASONS = ["Müşteri vazgeçti", "Bütçe yok", "Rakip fiyat verdi", "Süre doldu / yanıt yok", "Diğer"]


@dataclass(frozen=True)
class Stage:
    key: str
    label: str
    view_roles: tuple
    edit_roles: tuple
    waiting: str  # kartlarda "kimde" bilgisi


STAGES = (
    Stage("talep", "1. Talep", ALL_ROLES, MANAGE_ROLES, "Yönetici"),
    Stage("fiyat", "2. Fiyat Araştırması", ALL_ROLES, MANAGE_ROLES, "Yönetici / Çin ofisi"),
    Stage("gumruk", "3. Gümrük & Lojistik", ALL_ROLES, ALL_ROLES, "Gümrük"),
    Stage("teklif", "4. Teklif", MANAGE_ROLES, MANAGE_ROLES, "Yönetici"),
    Stage("karar", "5. Müşteri Kararı", MANAGE_ROLES, MANAGE_ROLES, "Müşteri"),
    Stage("siparis", "6. Sipariş", MANAGE_ROLES, MANAGE_ROLES, "Yönetici"),
    Stage("lojistik", "7. Lojistik & Gümrük", ALL_ROLES, ALL_ROLES, "Lojistik / Gümrük"),
    Stage("teslim", "8. Teslim & Stok", MANAGE_ROLES, MANAGE_ROLES, "Yönetici"),
)
STAGE_KEYS = [s.key for s in STAGES]
STAGE_BY_KEY = {s.key: s for s in STAGES}

# Gümrükçü, REQ'yi yalnızca kendi aşamalarındayken görür.
BROKER_STAGES = ("gumruk", "lojistik")


def stage_index(key: str) -> int:
    return STAGE_KEYS.index(key)


def next_stage(key: str):
    i = stage_index(key)
    return STAGE_KEYS[i + 1] if i + 1 < len(STAGE_KEYS) else None


def prev_stage(key: str):
    i = stage_index(key)
    return STAGE_KEYS[i - 1] if i > 0 else None


def can_view_stage(role: str, key: str) -> bool:
    return role in STAGE_BY_KEY[key].view_roles


def can_edit_stage(role: str, key: str) -> bool:
    return role in STAGE_BY_KEY[key].edit_roles


def visible_stages(role: str) -> list[str]:
    return [s.key for s in STAGES if role in s.view_roles]


def can_view_req(user_id: int, role: str, req) -> bool:
    """GEÇİCİ (kullanıcı yetkilendirme modülüne kadar): TRADE_MANAGER artık ADMIN gibi TÜM REQ'leri görür/düzenler
    (sahiplik kısıtı yok) — kullanıcıların birbirinin REQ'ine görev atayabilmesi için kullanıcının kendi isteği.
    Gerçek per-kullanıcı/aşama yetkilendirme modülü eklenince bu tekrar ele alınacak (bkz. CLAUDE.md)."""
    if role in (ADMIN, TRADE_MANAGER): return True
    if role == CUSTOMS_BROKER: return req.status == ACTIVE and req.stage in BROKER_STAGES
    return False


# ---------------------------------------------------------------- teklif hesabı

DELIVERY_TYPES = ["Gümrük Teslim", "Kapı Teslim", "Fabrika Teslim (EXW)"]
COST_KINDS = {"gumruk": "Gümrük", "lojistik": "Lojistik", "diger": "Diğer"}
LOGISTICS_MODES = {"dahil": "Ürün fiyatlarına dahil", "ayri": "Ayrı kalem"}


@dataclass
class Quote:
    rows: list
    cost_products: float
    cost_customs: float     # ürün bazlı gümrük + ekstra gümrük masrafları
    cost_logistics: float   # ürün bazlı lojistik + ekstra lojistik masrafları
    cost_other: float
    cost_total: float
    total: float            # KDV hariç teklif tutarı (müşterinin gördüğü satırların toplamı)
    profit: float
    tax: float
    grand_total: float


def calculate_quote(lines, extra_costs, margin_pct, tax_pct, logistics_mode: str = "dahil", logistics_margin_pct=None) -> Quote:
    """Maliyet = ürün alış + gümrük + lojistik + ekstra masraflar; teklif = maliyet x (1 + marj) (marj maliyet üzerinden, Odoo'daki gibi).

    Marj kaynağı satır bazlıdır:
      - Her satırın kendi `margin_pct`'i varsa o kullanılır; yoksa REQ'nin `margin_pct` (varsayılan) marjı kullanılır.
      - Bir satırda `sale_price_override` (doğrudan birim satış fiyatı) varsa, o satırın fiyatı marjdan bağımsız olarak
        doğrudan bu değerdir; maliyet/kâr yine hesaplanır (iç raporlama için) ama fiyatı etkilemez.
      - Lojistik "ayrı kalem" (ayri) modunda kendi satırı olur ve `logistics_margin_pct` (boşsa REQ'nin varsayılan marjı)
        ile fiyatlanır — ürün marjlarından bağımsızdır.

    Sunum (yalnızca görünüm, toplam aynıdır):
      dahil: lojistik ve tüm ekstra masraflar ürün birim maliyetlerine dağıtılır, her satır kendi marjıyla fiyatlanır.
      ayri : lojistik (ürün bazlı + ekstra lojistik) ayrı bir satır olur; ürün maliyetleri lojistiksiz kalır.
    Ekstra masraflar (satırlara bağlı olmayanlar) satırlara maliyet oranında dağıtılır. Birim fiyatlar 2 haneye yuvarlanır.
    extra_costs: .kind ('gumruk' | 'lojistik' | 'diger') ve .amount alanları olan nesneler."""
    default_margin = (margin_pct or 0.0) / 100.0
    lines, separate = list(lines), logistics_mode == "ayri"
    extras = {"gumruk": 0.0, "lojistik": 0.0, "diger": 0.0}
    for c in extra_costs: extras[c.kind if c.kind in extras else "diger"] += float(c.amount or 0.0)

    parts = [((l.qty or 0) * (l.unit_cost or 0.0), (l.qty or 0) * (l.unit_customs or 0.0),
              (l.qty or 0) * (getattr(l, "unit_logistics", None) or 0.0)) for l in lines]
    bases = [prod + customs + (0.0 if separate else logi) for prod, customs, logi in parts]  # ürün maliyetine giren kalem
    base_sum, total_qty = sum(bases), sum((l.qty or 0) for l in lines)
    shared_extra = extras["gumruk"] + extras["diger"] + (0.0 if separate else extras["lojistik"])

    rows = []
    for l, (prod, customs, logi), base in zip(lines, parts, bases):
        qty = l.qty or 0
        if base_sum: share = shared_extra * base / base_sum
        elif total_qty: share = shared_extra * qty / total_qty
        else: share = 0.0
        cost = base + share
        override = getattr(l, "sale_price_override", None)
        line_margin = getattr(l, "margin_pct", None)
        if override is not None:
            unit_price, margin_used = round(override, 2), None
        else:
            margin = (line_margin if line_margin is not None else margin_pct or 0.0) / 100.0
            unit_price = round(cost * (1 + margin) / qty, 2) if qty else 0.0
            margin_used = line_margin if line_margin is not None else margin_pct
        rows.append({"kind": "urun", "name": l.name, "qty": qty, "cost": round(cost, 2), "unit_price": unit_price,
                     "line_total": round(unit_price * qty, 2), "margin_pct": margin_used, "override": override is not None})
    if separate:
        logistics_cost = sum(logi for _, _, logi in parts) + extras["lojistik"]
        if logistics_cost > 0:
            logi_margin = (logistics_margin_pct if logistics_margin_pct is not None else default_margin * 100) / 100.0
            price = round(logistics_cost * (1 + logi_margin), 2)
            rows.append({"kind": "lojistik", "name": "Lojistik & Nakliye", "qty": 1, "cost": round(logistics_cost, 2),
                         "unit_price": price, "line_total": price,
                         "margin_pct": logistics_margin_pct if logistics_margin_pct is not None else margin_pct, "override": False})

    cost_products = sum(p for p, _, _ in parts)
    cost_customs = sum(c for _, c, _ in parts) + extras["gumruk"]
    cost_logistics = sum(g for _, _, g in parts) + extras["lojistik"]
    cost_total = round(cost_products + cost_customs + cost_logistics + extras["diger"], 2)
    total = round(sum(r["line_total"] for r in rows), 2)
    tax = round(total * (tax_pct or 0.0) / 100.0, 2)
    return Quote(rows, round(cost_products, 2), round(cost_customs, 2), round(cost_logistics, 2), round(extras["diger"], 2),
                 cost_total, total, round(total - cost_total, 2), tax, round(total + tax, 2))


def delivery_hint(delivery_type: str, customs_total: float) -> str | None:
    """Teslimat tipi kuralı: kapı teslimde gümrük masrafı teklife eklenir, gümrük teslimde eklenmez. Yalnızca uyarır; engellemez."""
    if delivery_type == "Gümrük Teslim" and customs_total > 0:
        return "Gümrük teslimde gümrük masrafı genellikle teklife eklenmez; girilen gümrük tutarı teklife dahil ediliyor. Kontrol edin."
    if delivery_type == "Kapı Teslim" and customs_total <= 0:
        return "Kapı teslimde gümrük masrafı teklife eklenir; gümrük tutarı 0 görünüyor. Kontrol edin."
    return None


def quote_for_req(req) -> Quote:
    return calculate_quote(req.lines, req.costs, req.margin_pct, req.tax_pct if req.tax_enabled else 0.0,
                           req.logistics_mode, req.logistics_margin_pct)


# ---------------------------------------------------------------- geçiş kapıları

def check_gate(stage_key: str, req) -> list[str]:
    """Bir aşamadan çıkmak için gereken minimum veri. Boş liste = geçilebilir."""
    errors, lines = [], list(req.lines)
    if stage_key == "talep":
        if not req.customer_id: errors.append("Müşteri seçilmeli.")
        if not lines: errors.append("En az bir ürün eklenmeli.")
        elif any((l.qty or 0) <= 0 for l in lines): errors.append("Tüm ürünlerin adedi 0'dan büyük olmalı.")
    elif stage_key == "fiyat":
        missing = [l.name for l in lines if not l.unit_cost or l.unit_cost <= 0]
        if missing: errors.append("Birim alış fiyatı girilmemiş: " + ", ".join(missing))
    elif stage_key == "gumruk":
        missing = [l.name for l in lines if l.unit_customs is None]
        if missing: errors.append("Birim gümrük girilmemiş (yoksa 0 yazın): " + ", ".join(missing))
    elif stage_key == "teklif":
        if req.margin_pct is None: errors.append("Kâr marjı girilmeli.")
        elif quote_for_req(req).total <= 0: errors.append("Teklif tutarı 0; fiyatları ve marjı kontrol edin.")
        if not req.quote_sent_at: errors.append("Teklifin müşteriye iletildiği işaretlenmeli.")
    elif stage_key == "karar":
        if req.decision != "onay": errors.append("Müşteri onayı işaretlenmeli (ret ise REQ rafa kaldırılır).")
    elif stage_key == "siparis":
        if not req.po_approved_at: errors.append("Çin ofisine satın alma onayının verildiği işaretlenmeli.")
    elif stage_key == "teslim":
        missing = [l.name for l in req.lines if delivered_qty(req, l.id) < (l.qty or 0) - 1e-9]
        if missing: errors.append("Henüz tam teslim edilmemiş ürünler var (teslimat makbuzu oluşturun): " + ", ".join(missing))
    return errors


def delivered_qty(req, req_line_id: int) -> float:
    """Bu REQ satırından, şimdiye kadarki tüm teslimat makbuzlarıyla teslim edilmiş toplam adet."""
    return sum(l.qty for d in req.deliveries for l in d.lines if l.req_line_id == req_line_id)


# Geri dönüldüğünde, o aşamadan sonraki onaylar geçersiz sayılır.
CLEAR_ON_ARRIVE = {
    "talep": ("quote_sent_at", "decision", "po_approved_at", "po_number"),
    "fiyat": ("quote_sent_at", "decision", "po_approved_at", "po_number"),
    "gumruk": ("quote_sent_at", "decision", "po_approved_at", "po_number"),
    "teklif": ("quote_sent_at", "decision", "po_approved_at", "po_number"),
    "karar": ("decision", "po_approved_at", "po_number"),
    "siparis": ("po_approved_at", "po_number"),
}


# ---------------------------------------------------------------- kargo (CRG)

LOGISTICS_STATUSES = ["Çıkış Hazırlığında", "Uçuşta / Yolda", "Gümrük Bölgesinde", "Dağıtımda", "Teslim Edildi"]
CUSTOMS_STATUSES = ["Bekliyor", "Evrak Kontrolde", "Muayenede", "Vergi Onay Bekliyor", "Gümrükten Çekildi"]
CARRIERS = ["Otomatik Algıla", "Turkish Cargo", "DHL Express", "FedEx", "UPS", "Özel Hat"]
ATTACHMENT_KINDS = {"awb": "AWB", "packing_list": "Packing List (PL)", "proforma_invoice": "Proforma Invoice (PI)", "diger": "Diğer"}
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024  # 10 MB
DEFAULT_DELIVERY_ADDRESS = "Ankara Merkez Ofis"  # yeni kargoda değiştirilmediği sürece kalır

# Taşıyıcının kendi takip sayfası; {awb} yer tutucusu varsa AWB otomatik doldurulur, yoksa genel sayfa açılır.
TRACKING_URL_TEMPLATES = {
    "DHL Express": "https://www.dhl.com/tr-en/home/tracking.html?submit=1&tracking-id={awb}",
    "Turkish Cargo": "https://www.turkishcargo.com/en/cargo-tracking",
    "FedEx": "https://www.fedex.com/fedextrack/?trknbr={awb}",
    "UPS": "https://www.ups.com/track?loc=en_US&tracknum={awb}",
}
# Yalnızca DHL için resmi genel API üzerinden otomatik konum çekilir (bkz. services.refresh_dhl_tracking).
# Turkish Cargo'nun belgelenmiş bir genel API'si yok; sitesi ağır bir JS uygulaması olduğu için kazıma (scraping)
# kırılgan/güvenilmez olur ve bilinçli olarak uygulanmadı — bunun yerine takip sayfasına bağlantı verilir.
AUTO_TRACKING_CARRIERS = ("DHL Express",)


def detect_carrier(awb_no: str) -> str:
    """AWB numarasının biçimine bakarak taşıyıcı tahmini (eski kargo modülünden aktarıldı)."""
    awb = re.sub(r"[\s-]", "", str(awb_no or ""))
    if not awb: return "Bilinmiyor"
    if (awb.startswith("235") and len(awb) == 11) or "TK" in str(awb_no).upper(): return "Turkish Cargo"
    if len(awb) == 10 and awb.isdigit(): return "DHL Express"
    if len(awb) in (12, 15) and awb.isdigit(): return "FedEx"
    if awb.upper().startswith("1Z"): return "UPS"
    return "Global Kargo / Hat"


def tracking_url(carrier: str, awb_no: str) -> str | None:
    """Taşıyıcının kendi takip sayfası; AWB varsa doldurulmuş, yoksa genel arama sayfası. Bilinmeyen taşıyıcıda None."""
    template = TRACKING_URL_TEMPLATES.get(carrier)
    if not template: return None
    return template.format(awb=re.sub(r"[\s-]", "", str(awb_no or ""))) if "{awb}" in template else template


def carrier_needs_manual_awb(carrier: str) -> bool:
    """True ise taşıyıcının takip sayfası AWB'yi otomatik doldurmuyor; kullanıcı AWB'yi kopyalayıp kendi yapıştırmalı."""
    template = TRACKING_URL_TEMPLATES.get(carrier)
    return bool(template) and "{awb}" not in template
