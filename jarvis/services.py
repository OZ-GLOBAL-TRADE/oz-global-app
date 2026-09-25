"""Uygulama servisleri: tüm okuma/yazma ve yetki kontrolleri burada; arayüz doğrudan modele dokunmaz.
Yazan fonksiyonlar kendi commit'lerini yapar. İş kuralı ihlali ServiceError ile bildirilir."""
import functools
import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import bcrypt
from sqlalchemy import func, select, update
from sqlalchemy.orm import defer, joinedload, selectinload

from jarvis import ai, config, pipeline as pl, tracking
from jarvis.models import (Attachment, Company, DeliveryDoc, DeliveryLine, Event, Partner, Product, QuoteDoc, Req,
                           ReqCost, ReqLine, Shipment, ShipmentItem, User)


class ServiceError(Exception):
    def __init__(self, message: str, errors: list[str] | None = None):
        super().__init__(message)
        self.errors = errors or [message]


@dataclass(frozen=True)
class Actor:
    id: int
    username: str
    name: str
    role: str
    company_id: int


def _atomic(fn):
    """Yazma fonksiyonu hata verirse yarım kalan değişiklikleri geri alır (oturum sonradan commit edilse bile sızmaz)."""
    @functools.wraps(fn)
    def wrapper(s, *args, **kwargs):
        try:
            return fn(s, *args, **kwargs)
        except Exception:
            s.rollback()
            raise
    return wrapper


def _now() -> datetime:
    return datetime.now(timezone.utc)


_TR_TZ = timezone(timedelta(hours=3))


def _num(v):
    """Pandas/data_editor değerlerini (NaN, None, numpy) sade float'a çevirir; boşsa None."""
    if v is None: return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def _text(v) -> str:
    return "" if v is None or (isinstance(v, float) and v != v) else str(v).strip()


def _require_role(actor: Actor, roles, what: str):
    if actor.role not in roles: raise ServiceError(f"{what} için yetkiniz yok.")


# ---------------------------------------------------------------- şirket & kullanıcılar

def ensure_company(s) -> Company:
    company = s.scalar(select(Company).where(Company.code == config.COMPANY_CODE))
    if not company:
        company = Company(code=config.COMPANY_CODE, name=config.COMPANY_NAME)
        s.add(company)
    if not company.legal_name: company.legal_name = config.COMPANY_LEGAL_NAME
    s.commit()
    return company


_COMPANY_TEXT = ("legal_name", "address", "tax_info", "phone", "email", "website", "bank_info")
_COMPANY_SEQS = {"quote_seq": (QuoteDoc, "Teklif"), "po_seq": (Req, "PO"), "shipment_seq": (Shipment, "Kargo"),
                "delivery_seq": (DeliveryDoc, "Teslimat")}


@_atomic
def update_company(s, actor: Actor, **fields) -> Company:
    """Teklif/PO/kargo başlığı ve numaralandırma ayarları (yalnızca ADMIN). *_seq alanları "son kullanılan sıra no"dur."""
    _require_role(actor, (pl.ADMIN,), "Şirket bilgilerini değiştirme")
    company = s.get(Company, actor.company_id)
    for key, value in fields.items():
        if key in _COMPANY_TEXT:
            setattr(company, key, _text(value))
        elif key in ("quote_prefix", "po_prefix", "shipment_prefix", "delivery_prefix"):
            prefix = re.sub(r"[^A-Za-z0-9]", "", _text(value)).upper()
            if not prefix: raise ServiceError("Önek boş olamaz.")
            setattr(company, key, prefix[:10])
        elif key in _COMPANY_SEQS:
            model, label = _COMPANY_SEQS[key]
            seq = int(value or 0)
            if seq < 0: raise ServiceError("Sıra numarası negatif olamaz.")
            current = getattr(company, key)
            has_existing = s.scalar(select(model.id).where(model.company_id == company.id).limit(1)) if model is not Req \
                else s.scalar(select(Req.id).where(Req.company_id == company.id, Req.po_number.is_not(None)).limit(1))
            if seq < current and has_existing:
                raise ServiceError(f"{label} numarası geriye alınamaz (şu an {current}); çakışma olmaması için yalnızca artırılabilir.")
            setattr(company, key, seq)
        else:
            raise ServiceError(f"Bilinmeyen ayar: {key}")
    s.commit()
    return company


def get_company(s, actor: Actor) -> Company:
    return s.get(Company, actor.company_id)


def ensure_user(s, company: Company, username: str, name: str, role: str) -> User:
    user = s.scalar(select(User).where(User.username == username))
    if not user:
        user = User(company_id=company.id, username=username, name=name, role=role)
        s.add(user)
        s.commit()
    return user


def list_users(s) -> list[User]:
    return list(s.scalars(select(User).where(User.active.is_(True)).order_by(User.id)))


def to_actor(user: User) -> Actor:
    return Actor(user.id, user.username, user.name, user.role, user.company_id)


_LOGIN_ATTEMPTS: dict[str, list[float]] = {}  # kullanıcı adı -> son hatalı deneme zaman damgaları (süreç ömrü boyunca)
_LOGIN_MAX_ATTEMPTS = 5
_LOGIN_LOCKOUT_SECONDS = 300  # 5 dakika


def authenticate(s, username: str, password: str) -> Actor:
    """Giriş formu için: kullanıcı adı + şifre doğrular. Kullanıcı adının var olup olmadığını sızdırmamak
    için hatalı kullanıcı adı ve hatalı şifre AYNI mesajı döndürür. Kaba kuvvet (brute-force) denemesine karşı
    kullanıcı adı başına basit bir kilitleme uygular (süreç bazlı; uygulama yeniden başlarsa sıfırlanır — tek
    süreçli Streamlit dağıtımı için yeterli bir ilk savunma katmanı, IP bazlı/dağıtık deneme koruması değildir)."""
    username = (username or "").strip()
    now = time.time()
    recent = [t for t in _LOGIN_ATTEMPTS.get(username, []) if now - t < _LOGIN_LOCKOUT_SECONDS]
    if len(recent) >= _LOGIN_MAX_ATTEMPTS:
        raise ServiceError(f"Çok fazla hatalı giriş denemesi. Lütfen {_LOGIN_LOCKOUT_SECONDS // 60} dakika sonra tekrar deneyin.")

    user = s.scalar(select(User).where(User.username == username, User.active.is_(True)))
    if not user or not user.password_hash or not bcrypt.checkpw((password or "").encode("utf-8"), user.password_hash.encode("utf-8")):
        recent.append(now)
        _LOGIN_ATTEMPTS[username] = recent
        raise ServiceError("Kullanıcı adı veya şifre hatalı.")
    _LOGIN_ATTEMPTS.pop(username, None)
    return to_actor(user)


def set_password(s, actor: Actor, user_id: int, new_password: str) -> None:
    """Yalnızca admin; hedef kullanıcı aynı şirkette olmalı."""
    _require_role(actor, (pl.ADMIN,), "Şifre belirleme")
    if len(new_password or "") < 8: raise ServiceError("Şifre en az 8 karakter olmalı.")
    user = s.get(User, user_id)
    if not user or user.company_id != actor.company_id: raise ServiceError("Kullanıcı bulunamadı.")
    user.password_hash = bcrypt.hashpw(new_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    s.commit()


# ---------------------------------------------------------------- kişiler (müşteri / tedarikçi)

PARTNER_TEXT_FIELDS = ("kind", "country", "tax_no", "address", "email", "phone", "category", "keywords", "notes")
_TR_ASCII = str.maketrans("İIıŞşĞğÜüÖöÇç", "IIISSGGUUOOCC")


def _name_owner(s, model, company_id: int, name: str, exclude_id: int | None = None):
    """Aynı adı taşıyan kaydı (silinmiş olsa da) döndürür; yoksa None. Türkçe harf ve büyük/küçük harf farkını yok sayar
    (SQL lower() İ/ı için güvenilmez). Silinen kayıtlar da adı ÜZERİNDE tutar: veritabanı benzersizlik kuralı hepsini kapsar."""
    key = " ".join(name.translate(_TR_ASCII).upper().split())
    for rec in s.scalars(select(model).where(model.company_id == company_id)):
        if rec.id != exclude_id and " ".join(rec.name.translate(_TR_ASCII).upper().split()) == key: return rec
    return None


def _name_taken(s, model, company_id: int, name: str) -> bool:
    return _name_owner(s, model, company_id, name) is not None


def _dup_error(owner, name: str, kind: str = "kayıtlı") -> ServiceError:
    if owner.deleted_at: return ServiceError(f"'{name}' silinenler arasında; yenisini eklemek yerine oradan geri yükleyin.")
    return ServiceError(f"'{name}' zaten {kind}.")


def suggest_short_code(name: str) -> str:
    """İlk harf + sonraki ünsüzler (en fazla 4 harf). Örn: Altınay -> ALTN."""
    letters = [c for c in name.translate(_TR_ASCII).upper() if "A" <= c <= "Z"]
    if not letters: return "REQ"
    code = letters[0] + "".join([c for c in letters[1:] if c not in "AEIOU"][:3])
    return code if len(code) >= 2 else "".join(letters[:4])


def _free_short_code(s, company_id: int, base: str) -> str:
    code, n = base, 1
    while s.scalar(select(Partner.id).where(Partner.company_id == company_id, Partner.short_code == code)):
        n += 1
        code = f"{base}{n}"
    return code


def list_partners(s, actor: Actor, *, customers: bool = False, suppliers: bool = False, deleted: bool = False) -> list[Partner]:
    """Silinenler (çöp kutusu) hiçbir zaman normal listede görünmez; `deleted=True` yalnızca silinenleri verir (yönetici roller)."""
    if deleted: _require_role(actor, pl.MANAGE_ROLES, "Silinenleri görme")
    q = select(Partner).where(Partner.company_id == actor.company_id,
                              Partner.deleted_at.is_not(None) if deleted else Partner.deleted_at.is_(None)).order_by(Partner.name)
    if customers: q = q.where(Partner.is_customer.is_(True))
    if suppliers: q = q.where(Partner.is_supplier.is_(True))
    return list(s.scalars(q))


@_atomic
def add_partner(s, actor: Actor, *, name: str, is_customer: bool = False, is_supplier: bool = False,
                short_code: str = "", req_seq: int = 0, is_demo: bool = False, **fields) -> Partner:
    _require_role(actor, pl.MANAGE_ROLES, "Kişi ekleme")
    name = " ".join((name or "").split())
    if not name: raise ServiceError("Ad boş olamaz.")
    if not (is_customer or is_supplier): raise ServiceError("Müşteri veya tedarikçi olarak işaretlenmeli.")
    if owner := _name_owner(s, Partner, actor.company_id, name):
        raise _dup_error(owner, name)

    code = None
    if is_customer:
        wanted = re.sub(r"[^A-Z0-9]", "", (short_code or "").upper())
        if wanted:
            if s.scalar(select(Partner.id).where(Partner.company_id == actor.company_id, Partner.short_code == wanted)):
                raise ServiceError(f"'{wanted}' kısa kodu başka bir müşteride kullanılıyor.")
            code = wanted
        else:
            code = _free_short_code(s, actor.company_id, suggest_short_code(name))

    partner = Partner(company_id=actor.company_id, name=name, short_code=code, is_customer=is_customer,
                      is_supplier=is_supplier, req_seq=max(int(req_seq or 0), 0), is_demo=is_demo,
                      **{k: _text(v) for k, v in fields.items() if k in PARTNER_TEXT_FIELDS})
    s.add(partner)
    s.commit()
    return partner


# ---------------------------------------------------------------- ürünler

def list_products(s, actor: Actor, *, deleted: bool = False) -> list[Product]:
    if deleted: _require_role(actor, pl.MANAGE_ROLES, "Silinenleri görme")
    return list(s.scalars(select(Product).where(Product.company_id == actor.company_id,
                                                Product.deleted_at.is_not(None) if deleted else Product.deleted_at.is_(None)).order_by(Product.name)))


@_atomic
def add_product(s, actor: Actor, *, name: str, category: str = "", spec: str = "", hs_code: str = "",
                default_supplier_id: int | None = None, last_cost: float | None = None, notes: str = "",
                is_demo: bool = False) -> Product:
    _require_role(actor, pl.MANAGE_ROLES, "Ürün ekleme")
    name = " ".join((name or "").split())
    if not name: raise ServiceError("Ürün adı boş olamaz.")
    if owner := _name_owner(s, Product, actor.company_id, name):
        raise _dup_error(owner, name, "kataloğda var")
    product = Product(company_id=actor.company_id, name=name, category=_text(category), spec=_text(spec),
                      hs_code=_text(hs_code), default_supplier_id=default_supplier_id or None,
                      last_cost=_num(last_cost) or None, notes=_text(notes), is_demo=is_demo)
    s.add(product)
    s.commit()
    return product


_EDITABLE = {Partner: PARTNER_TEXT_FIELDS, Product: ("category", "spec", "hs_code", "last_cost", "notes")}


@_atomic
def update_records(s, actor: Actor, model, rows: list[dict]) -> int:
    """Tablo üzerinden toplu düzenleme (ad ve kod alanları hariç). Gümrükçü yalnızca GTİP kodunu değiştirebilir."""
    fields = _EDITABLE[model]
    if model is Partner: _require_role(actor, pl.MANAGE_ROLES, "Kişi düzenleme")
    elif actor.role == pl.CUSTOMS_BROKER: fields = ("hs_code",)
    changed = 0
    for row in rows:
        obj = s.get(model, int(row["id"]))
        if obj is None or obj.company_id != actor.company_id: continue
        for f in fields:
            if f not in row: continue
            value = _num(row[f]) if f == "last_cost" else _text(row[f])
            if getattr(obj, f) != value:
                setattr(obj, f, value)
                changed += 1
    s.commit()
    return changed


# ---------------------------------------------------------------- REQ okuma

_REQ_OPTS = (joinedload(Req.customer), joinedload(Req.owner), selectinload(Req.lines), selectinload(Req.costs))


def visible_reqs(s, actor: Actor, status: str | None = None) -> list[Req]:
    """GEÇİCİ: TRADE_MANAGER artık ADMIN gibi tüm REQ'leri görür (bkz. pipeline.can_view_req)."""
    q = select(Req).options(*_REQ_OPTS).where(Req.company_id == actor.company_id, Req.deleted_at.is_(None))
    if actor.role == pl.CUSTOMS_BROKER: q = q.where(Req.status == pl.ACTIVE, Req.stage.in_(pl.BROKER_STAGES))
    elif actor.role not in (pl.ADMIN, pl.TRADE_MANAGER): return []
    if status: q = q.where(Req.status == status)
    return list(s.scalars(q.order_by(Req.updated_at.desc())).unique())


def get_req(s, actor: Actor, *, req_id: int | None = None, code: str | None = None, include_deleted: bool = False) -> Req:
    """Silinmiş REQ 'bulunamadı' sayılır; yalnızca çöp kutusu işlemleri `include_deleted=True` ile (yönetici roller) erişir."""
    q = select(Req).options(*_REQ_OPTS).where(Req.company_id == actor.company_id)
    if include_deleted: _require_role(actor, pl.MANAGE_ROLES, "Silinen REQ'lere erişim")
    else: q = q.where(Req.deleted_at.is_(None))
    q = q.where(Req.id == req_id) if req_id is not None else q.where(Req.code == code)
    req = s.scalars(q).unique().first()
    if not req or not pl.can_view_req(actor.id, actor.role, req): raise ServiceError("REQ bulunamadı veya yetkiniz yok.")
    return req


def list_events(s, req_id: int, actor: Actor | None = None) -> list[Event]:
    """actor verilirse, rolün göremediği aşamalarda yazılmış düzenleme/not kayıtları (örn. kâr marjı) gizlenir."""
    events = list(s.scalars(select(Event).options(joinedload(Event.user)).where(Event.req_id == req_id, Event.deleted_at.is_(None)).order_by(Event.id.desc())))
    if actor is None or actor.role == pl.ADMIN: return events
    visible = set(pl.visible_stages(actor.role))
    return [e for e in events if e.kind not in ("edit", "note") or e.stage is None or e.stage in visible]


def next_req_code(s, customer_id: int) -> str:
    customer = s.get(Partner, customer_id)
    return f"{customer.short_code}_REQ_{(customer.req_seq or 0) + 1:02d}"


# ---------------------------------------------------------------- REQ yazma

def _log(s, actor: Actor, req: Req, kind: str, message: str, from_stage=None, to_stage=None):
    s.add(Event(company_id=actor.company_id, req_id=req.id, user_id=actor.id, kind=kind, message=message,
                stage=req.stage, from_stage=from_stage, to_stage=to_stage))


def _guard_edit(actor: Actor, req: Req):
    if not pl.can_view_req(actor.id, actor.role, req): raise ServiceError("Bu REQ üzerinde yetkiniz yok.")
    if req.status != pl.ACTIVE: raise ServiceError("Bu REQ aktif değil.")
    if not pl.can_edit_stage(actor.role, req.stage):
        raise ServiceError(f"'{pl.STAGE_BY_KEY[req.stage].label}' aşamasını düzenleme yetkiniz yok.")


def _require_stage(req: Req, stage: str):
    if req.stage != stage:
        raise ServiceError(f"Bu işlem yalnızca '{pl.STAGE_BY_KEY[stage].label}' aşamasında yapılabilir. Önceki aşamaya dönerek düzeltebilirsiniz.")


@_atomic
def create_req(s, actor: Actor, *, customer_id: int, items: list[tuple[int, float]], currency: str = "USD",
               delivery_type: str = "Gümrük Teslim", notes: str = "", is_demo: bool = False) -> Req:
    _require_role(actor, pl.MANAGE_ROLES, "REQ açma")
    customer = s.get(Partner, customer_id)
    if not customer or not customer.is_customer or customer.company_id != actor.company_id or customer.deleted_at:
        raise ServiceError("Geçerli bir müşteri seçin.")
    if currency not in pl.CURRENCIES: raise ServiceError("Geçersiz para birimi.")
    if delivery_type not in pl.DELIVERY_TYPES: raise ServiceError("Geçersiz teslimat tipi.")
    items = [(pid, qty) for pid, qty in items if pid]
    if not items: raise ServiceError("En az bir ürün seçin.")

    # Sayaç veritabanında atomik artar: aynı anda iki REQ açılsa bile kod tekrar etmez.
    s.execute(update(Partner).where(Partner.id == customer_id).values(req_seq=Partner.req_seq + 1))
    seq = s.scalar(select(Partner.req_seq).where(Partner.id == customer_id))
    req = Req(company_id=actor.company_id, code=f"{customer.short_code}_REQ_{seq:02d}", customer_id=customer_id,
              owner_id=actor.id, currency=currency, delivery_type=delivery_type, notes=_text(notes), is_demo=is_demo)
    for pos, (pid, qty) in enumerate(items):
        product = s.get(Product, pid)
        if not product or product.company_id != actor.company_id or product.deleted_at: raise ServiceError("Geçersiz ürün seçimi.")
        if not qty or float(qty) <= 0: raise ServiceError(f"Adet 0'dan büyük olmalı: {product.name}")
        req.lines.append(ReqLine(product_id=product.id, name=product.name, qty=float(qty), position=pos))
    s.add(req)
    s.flush()
    _log(s, actor, req, "create", f"REQ açıldı ({len(items)} kalem, {currency}).", to_stage="talep")
    s.commit()
    return req


@_atomic
def save_items(s, actor: Actor, req: Req, rows: list[dict]):
    """rows: {id?, product_id, qty}. Yalnızca Talep aşamasında; eksik kalan satırlar silinir."""
    _guard_edit(actor, req)
    _require_stage(req, "talep")
    by_id = {l.id: l for l in req.lines}
    # Yeni seçilebilecek ürünler yalnızca silinmemiş olanlardır; ama bu REQ'in mevcut satırlarındaki ürünler (sonradan katalogdan
    # silinmiş olsa da) tanınır — yoksa Talep kaydedilirken o satırlar sessizce düşerdi.
    keep_ids = {l.product_id for l in req.lines if l.product_id}
    products = {p.id: p for p in s.scalars(select(Product).where(Product.company_id == actor.company_id))
                if p.deleted_at is None or p.id in keep_ids}
    seen, pos = set(), 0
    for r in rows:
        pid = _num(r.get("product_id"))
        rid = _num(r.get("id"))
        line = by_id.get(int(rid)) if rid is not None else None
        if pid is None and line and not line.product_id:
            # Ürünü katalogdan kalıcı silinmiş mevcut satır: satır adıyla kalır, yalnızca adet güncellenebilir
            qty = _num(r.get("qty")) or 0
            if qty <= 0: raise ServiceError(f"Adet 0'dan büyük olmalı: {line.name}")
            line.qty, line.position = qty, pos
            seen.add(line.id)
            pos += 1
            continue
        if pid is None or int(pid) not in products: continue
        pid, qty = int(pid), _num(r.get("qty")) or 0
        if qty <= 0: raise ServiceError(f"Adet 0'dan büyük olmalı: {products[pid].name}")
        if line:
            if line.product_id != pid: line.unit_cost = line.unit_customs = None  # ürün değiştiyse eski fiyat geçersiz
            line.product_id, line.name, line.qty, line.position = pid, products[pid].name, qty, pos
            seen.add(line.id)
        else:
            req.lines.append(ReqLine(product_id=pid, name=products[pid].name, qty=qty, position=pos))
        pos += 1
    for line in list(req.lines):
        if line.id in by_id and line.id not in seen: req.lines.remove(line)
    req.updated_at = _now()
    _log(s, actor, req, "edit", f"Ürünler güncellendi ({len(req.lines)} kalem).")
    s.commit()


_FIELD_STAGE = {"unit_cost": ("fiyat", "Birim alış fiyatları"), "unit_customs": ("gumruk", "Birim gümrük masrafları"),
                "unit_logistics": ("gumruk", "Birim lojistik masrafları"),
                "margin_pct": ("teklif", "Ürün bazlı kâr marjı"), "sale_price_override": ("teklif", "Doğrudan satış fiyatı")}


@_atomic
def save_line_values(s, actor: Actor, req: Req, field: str, rows: list[dict]):
    """rows: {id, value}. unit_cost yalnızca Fiyat; unit_customs/unit_logistics yalnızca Gümrük; margin_pct/sale_price_override
    yalnızca Teklif aşamasında yazılır. `sale_price_override`'da 0 (ya da altı) "boş" sayılır: kimse ürünü gerçekten
    $0'a satmak istemez, bu yüzden yanlışlıkla girilen bir 0 marjı sessizce iptal etmek yerine "girilmemiş" gibi davranırız
    (kâr marjına geri döner) — kullanıcı geri bildirimiyle netleşen bir karışıklığı önlemek için."""
    stage, label = _FIELD_STAGE[field]
    _guard_edit(actor, req)
    _require_stage(req, stage)
    by_id = {l.id: l for l in req.lines}
    changed = 0
    for r in rows:
        rid = _num(r.get("id"))
        line = by_id.get(int(rid)) if rid is not None else None
        if not line: continue
        value = _num(r.get("value"))
        if field == "sale_price_override" and value is not None and value <= 0: value = None
        if value is not None and value < 0: raise ServiceError("Tutarlar negatif olamaz.")
        if getattr(line, field) != value:
            setattr(line, field, value)
            changed += 1
    if changed:
        req.updated_at = _now()
        _log(s, actor, req, "edit", f"{label} güncellendi.")
    s.commit()


@_atomic
def save_costs(s, actor: Actor, req: Req, rows: list[dict]):
    """Ürüne bağlı olmayan ekstra masraflar (Gümrük aşaması); her biri gümrük / lojistik / diğer türünde. Liste baştan yazılır."""
    _guard_edit(actor, req)
    _require_stage(req, "gumruk")
    clean = []
    for r in rows:
        label, amount, kind = _text(r.get("label")), _num(r.get("amount")), _text(r.get("kind")) or "diger"
        if not label and amount is None: continue
        if kind not in pl.COST_KINDS: raise ServiceError(f"Geçersiz masraf türü: {kind}")
        if not label: raise ServiceError("Ekstra masraf için açıklama yazın.")
        if amount is None or amount < 0: raise ServiceError(f"'{label}' için geçerli bir tutar girin.")
        clean.append((label, amount, kind))
    if [(c.label, c.amount, c.kind) for c in req.costs] == clean:
        s.commit()
        return
    req.costs.clear()
    for label, amount, kind in clean: req.costs.append(ReqCost(label=label, amount=amount, kind=kind))
    req.updated_at = _now()
    _log(s, actor, req, "edit", f"Ekstra masraflar güncellendi ({len(clean)} kalem).")
    s.commit()


_STAGE_FIELDS = {"talep": ("delivery_type",), "siparis": ("customer_po_no",),
                 "teklif": ("margin_pct", "logistics_margin_pct", "tax_enabled", "tax_pct", "valid_days", "payment_terms", "logistics_mode")}


@_atomic
def update_fields(s, actor: Actor, req: Req, **fields):
    _guard_edit(actor, req)
    allowed = _STAGE_FIELDS.get(req.stage, ())
    for key in fields:
        if key not in allowed: raise ServiceError(f"'{key}' alanı '{pl.STAGE_BY_KEY[req.stage].label}' aşamasında düzenlenemez.")
    for key in ("margin_pct", "logistics_margin_pct"):
        if key in fields and fields[key] is not None and fields[key] < 0: raise ServiceError("Kâr marjı negatif olamaz.")
    if "tax_pct" in fields and not 0 <= (fields["tax_pct"] or 0) <= 100: raise ServiceError("KDV oranı 0-100 arasında olmalı.")
    if "delivery_type" in fields and fields["delivery_type"] not in pl.DELIVERY_TYPES: raise ServiceError("Geçersiz teslimat tipi.")
    if "logistics_mode" in fields and fields["logistics_mode"] not in pl.LOGISTICS_MODES: raise ServiceError("Geçersiz lojistik gösterimi.")
    changed = [k for k, v in fields.items() if getattr(req, k) != v]
    for k in changed: setattr(req, k, fields[k])
    if changed:
        req.updated_at = _now()
        _log(s, actor, req, "edit", "Güncellendi: " + ", ".join(f"{k}={fields[k]}" for k in changed))
    s.commit()


@_atomic
def update_currency(s, actor: Actor, req: Req, currency: str):
    """Yanlışlıkla seçilen para birimini düzeltir; sipariş kilidi dışında herhangi bir aşamada çalışır
    (yalnızca stage-sahibi roller değil, MANAGE_ROLES)."""
    if not pl.can_view_req(actor.id, actor.role, req): raise ServiceError("Bu REQ üzerinde yetkiniz yok.")
    if req.status != pl.ACTIVE: raise ServiceError("Bu REQ aktif değil.")
    _require_role(actor, pl.MANAGE_ROLES, "Para birimi düzeltme")
    if currency not in pl.CURRENCIES: raise ServiceError("Geçersiz para birimi.")
    if currency != req.currency:
        req.currency = currency
        req.updated_at = _now()
        _log(s, actor, req, "edit", f"Para birimi düzeltildi: {currency}.")
    s.commit()


def _quote_content(req: Req) -> dict:
    """Müşteriye görünen teklif içeriği (maliyet ve kâr içermez). Parmak izi bu içerikten hesaplanır."""
    q = pl.quote_for_req(req)
    specs = [l.product.spec if l.product else "" for l in req.lines]
    rows, product_index = [], 0
    for r in q.rows:
        spec = specs[product_index] if r["kind"] == "urun" and product_index < len(specs) else ""
        product_index += 1 if r["kind"] == "urun" else 0
        rows.append({"name": r["name"], "spec": spec, "qty": r["qty"], "unit_price": r["unit_price"], "line_total": r["line_total"]})
    return {"reference": req.code, "currency": req.currency, "delivery_type": req.delivery_type, "payment_terms": req.payment_terms,
            "valid_days": req.valid_days, "tax_enabled": bool(req.tax_enabled), "tax_pct": req.tax_pct if req.tax_enabled else 0.0,
            "rows": rows, "total": q.total, "tax": q.tax, "grand_total": q.grand_total}


@_atomic
def issue_quote(s, actor: Actor, req: Req) -> QuoteDoc:
    """Teklif aşamasındaki REQ için numaralı teklif (PDF verisi) oluşturur. İçerik son teklifle aynıysa yenisini açmaz;
    değişmişse aynı numaranın yeni revizyonunu (-R2, -R3...) açar. Demo REQ'ler gerçek numara sayacını tüketmez."""
    _guard_edit(actor, req)
    _require_stage(req, "teklif")
    if req.margin_pct is None: raise ServiceError("Önce kâr marjını girip kaydedin.")
    content = _quote_content(req)
    if content["total"] <= 0: raise ServiceError("Teklif tutarı 0; fiyatları ve marjı kontrol edin.")
    fingerprint = hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    existing = list(req.quotes)
    if existing and existing[-1].fingerprint == fingerprint: return existing[-1]

    company, now = s.get(Company, actor.company_id), _now()
    if existing:
        number = f"{existing[0].number}-R{len(existing) + 1}"
    elif req.is_demo:
        number = f"DEMO-{req.code}"
    else:
        s.execute(update(Company).where(Company.id == company.id).values(quote_seq=Company.quote_seq + 1))
        seq = s.scalar(select(Company.quote_seq).where(Company.id == company.id))
        number = f"{company.quote_prefix}{now.astimezone(_TR_TZ):%y%m%d}{seq:03d}"
    valid_until = now + timedelta(days=int(req.valid_days))
    # Ödeme açıklaması otomatik: önek + teklif numarasının son 3 hanesi (örn. OZ207) — Odoo örneğindeki gibi.
    # Demo/revizyon numaraları (DEMO-..., ...-R2) 3 haneli sayısal sırayla bitmez; o durumlarda anlamsız bir kısaltma
    # üretmek yerine boş bırakılır (PDF'de satır hiç görünmez).
    payment_ref = f"{company.quote_prefix}{number[-3:]}" if number[-3:].isdigit() else ""
    snapshot = {**content, "number": number, "payment_ref": payment_ref, "issued_at": now.astimezone(_TR_TZ).strftime("%d.%m.%Y"),
                "valid_until": valid_until.astimezone(_TR_TZ).strftime("%d.%m.%Y"),
                "customer": {"name": req.customer.name, "address": req.customer.address, "tax_no": req.customer.tax_no, "email": req.customer.email},
                "company": {"name": company.legal_name or company.name, "brand": company.name, "address": company.address,
                            "tax_info": company.tax_info, "phone": company.phone, "email": company.email, "website": company.website,
                            "bank_info": company.bank_info}}
    doc = QuoteDoc(company_id=actor.company_id, req_id=req.id, version=len(existing) + 1, number=number, fingerprint=fingerprint,
                   issued_at=now, issued_by=actor.id, valid_until=valid_until, currency=req.currency, total=content["total"],
                   grand_total=content["grand_total"], snapshot=json.dumps(snapshot, ensure_ascii=False))
    req.quotes.append(doc)
    _log(s, actor, req, "edit", f"Teklif oluşturuldu: {number}")
    s.commit()
    return doc


def list_quotes(s, actor: Actor, req: Req) -> list[QuoteDoc]:
    """En yeni revizyon başta. Yalnızca teklif aşamasını görebilen roller (yönetici/ürün yöneticisi) görür."""
    if not pl.can_view_req(actor.id, actor.role, req) or not pl.can_view_stage(actor.role, "teklif"): return []
    return list(reversed(req.quotes))


@_atomic
def mark_quote_sent(s, actor: Actor, req: Req):
    _guard_edit(actor, req)
    _require_stage(req, "teklif")
    doc = issue_quote(s, actor, req)  # güncel içerikle eşleşen numaralı teklif yoksa oluşturur
    req.quote_sent_at = _now()
    _log(s, actor, req, "edit", f"Teklif müşteriye iletildi olarak işaretlendi ({doc.number}).")
    s.commit()


def _issue_po_number(s, actor: Actor, req: Req) -> str:
    """Bizim tedarikçiye (Çin ofisi) açtığımız satın alma sipariş numarası; teklif numarasıyla aynı mantıkta atomik artar."""
    if req.is_demo: return f"DEMO-{req.code}"
    company = s.get(Company, actor.company_id)
    s.execute(update(Company).where(Company.id == company.id).values(po_seq=Company.po_seq + 1))
    seq = s.scalar(select(Company.po_seq).where(Company.id == company.id))
    return f"{company.po_prefix}{_now().astimezone(_TR_TZ):%y%m%d}{seq:03d}"


@_atomic
def set_po_approved(s, actor: Actor, req: Req, approved: bool):
    _guard_edit(actor, req)
    _require_stage(req, "siparis")
    if approved:
        req.po_approved_at = _now()
        if not req.po_number: req.po_number = _issue_po_number(s, actor, req)
        _log(s, actor, req, "edit", f"Çin ofisine satın alma onayı verildi ({req.po_number}).")
    else:
        req.po_approved_at = None
        _log(s, actor, req, "edit", "Satın alma onayı geri alındı.")
    s.commit()


@_atomic
def create_delivery(s, actor: Actor, req: Req, rows: list[dict], delivered_by: str = "", delivered_to: str = "") -> DeliveryDoc:
    """Teslimat makbuzu (OUT/NNNN) oluşturur. rows: [{"line_id", "qty"}, ...] — bu teslimatta teslim edilen adetler
    (0 veya boş olanlar atlanır). Yalnızca Teslim aşamasında; kalan adedi (REQ'deki toplam - önceki teslimatlar) aşan
    girişler reddedilir. Kısmi (ön) teslimat desteklenir: aynı REQ için birden fazla makbuz oluşturulabilir."""
    _guard_edit(actor, req)
    _require_stage(req, "teslim")
    lines_by_id = {l.id: l for l in req.lines}
    clean = []
    for r in rows:
        line_id = _num(r.get("line_id"))
        if line_id is None: continue
        line = lines_by_id.get(int(line_id))
        if not line: raise ServiceError("Geçersiz REQ satırı.")
        qty = _num(r.get("qty")) or 0
        if qty <= 0: continue
        remaining = (line.qty or 0) - pl.delivered_qty(req, line.id)
        if qty > remaining + 1e-9:
            raise ServiceError(f"'{line.name}' için en fazla {remaining:g} adet teslim edilebilir (kalan).")
        clean.append((line, qty))
    if not clean: raise ServiceError("Teslim edilecek en az bir ürün ve adet girin.")

    company = s.get(Company, actor.company_id)
    s.execute(update(Company).where(Company.id == company.id).values(delivery_seq=Company.delivery_seq + 1))
    seq = s.scalar(select(Company.delivery_seq).where(Company.id == company.id))
    number = f"{company.delivery_prefix}/{seq:05d}"
    now = _now()
    order_ref = req.quotes[-1].number if req.quotes else req.code  # müşterinin gördüğü sipariş no: son teklif numarası
    rows_snapshot = [{"name": line.name, "ordered": line.qty, "delivered": qty} for line, qty in clean]
    snapshot = {"number": number, "reference": req.code, "order_ref": order_ref, "issued_at": now.astimezone(_TR_TZ).strftime("%d.%m.%Y"),
                "delivered_by": _text(delivered_by), "delivered_to": _text(delivered_to) or req.customer.name, "rows": rows_snapshot,
                "customer": {"name": req.customer.name, "address": req.customer.address},
                "company": {"name": company.legal_name or company.name, "brand": company.name}}
    doc = DeliveryDoc(company_id=actor.company_id, req_id=req.id, number=number, issued_by=actor.id,
                      delivered_by=_text(delivered_by), delivered_to=_text(delivered_to),
                      snapshot=json.dumps(snapshot, ensure_ascii=False))
    for line, qty in clean: doc.lines.append(DeliveryLine(req_line_id=line.id, qty=qty))
    req.deliveries.append(doc)
    _log(s, actor, req, "edit", f"Teslimat makbuzu oluşturuldu: {number} ({len(clean)} kalem)")
    s.commit()
    return doc


def list_deliveries(s, actor: Actor, req: Req) -> list[DeliveryDoc]:
    """En yeni önce."""
    if not pl.can_view_req(actor.id, actor.role, req): raise ServiceError("Bu REQ üzerinde yetkiniz yok.")
    return list(reversed(req.deliveries))


@_atomic
def advance_req(s, actor: Actor, req: Req) -> Req:
    _guard_edit(actor, req)
    errors = pl.check_gate(req.stage, req)
    if errors: raise ServiceError("Sonraki aşamaya geçmek için eksikler var.", errors)
    old, new = req.stage, pl.next_stage(req.stage)
    if new is None:
        req.status = pl.DONE
        _log(s, actor, req, "status", "REQ tamamlandı.", from_stage=old)
    else:
        req.stage = new
        _log(s, actor, req, "stage", f"{pl.STAGE_BY_KEY[old].label} → {pl.STAGE_BY_KEY[new].label}", from_stage=old, to_stage=new)
    req.updated_at = _now()
    s.commit()
    return req


@_atomic
def decide(s, actor: Actor, req: Req, approved: bool, reason: str = "") -> Req:
    """Müşteri kararı: onay ise Sipariş'e geçer, ret ise REQ rafa kaldırılır."""
    _guard_edit(actor, req)
    _require_stage(req, "karar")
    if approved:
        req.decision = "onay"
        _log(s, actor, req, "edit", "Müşteri teklifi onayladı.")
        s.commit()
        return advance_req(s, actor, req)
    if not _text(reason): raise ServiceError("Ret sebebini yazın.")
    req.decision = "ret"
    return shelve_req(s, actor, req, reason)


@_atomic
def move_back(s, actor: Actor, req: Req, reason: str) -> Req:
    _require_role(actor, pl.MANAGE_ROLES, "Aşamayı geri alma")
    if not pl.can_view_req(actor.id, actor.role, req): raise ServiceError("Bu REQ üzerinde yetkiniz yok.")
    if req.status != pl.ACTIVE: raise ServiceError("Yalnızca aktif REQ geri alınabilir.")
    previous = pl.prev_stage(req.stage)
    if previous is None: raise ServiceError("REQ zaten ilk aşamada.")
    if not _text(reason): raise ServiceError("Geri alma sebebini yazın.")
    old = req.stage
    for f in pl.CLEAR_ON_ARRIVE.get(previous, ()): setattr(req, f, None)
    req.stage = previous
    req.updated_at = _now()
    _log(s, actor, req, "stage", f"Geri alındı: {pl.STAGE_BY_KEY[old].label} → {pl.STAGE_BY_KEY[previous].label}. Sebep: {_text(reason)}",
         from_stage=old, to_stage=previous)
    s.commit()
    return req


@_atomic
def shelve_req(s, actor: Actor, req: Req, reason: str) -> Req:
    _require_role(actor, pl.MANAGE_ROLES, "REQ'yi rafa kaldırma")
    if not pl.can_view_req(actor.id, actor.role, req): raise ServiceError("Bu REQ üzerinde yetkiniz yok.")
    if req.status != pl.ACTIVE: raise ServiceError("Yalnızca aktif REQ rafa kaldırılabilir.")
    if not _text(reason): raise ServiceError("Rafa kaldırma sebebini yazın.")
    req.status, req.shelved_reason, req.updated_at = pl.SHELVED, _text(reason), _now()
    _log(s, actor, req, "status", f"Rafa kaldırıldı. Sebep: {_text(reason)}")
    s.commit()
    return req


@_atomic
def reopen_req(s, actor: Actor, req: Req) -> Req:
    _require_role(actor, pl.MANAGE_ROLES, "REQ'yi yeniden açma")
    if not pl.can_view_req(actor.id, actor.role, req): raise ServiceError("Bu REQ üzerinde yetkiniz yok.")
    if req.status != pl.SHELVED: raise ServiceError("Yalnızca rafa kaldırılmış REQ yeniden açılabilir.")
    req.status, req.shelved_reason, req.updated_at = pl.ACTIVE, "", _now()
    if req.decision == "ret": req.decision = None
    _log(s, actor, req, "status", "REQ yeniden açıldı.")
    s.commit()
    return req


_SUPPLIER_STAGES = ("talep", "fiyat")


@_atomic
def set_line_supplier(s, actor: Actor, req: Req, line_id: int, supplier_id: int | None):
    """Talep ya da Fiyat Araştırması aşamasında bir REQ satırı için tedarikçi seçimi (bilgi amaçlı; fiyatı etkilemez)."""
    _guard_edit(actor, req)
    if req.stage not in _SUPPLIER_STAGES:
        raise ServiceError(f"Tedarikçi seçimi yalnızca Talep veya Fiyat Araştırması aşamasında yapılabilir.")
    line = next((l for l in req.lines if l.id == line_id), None)
    if not line: raise ServiceError("Geçersiz REQ satırı.")
    supplier_name = None
    if supplier_id is not None:
        supplier = s.get(Partner, supplier_id)
        if not supplier or supplier.company_id != actor.company_id or not supplier.is_supplier or supplier.deleted_at:
            raise ServiceError("Geçersiz tedarikçi.")
        supplier_name = supplier.name
    if line.supplier_id != supplier_id:
        line.supplier_id = supplier_id
        req.updated_at = _now()
        _log(s, actor, req, "edit", f"Tedarikçi seçildi: {line.name} → {supplier_name or '(kaldırıldı)'}")
    s.commit()


@_atomic
def save_line_suppliers(s, actor: Actor, req: Req, rows: list[dict]):
    """rows: {id, supplier_id | None}. Fiyat tablosundan elle tedarikçi seçimi (akıllı aramaya gerek kalmadan);
    kurallar set_line_supplier ile aynı. Değişmeyen satırlara dokunmaz."""
    _guard_edit(actor, req)
    if req.stage not in _SUPPLIER_STAGES:
        raise ServiceError("Tedarikçi seçimi yalnızca Talep veya Fiyat Araştırması aşamasında yapılabilir.")
    by_id = {l.id: l for l in req.lines}
    suppliers = {p.id: p for p in s.scalars(select(Partner).where(Partner.company_id == actor.company_id, Partner.is_supplier.is_(True),
                                                                   Partner.deleted_at.is_(None)))}
    changes = []
    for r in rows:
        line = by_id.get(int(r["id"])) if r.get("id") is not None else None
        sid = r.get("supplier_id")
        if not line or line.supplier_id == sid: continue
        if sid is not None and sid not in suppliers: raise ServiceError("Geçersiz tedarikçi.")
        line.supplier_id = sid
        changes.append(f"{line.name} → {suppliers[sid].name if sid else '(kaldırıldı)'}")
    if changes:
        req.updated_at = _now()
        _log(s, actor, req, "edit", "Tedarikçi seçildi: " + "; ".join(changes))
    s.commit()


_REQ_NO = re.compile(r"_REQ_(\d+)$")


@_atomic
def update_req_number(s, actor: Actor, req: Req, number: int) -> str:
    """Yanlış numarayla açılmış REQ'in yalnızca SAYISINI düzeltir (önek müşterinin kısa kodudur, Kişiler'den değişir).
    Sayaç buna göre devam eder: düzeltilen REQ müşterinin son açılan REQ'i ise sayaç yeni numaraya çekilir (aşağı dahil),
    değilse yalnızca yeni numara sayaçtan büyükse sayaç ilerletilir. Eski teklif PDF'leri eski kodla kalır (snapshot)."""
    _require_role(actor, pl.MANAGE_ROLES, "REQ numarası düzeltme")
    if not pl.can_view_req(actor.id, actor.role, req): raise ServiceError("Bu REQ üzerinde yetkiniz yok.")
    number = int(number or 0)
    if number < 1: raise ServiceError("REQ numarası 1 veya daha büyük olmalı.")
    customer = s.get(Partner, req.customer_id)
    new_code, old_code = f"{customer.short_code}_REQ_{number:02d}", req.code
    if new_code == old_code: return old_code
    if s.scalar(select(Req.id).where(Req.company_id == actor.company_id, Req.code == new_code, Req.id != req.id)):
        raise ServiceError(f"{new_code} zaten kullanılıyor.")
    match = _REQ_NO.search(old_code)
    was_latest = match is not None and int(match.group(1)) == (customer.req_seq or 0)
    if was_latest or number > (customer.req_seq or 0): customer.req_seq = number
    req.code, req.updated_at = new_code, _now()
    _log(s, actor, req, "edit", f"REQ kodu düzeltildi: {old_code} → {new_code} (müşterinin sonraki REQ'i {customer.req_seq + 1:02d} olacak).")
    s.commit()
    return new_code


@_atomic
def update_line_qtys(s, actor: Actor, req: Req, rows: list[dict]):
    """rows: {id, qty}. Yanlış girilen adetler REQ aktif olduğu sürece HER aşamada düzeltilebilir (aşamaya geri dönmeden).
    Güvenlik: adet, o satırdan zaten teslim edilen ya da kargoya ayrılan miktarın altına inemez. Teklif iletildiyse
    iletilen PDF değişmez; yeni PDF oluşturulursa içerik farklı olduğu için revizyon (-R2) açılır."""
    _require_role(actor, pl.MANAGE_ROLES, "Adet düzeltme")
    if not pl.can_view_req(actor.id, actor.role, req): raise ServiceError("Bu REQ üzerinde yetkiniz yok.")
    if req.status != pl.ACTIVE: raise ServiceError("Bu REQ aktif değil.")
    by_id = {l.id: l for l in req.lines}
    shipped = dict(s.execute(select(ShipmentItem.req_line_id, func.sum(ShipmentItem.qty))
                             .where(ShipmentItem.req_id == req.id).group_by(ShipmentItem.req_line_id)).all())
    changes = []
    for r in rows:
        line = by_id.get(int(r["id"])) if r.get("id") is not None else None
        qty = _num(r.get("qty"))
        if not line or qty is None or qty == line.qty: continue
        if qty <= 0: raise ServiceError(f"Adet 0'dan büyük olmalı: {line.name}")
        floor = max(pl.delivered_qty(req, line.id), shipped.get(line.id, 0.0) or 0.0)
        if qty < floor - 1e-9:
            raise ServiceError(f"'{line.name}' için adet {floor:g}'in altına inemez (teslim edilen/kargoya ayrılan miktar).")
        changes.append(f"{line.name}: {line.qty:g} → {qty:g}")
        line.qty = qty
    if changes:
        req.updated_at = _now()
        _log(s, actor, req, "edit", "Adet düzeltildi: " + "; ".join(changes))
    s.commit()


def search_suppliers(s, actor: Actor, req: Req) -> tuple[list[dict], str]:
    """REQ'in ürünlerini tedarikçi havuzuyla (Kişiler > Tedarikçiler) Gemini ile eşleştirir. Yazma yapmaz."""
    if not pl.can_view_req(actor.id, actor.role, req): raise ServiceError("Bu REQ üzerinde yetkiniz yok.")
    suppliers = list(s.scalars(select(Partner).where(Partner.company_id == actor.company_id, Partner.is_supplier.is_(True),
                                                     Partner.deleted_at.is_(None))))
    items = [l.name + (f" ({l.product.spec})" if l.product and l.product.spec else "") for l in req.lines]
    pool = [{"id": p.id, "name": p.name, "category": p.category, "keywords": p.keywords, "country": p.country, "email": p.email} for p in suppliers]
    matches, error = ai.match_suppliers(items, pool)
    if error: return [], error
    by_id = {p.id: p for p in suppliers}
    for m in matches:  # AI'nın döndürdüğü id/isim güvenilmez; havuzdaki gerçek kayıtla eşleştir ve e-postayı bizim veriden al
        supplier = by_id.get(_num(m.get("tedarikci_id")) and int(m["tedarikci_id"])) if _num(m.get("tedarikci_id")) is not None else None
        if not supplier: supplier = next((p for p in suppliers if p.name == m.get("tedarikci")), None)
        m["tedarikci_id"] = supplier.id if supplier else None
        m["tedarikci"] = supplier.name if supplier else m.get("tedarikci", "-")
        m["eposta"] = supplier.email if supplier else ""
    return [m for m in matches if m["tedarikci_id"]], ""


@_atomic
def add_note(s, actor: Actor, req: Req, text: str, *, assignee_id: int | None = None):
    """assignee_id verilirse bir GÖREV oluşturur (kind='task'), verilmezse normal bir not."""
    if not pl.can_view_req(actor.id, actor.role, req): raise ServiceError("Bu REQ üzerinde yetkiniz yok.")
    if not _text(text): raise ServiceError("Not boş olamaz.")
    if assignee_id is not None:
        assignee = s.get(User, assignee_id)
        if not assignee or assignee.company_id != actor.company_id: raise ServiceError("Geçersiz kullanıcı.")
        if not pl.can_view_req(assignee.id, assignee.role, req):
            raise ServiceError(f"{assignee.name} bu REQ'i göremediği için göreve atanamaz.")
        event = Event(company_id=actor.company_id, req_id=req.id, user_id=actor.id, kind="task", message=_text(text),
                     stage=req.stage, assignee_id=assignee_id)
        s.add(event)
    else:
        _log(s, actor, req, "note", _text(text))
    s.commit()


def _guard_task(s, actor: Actor, event_id: int) -> Event:
    event = s.get(Event, event_id)
    if not event or event.company_id != actor.company_id or event.kind != "task" or event.deleted_at: raise ServiceError("Görev bulunamadı.")
    if event.assignee_id != actor.id and actor.role not in pl.MANAGE_ROLES:
        raise ServiceError("Bu görevi yalnızca atanan kişi ya da yöneticiler değiştirebilir.")
    return event


@_atomic
def complete_task(s, actor: Actor, event_id: int):
    """Görevi tamamlandı işaretler. Görevin atandığı kişi ya da yönetici roller işaretleyebilir."""
    event = _guard_task(s, actor, event_id)
    if event.done_at is None and event.cancelled_at is None:
        event.done_at = _now()
        s.commit()


@_atomic
def cancel_task(s, actor: Actor, event_id: int):
    """Görevi iptal eder. Görevin atandığı kişi ya da yönetici roller iptal edebilir."""
    event = _guard_task(s, actor, event_id)
    if event.done_at is None and event.cancelled_at is None:
        event.cancelled_at = _now()
        s.commit()


def list_assignable_users(s, actor: Actor) -> list[User]:
    """Aynı şirketteki aktif kullanıcılar — görev atama seçici için (list_users'ın aksine şirket bazlı filtrelenir)."""
    return list(s.scalars(select(User).where(User.company_id == actor.company_id, User.active.is_(True)).order_by(User.name)))


def list_assignable_users_for_req(s, actor: Actor, req: Req) -> list[User]:
    """Görev atanabilecek kullanıcılar bu REQ'i ZATEN görebilenlerle sınırlıdır — aksi halde atanan kişi kendi
    görevini açamaz (REQ görünürlüğü sahiplik bazlıdır; bkz. pipeline.can_view_req, get_req)."""
    return [u for u in list_assignable_users(s, actor) if pl.can_view_req(u.id, u.role, req)]


def list_my_open_tasks(s, actor: Actor) -> list[Event]:
    """Bana atanmış, henüz tamamlanmamış görevler — kenar çubuğundaki bildirim için."""
    return list(s.scalars(select(Event).options(joinedload(Event.req)).where(
        Event.company_id == actor.company_id, Event.kind == "task", Event.assignee_id == actor.id,
        Event.done_at.is_(None), Event.cancelled_at.is_(None), Event.deleted_at.is_(None),
        Event.req_id.in_(select(Req.id).where(Req.deleted_at.is_(None))),  # silinmiş REQ'in görevi bildirimde görünmesin
    ).order_by(Event.created_at)))


# ---------------------------------------------------------------- kargo (CRG)

_SHIPMENT_OPTS = (selectinload(Shipment.items).joinedload(ShipmentItem.req),
                  selectinload(Shipment.items).joinedload(ShipmentItem.req_line).joinedload(ReqLine.product))
_SHIPMENT_TEXT = ("awb_no", "carrier", "gcb_no", "delivery_address", "current_location", "notes")


def _clean_shipment_fields(fields: dict) -> dict:
    clean = {}
    for key, value in fields.items():
        if key in _SHIPMENT_TEXT: clean[key] = _text(value)
        elif key == "departure_date": clean[key] = value  # datetime | None
        elif key == "logistics_status":
            if value not in pl.LOGISTICS_STATUSES: raise ServiceError("Geçersiz lojistik durumu.")
            clean[key] = value
        elif key == "customs_status":
            if value not in pl.CUSTOMS_STATUSES: raise ServiceError("Geçersiz gümrük statüsü.")
            clean[key] = value
        elif key == "delivery_type":
            if value not in (*pl.DELIVERY_TYPES, "Belirtilmedi"): raise ServiceError("Geçersiz teslimat tipi.")
            clean[key] = value
        else:
            raise ServiceError(f"Bilinmeyen kargo alanı: {key}")
    return clean


def list_shipments(s, actor: Actor) -> list[Shipment]:
    """Admin ve gümrük tüm kargoları görür; ürün yöneticisi yalnızca kendi REQ'lerinden içerik taşıyan kargoları görür."""
    q = select(Shipment).options(*_SHIPMENT_OPTS).where(Shipment.company_id == actor.company_id)
    if actor.role == pl.TRADE_MANAGER:
        q = (q.join(ShipmentItem, ShipmentItem.shipment_id == Shipment.id)
              .join(Req, Req.id == ShipmentItem.req_id).where(Req.owner_id == actor.id))
    elif actor.role not in (pl.ADMIN, pl.CUSTOMS_BROKER):
        return []
    return list(s.scalars(q.order_by(Shipment.updated_at.desc())).unique())


def get_shipment(s, actor: Actor, *, shipment_id: int | None = None, code: str | None = None) -> Shipment:
    q = select(Shipment).options(*_SHIPMENT_OPTS).where(Shipment.company_id == actor.company_id)
    q = q.where(Shipment.id == shipment_id) if shipment_id is not None else q.where(Shipment.code == code)
    shipment = s.scalar(q)
    if not shipment: raise ServiceError("Kargo bulunamadı.")
    if actor.role == pl.TRADE_MANAGER and not any(item.req.owner_id == actor.id for item in shipment.items):
        raise ServiceError("Bu kargo üzerinde yetkiniz yok.")
    return shipment


@_atomic
def create_shipment(s, actor: Actor, **fields) -> Shipment:
    """`delivery_address` verilmezse (ya da boşsa) varsayılan olarak `pipeline.DEFAULT_DELIVERY_ADDRESS` atanır;
    kullanıcı değiştirmediği sürece bu değer kalır."""
    _require_role(actor, pl.ALL_ROLES, "Kargo oluşturma")
    company = s.get(Company, actor.company_id)
    s.execute(update(Company).where(Company.id == company.id).values(shipment_seq=Company.shipment_seq + 1))
    seq = s.scalar(select(Company.shipment_seq).where(Company.id == company.id))
    clean = _clean_shipment_fields(fields)
    clean.setdefault("delivery_address", pl.DEFAULT_DELIVERY_ADDRESS)
    if not clean["delivery_address"]: clean["delivery_address"] = pl.DEFAULT_DELIVERY_ADDRESS
    shipment = Shipment(company_id=actor.company_id, code=f"{company.shipment_prefix}_{seq:02d}", created_by=actor.id, **clean)
    s.add(shipment)
    s.commit()
    return shipment


@_atomic
def update_shipment(s, actor: Actor, shipment: Shipment, **fields) -> Shipment:
    _require_role(actor, pl.ALL_ROLES, "Kargo düzenleme")
    for key, value in _clean_shipment_fields(fields).items(): setattr(shipment, key, value)
    shipment.updated_at = _now()
    s.commit()
    return shipment


def shippable_lines(s, actor: Actor, req: Req, exclude_shipment_id: int | None = None) -> list[dict]:
    """Her REQ satırı için kalan (henüz herhangi bir kargoya eklenmemiş) adet. exclude_shipment_id verilirse, o kargonun
    kendi mevcut ayırması kalan hesaba geri eklenir (bir kargoyu düzenlerken/genişletirken kullanılır)."""
    q = select(ShipmentItem.req_line_id, func.sum(ShipmentItem.qty)).where(ShipmentItem.req_id == req.id)
    if exclude_shipment_id is not None: q = q.where(ShipmentItem.shipment_id != exclude_shipment_id)
    shipped = dict(s.execute(q.group_by(ShipmentItem.req_line_id)).all())
    return [{"line": l, "shipped": shipped.get(l.id, 0.0), "remaining": (l.qty or 0) - shipped.get(l.id, 0.0)} for l in req.lines]


@_atomic
def add_shipment_item(s, actor: Actor, shipment: Shipment, req_line_id: int, qty) -> None:
    """qty, bu kargodaki MUTLAK toplam adettir (satır zaten bu kargodaysa üzerine yazar, eklemez).
    `shipment.items` üzerinde doğrudan çalışır (ham SQL ile ekleme/silme yapmaz) ki aynı oturumda önceden
    yüklenmiş koleksiyon bayatlamasın — `req.lines`/`req.costs` ile aynı desen."""
    _require_role(actor, pl.ALL_ROLES, "Kargoya ürün ekleme")
    line = s.get(ReqLine, req_line_id)
    if not line or line.req.company_id != actor.company_id: raise ServiceError("Geçersiz REQ satırı.")
    qty = _num(qty) or 0
    if qty <= 0: raise ServiceError("Adet 0'dan büyük olmalı.")
    info = next(r for r in shippable_lines(s, actor, line.req, exclude_shipment_id=shipment.id) if r["line"].id == line.id)
    if qty > info["remaining"]:
        raise ServiceError(f"'{line.name}' için en fazla {info['remaining']:g} adet eklenebilir (REQ'de {line.qty:g} adetten boşta kalan).")
    existing = next((it for it in shipment.items if it.req_line_id == line.id), None)
    if existing: existing.qty = qty
    else: shipment.items.append(ShipmentItem(req_line_id=line.id, req_id=line.req_id, qty=qty))
    shipment.updated_at = _now()
    s.commit()


@_atomic
def remove_shipment_item(s, actor: Actor, shipment: Shipment, item_id: int):
    _require_role(actor, pl.ALL_ROLES, "Kargodan ürün çıkarma")
    item = next((it for it in shipment.items if it.id == item_id), None)
    if not item: raise ServiceError("Geçersiz kayıt.")
    shipment.items.remove(item)  # cascade="all, delete-orphan": flush'ta veritabanından da silinir
    shipment.updated_at = _now()
    s.commit()


def req_shipments(s, actor: Actor, req: Req) -> list[Shipment]:
    """Bu REQ'in en az bir satırını içeren kargolar (bilgi amaçlıdır; REQ'in kendi aşama akışını etkilemez/değiştirmez)."""
    ids = s.scalars(select(ShipmentItem.shipment_id).where(ShipmentItem.req_id == req.id).distinct())
    return [shipment for i in ids if (shipment := s.get(Shipment, i)) is not None]


def list_attachments(s, actor: Actor, shipment: Shipment) -> list[Attachment]:
    """Yalnızca üst bilgi (dosya içeriği hariç) — listeyi hafif tutar. İndirmek için get_attachment kullanılır."""
    return list(s.scalars(select(Attachment).options(defer(Attachment.data)).where(Attachment.shipment_id == shipment.id).order_by(Attachment.id)))


def list_req_attachments(s, actor: Actor, req: Req) -> list[Attachment]:
    """REQ'e eklenen dosyalar (Notlar & Görevler panelinde). Yalnızca üst bilgi; indirmek için get_attachment kullanılır."""
    if not pl.can_view_req(actor.id, actor.role, req): raise ServiceError("Bu REQ üzerinde yetkiniz yok.")
    return list(s.scalars(select(Attachment).options(defer(Attachment.data)).where(Attachment.req_id == req.id).order_by(Attachment.id)))


@_atomic
def upload_req_attachment(s, actor: Actor, req: Req, filename: str, content_type: str, data: bytes) -> Attachment:
    if not pl.can_view_req(actor.id, actor.role, req): raise ServiceError("Bu REQ üzerinde yetkiniz yok.")
    if not data: raise ServiceError("Dosya boş.")
    if len(data) > pl.MAX_ATTACHMENT_BYTES: raise ServiceError(f"Dosya çok büyük (en fazla {pl.MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB).")
    att = Attachment(company_id=actor.company_id, req_id=req.id, kind="diger", filename=_text(filename) or "dosya",
                     content_type=content_type or "application/octet-stream", size=len(data), data=data, uploaded_by=actor.id)
    s.add(att)
    s.commit()
    return att


def get_attachment(s, actor: Actor, attachment_id: int) -> Attachment:
    att = s.get(Attachment, attachment_id)
    if not att or att.company_id != actor.company_id: raise ServiceError("Belge bulunamadı.")
    return att


@_atomic
def upload_attachment(s, actor: Actor, shipment: Shipment, kind: str, filename: str, content_type: str, data: bytes) -> Attachment:
    _require_role(actor, pl.ALL_ROLES, "Belge yükleme")
    if kind not in pl.ATTACHMENT_KINDS: raise ServiceError("Geçersiz belge türü.")
    if not data: raise ServiceError("Dosya boş.")
    if len(data) > pl.MAX_ATTACHMENT_BYTES: raise ServiceError(f"Dosya çok büyük (en fazla {pl.MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB).")
    att = Attachment(company_id=actor.company_id, shipment_id=shipment.id, kind=kind, filename=_text(filename) or "dosya",
                     content_type=content_type or "application/octet-stream", size=len(data), data=data, uploaded_by=actor.id)
    s.add(att)
    shipment.updated_at = _now()
    s.commit()
    return att


@_atomic
def delete_attachment(s, actor: Actor, attachment_id: int):
    att = get_attachment(s, actor, attachment_id)
    s.delete(att)
    s.commit()


@_atomic
def refresh_dhl_tracking(s, actor: Actor, shipment: Shipment) -> str:
    """DHL'in resmi genel takip API'sinden (bkz. jarvis/tracking.py) güncel konumu çeker ve `current_location`'a yazar.
    Yalnızca DHL Express için çalışır (bkz. pipeline.AUTO_TRACKING_CARRIERS); ham açıklama notlara da eklenir."""
    _require_role(actor, pl.ALL_ROLES, "Kargo takibi güncelleme")
    if shipment.carrier not in pl.AUTO_TRACKING_CARRIERS:
        raise ServiceError(f"Otomatik takip yalnızca şu taşıyıcılarda çalışır: {', '.join(pl.AUTO_TRACKING_CARRIERS)}.")
    key = config.get_config_val("DHL_API_KEY")
    if not key: raise ServiceError("DHL_API_KEY tanımlı değil. CLAUDE.md'de kurulum talimatı var.")
    try:
        event = tracking.fetch_dhl_status(shipment.awb_no, key)
    except tracking.TrackingError as e:
        raise ServiceError(str(e)) from e
    shipment.current_location = event["location"]
    shipment.last_tracked_at = _now()
    note_line = f"[Otomatik-DHL {_now().astimezone(_TR_TZ):%d.%m.%Y %H:%M}] {event['description']} — {event['location']}"
    shipment.notes = (shipment.notes + "\n" + note_line).strip() if shipment.notes else note_line
    shipment.updated_at = _now()
    s.commit()
    return event["description"]



# ---------------------------------------------------------------- silme (çöp kutusu), kalıcı silme, ad/kod/müşteri düzeltme
# Silme = çöp kutusuna taşıma (deleted_at): kayıt her listeden/aramadan çıkar ama geri yüklenebilir. Kalıcı silme yalnızca ADMIN'de,
# yalnızca çöp kutusundaki kayıt için ve kaydın adını/kodunu yazarak onaylanır. Silme/geri yükleme/düzeltme yetkisi yönetici rollerindedir.

def _mark_deleted(rec, actor: Actor):
    rec.deleted_at, rec.deleted_by = _now(), actor.id


def _unmark_deleted(rec):
    rec.deleted_at = rec.deleted_by = None


def _typed_confirm(confirm, expected: str, what: str):
    if (confirm or "").strip() != expected: raise ServiceError(f"Kalıcı silmek için {what} aynen yazın: {expected}")


def _guard_no_shipments(s, req: Req):
    if s.scalar(select(func.count(ShipmentItem.id)).where(ShipmentItem.req_id == req.id)):
        raise ServiceError("Bu REQ bir kargoya bağlı; önce Kargo modülünden ürünlerini kargodan çıkarın.")


# ---- REQ

@_atomic
def delete_req(s, actor: Actor, req: Req):
    _require_role(actor, pl.MANAGE_ROLES, "REQ silme")
    if req.deleted_at: raise ServiceError("Bu REQ zaten silinmiş.")
    _guard_no_shipments(s, req)
    _mark_deleted(req, actor)
    _log(s, actor, req, "status", "REQ silindi (çöp kutusuna taşındı).")
    s.commit()


def list_deleted_reqs(s, actor: Actor) -> list[Req]:
    _require_role(actor, pl.MANAGE_ROLES, "Silinenleri görme")
    q = select(Req).options(*_REQ_OPTS).where(Req.company_id == actor.company_id, Req.deleted_at.is_not(None)).order_by(Req.deleted_at.desc())
    return list(s.scalars(q).unique())


@_atomic
def restore_req(s, actor: Actor, req: Req):
    """`req`: get_req(..., include_deleted=True) ile alınmış silinmiş REQ."""
    _require_role(actor, pl.MANAGE_ROLES, "REQ geri yükleme")
    if not req.deleted_at: raise ServiceError("Bu REQ silinmemiş.")
    _unmark_deleted(req)
    req.updated_at = _now()
    _log(s, actor, req, "status", "REQ geri yüklendi.")
    s.commit()


@_atomic
def purge_req(s, actor: Actor, req: Req, confirm: str):
    """Geri dönüşsüz: REQ ile birlikte satırları, masrafları, notları, teklif/teslimat kayıtları ve dosyaları gider."""
    _require_role(actor, (pl.ADMIN,), "Kalıcı silme")
    if not req.deleted_at: raise ServiceError("Önce REQ'i silinenlere taşıyın; yalnızca silinenler kalıcı silinebilir.")
    _typed_confirm(confirm, req.code, "REQ kodunu")
    _guard_no_shipments(s, req)
    s.delete(req)
    s.commit()


# ---- müşteri / tedarikçi

def _get_partner(s, actor: Actor, partner_id: int, *, deleted: bool | None = None) -> Partner:
    """deleted=None: fark etmez; True: yalnızca silinmiş olan; False: yalnızca silinmemiş olan."""
    p = s.get(Partner, partner_id)
    if not p or p.company_id != actor.company_id: raise ServiceError("Kayıt bulunamadı.")
    if deleted is True and not p.deleted_at: raise ServiceError("Bu kayıt silinmemiş.")
    if deleted is False and p.deleted_at: raise ServiceError("Kayıt bulunamadı.")
    return p


def partner_usage(s, actor: Actor) -> dict[int, dict]:
    """Kişi başına kullanım sayıları (silme uyarıları için): müşteri olarak silinmemiş REQ sayısı; tedarikçi olarak seçildiği
    satır sayısı (silinmemiş REQ'lerde) ve varsayılan tedarikçi olduğu ürün sayısı."""
    usage: dict[int, dict] = {}
    for cid, n in s.execute(select(Req.customer_id, func.count(Req.id)).where(Req.company_id == actor.company_id, Req.deleted_at.is_(None))
                            .group_by(Req.customer_id)):
        usage.setdefault(cid, {})["reqs"] = n
    for sid, n in s.execute(select(ReqLine.supplier_id, func.count(ReqLine.id)).join(Req, Req.id == ReqLine.req_id)
                            .where(Req.company_id == actor.company_id, Req.deleted_at.is_(None), ReqLine.supplier_id.is_not(None))
                            .group_by(ReqLine.supplier_id)):
        usage.setdefault(sid, {})["lines"] = n
    for sid, n in s.execute(select(Product.default_supplier_id, func.count(Product.id))
                            .where(Product.company_id == actor.company_id, Product.deleted_at.is_(None), Product.default_supplier_id.is_not(None))
                            .group_by(Product.default_supplier_id)):
        usage.setdefault(sid, {})["products"] = n
    return usage


@_atomic
def delete_partner(s, actor: Actor, partner_id: int) -> Partner:
    _require_role(actor, pl.MANAGE_ROLES, "Kişi silme")
    p = _get_partner(s, actor, partner_id, deleted=False)
    _mark_deleted(p, actor)
    s.commit()
    return p


@_atomic
def restore_partner(s, actor: Actor, partner_id: int) -> Partner:
    _require_role(actor, pl.MANAGE_ROLES, "Kişi geri yükleme")
    p = _get_partner(s, actor, partner_id, deleted=True)
    _unmark_deleted(p)
    s.commit()
    return p


@_atomic
def purge_partner(s, actor: Actor, partner_id: int, confirm: str):
    _require_role(actor, (pl.ADMIN,), "Kalıcı silme")
    p = _get_partner(s, actor, partner_id, deleted=True)
    _typed_confirm(confirm, p.name, "kaydın adını")
    n = s.scalar(select(func.count(Req.id)).where(Req.customer_id == p.id))
    if n: raise ServiceError(f"Bu müşteriye ait {n} REQ var (silinmiş olanlar dahil); REQ'ler kalıcı silinmeden müşteri kalıcı silinemez.")
    # Tedarikçi olarak seçildiği satırlar ve varsayılan tedarikçi olduğu ürünler bilgi amaçlıdır: bağlantı boşaltılır, satır/ürün kalır
    s.execute(update(ReqLine).where(ReqLine.supplier_id == p.id).values(supplier_id=None))
    s.execute(update(Product).where(Product.default_supplier_id == p.id).values(default_supplier_id=None))
    s.delete(p)
    s.commit()


@_atomic
def rename_partner(s, actor: Actor, partner_id: int, name: str) -> Partner:
    """Yalnızca görünen ad değişir. Eski teklif/teslimat PDF'leri oluşturuldukları andaki adı korur (anlık görüntü)."""
    _require_role(actor, pl.MANAGE_ROLES, "Ad değiştirme")
    p = _get_partner(s, actor, partner_id)
    name = " ".join((name or "").split())
    if not name: raise ServiceError("Ad boş olamaz.")
    if name == p.name: return p
    if owner := _name_owner(s, Partner, actor.company_id, name, exclude_id=p.id): raise _dup_error(owner, name)
    p.name = name
    s.commit()
    return p


@_atomic
def change_short_code(s, actor: Actor, partner_id: int, code: str) -> Partner:
    """Müşteri kısa kodu: yeni REQ'ler yeni kodla açılır; MEVCUT REQ kodları (ör. TTRA_REQ_17) aynen kalır. Başka bir müşterinin
    mevcut REQ kodlarıyla çakışacak bir kod verilemez (aksi halde ileride aynı kodlu iki REQ oluşurdu)."""
    _require_role(actor, pl.MANAGE_ROLES, "Kısa kod değiştirme")
    p = _get_partner(s, actor, partner_id)
    if not p.is_customer: raise ServiceError("Kısa kod yalnızca müşteriler için vardır.")
    new = re.sub(r"[^A-Z0-9]", "", (code or "").translate(_TR_ASCII).upper())
    if len(new) < 2: raise ServiceError("Kısa kod en az 2 harf/rakam olmalı.")
    if new == p.short_code: return p
    if s.scalar(select(Partner.id).where(Partner.company_id == actor.company_id, Partner.short_code == new, Partner.id != p.id)):
        raise ServiceError(f"'{new}' kısa kodu başka bir müşteride kullanılıyor (silinenler dahil).")
    clash = s.scalar(select(Req.code).where(Req.company_id == actor.company_id, Req.code.like(f"{new}\\_REQ\\_%", escape="\\"), Req.customer_id != p.id).limit(1))
    if clash: raise ServiceError(f"'{new}' koduyla başlayan bir REQ ({clash}) başka bir müşteriye ait; çakışmaması için bu kod verilemez.")
    p.short_code = new
    s.commit()
    return p


# ---- ürün

def _get_product(s, actor: Actor, product_id: int, *, deleted: bool | None = None) -> Product:
    p = s.get(Product, product_id)
    if not p or p.company_id != actor.company_id: raise ServiceError("Ürün bulunamadı.")
    if deleted is True and not p.deleted_at: raise ServiceError("Bu ürün silinmemiş.")
    if deleted is False and p.deleted_at: raise ServiceError("Ürün bulunamadı.")
    return p


def product_usage(s, actor: Actor) -> dict[int, int]:
    """Ürün başına, silinmemiş REQ'lerdeki satır sayısı (silme uyarısı için)."""
    return dict(s.execute(select(ReqLine.product_id, func.count(ReqLine.id)).join(Req, Req.id == ReqLine.req_id)
                          .where(Req.company_id == actor.company_id, Req.deleted_at.is_(None), ReqLine.product_id.is_not(None))
                          .group_by(ReqLine.product_id)).all())


@_atomic
def delete_product(s, actor: Actor, product_id: int) -> Product:
    """Katalogdan kaldırır; REQ satırlarındaki ürün adı ve bağlantı korunur (mevcut REQ'ler bozulmaz)."""
    _require_role(actor, pl.MANAGE_ROLES, "Ürün silme")
    p = _get_product(s, actor, product_id, deleted=False)
    _mark_deleted(p, actor)
    s.commit()
    return p


@_atomic
def restore_product(s, actor: Actor, product_id: int) -> Product:
    _require_role(actor, pl.MANAGE_ROLES, "Ürün geri yükleme")
    p = _get_product(s, actor, product_id, deleted=True)
    _unmark_deleted(p)
    s.commit()
    return p


@_atomic
def purge_product(s, actor: Actor, product_id: int, confirm: str):
    _require_role(actor, (pl.ADMIN,), "Kalıcı silme")
    p = _get_product(s, actor, product_id, deleted=True)
    _typed_confirm(confirm, p.name, "ürünün adını")
    s.execute(update(ReqLine).where(ReqLine.product_id == p.id).values(product_id=None))  # satırlar adını korur (ReqLine.name kopya)
    s.delete(p)
    s.commit()


@_atomic
def rename_product(s, actor: Actor, product_id: int, name: str) -> Product:
    """Katalogdaki ad değişir; mevcut REQ satırlarındaki ad kopyası değişmez (o satır Talep'te yeniden kaydedilirse güncellenir)."""
    _require_role(actor, pl.MANAGE_ROLES, "Ad değiştirme")
    p = _get_product(s, actor, product_id)
    name = " ".join((name or "").split())
    if not name: raise ServiceError("Ürün adı boş olamaz.")
    if name == p.name: return p
    if owner := _name_owner(s, Product, actor.company_id, name, exclude_id=p.id): raise _dup_error(owner, name, "kataloğda var")
    p.name = name
    s.commit()
    return p


# ---- REQ notu / görevi silme, REQ müşterisi / notu / teslimat tipi düzeltme

@_atomic
def delete_note(s, actor: Actor, event_id: int):
    """Not ya da görevi siler (gizler). Yazan kişi ya da yönetici roller silebilir. REQ geçmişine içeriksiz bir kayıt düşer."""
    event = s.get(Event, event_id)
    if not event or event.company_id != actor.company_id or event.kind not in ("note", "task") or event.deleted_at:
        raise ServiceError("Not bulunamadı.")
    req = s.get(Req, event.req_id) if event.req_id else None
    if not req or req.deleted_at or not pl.can_view_req(actor.id, actor.role, req): raise ServiceError("Not bulunamadı.")
    if event.user_id != actor.id and actor.role not in pl.MANAGE_ROLES:
        raise ServiceError("Bu notu yalnızca yazan kişi ya da yöneticiler silebilir.")
    _mark_deleted(event, actor)
    _log(s, actor, req, "edit", ("Görev" if event.kind == "task" else "Not") + " silindi.")
    s.commit()


@_atomic
def change_req_customer(s, actor: Actor, req: Req, customer_id: int):
    """REQ'i başka müşteriye taşır (yanlış müşteriye açıldıysa). REQ KODU DEĞİŞMEZ — kodu yeni müşterinin önekine çevirmek için
    'REQ no düzelt' kullanılır. Müşteriye giden teklif/teslimat makbuzu varsa değiştirilemez (PDF'lerdeki müşteriyle tutarsız kalırdı)."""
    _require_role(actor, pl.MANAGE_ROLES, "REQ müşterisini değiştirme")
    if not pl.can_view_req(actor.id, actor.role, req): raise ServiceError("Bu REQ üzerinde yetkiniz yok.")
    customer = _get_partner(s, actor, customer_id, deleted=False)
    if not customer.is_customer: raise ServiceError("Geçerli bir müşteri seçin.")
    if customer.id == req.customer_id: return
    if req.quotes or req.deliveries:
        raise ServiceError("Bu REQ için teklif ya da teslimat makbuzu oluşturulmuş; müşteriye giden belgelerle tutarsız kalmaması için müşteri değiştirilemez.")
    old = req.customer.name
    req.customer_id, req.customer = customer.id, customer
    req.updated_at = _now()
    _log(s, actor, req, "edit", f"Müşteri değiştirildi: {old} → {customer.name} (REQ kodu değişmedi: {req.code}).")
    s.commit()


@_atomic
def update_req_meta(s, actor: Actor, req: Req, *, notes: str | None = None, delivery_type: str | None = None):
    """REQ notu ve teslimat tipi HER aşamada düzeltilebilir (normalde yalnızca Talep'te). Teslimat tipi teklif PDF'inde yer aldığı için
    değişirse bir sonraki teklif yeni revizyon (-R2) olur; hesap OTOMATİK değişmez (kullanıcı kuralı)."""
    _require_role(actor, pl.MANAGE_ROLES, "REQ bilgisi düzeltme")
    if not pl.can_view_req(actor.id, actor.role, req): raise ServiceError("Bu REQ üzerinde yetkiniz yok.")
    if req.status != pl.ACTIVE: raise ServiceError("Bu REQ aktif değil.")
    changes = []
    if notes is not None and _text(notes) != req.notes:
        req.notes = _text(notes)
        changes.append("not")
    if delivery_type is not None and delivery_type != req.delivery_type:
        if delivery_type not in pl.DELIVERY_TYPES: raise ServiceError("Geçersiz teslimat tipi.")
        req.delivery_type = delivery_type
        changes.append(f"teslimat tipi={delivery_type}")
    if changes:
        req.updated_at = _now()
        _log(s, actor, req, "edit", "Düzeltildi: " + ", ".join(changes))
    s.commit()
