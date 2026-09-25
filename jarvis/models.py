from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (Boolean, DateTime, Float, ForeignKey, Index, Integer, LargeBinary, String, Text,
                        UniqueConstraint, text, true)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Company(Base):
    __tablename__ = "companies"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    # Teklif PDF başlığı ve numaralandırma (Ayarlar sayfasından düzenlenir)
    legal_name: Mapped[str] = mapped_column(String(300), default="", server_default=text("''"))
    address: Mapped[str] = mapped_column(Text, default="", server_default=text("''"))
    tax_info: Mapped[str] = mapped_column(String(200), default="", server_default=text("''"))
    phone: Mapped[str] = mapped_column(String(50), default="", server_default=text("''"))
    email: Mapped[str] = mapped_column(String(200), default="", server_default=text("''"))
    website: Mapped[str] = mapped_column(String(200), default="", server_default=text("''"))
    bank_info: Mapped[str] = mapped_column(Text, default="", server_default=text("''"))
    quote_prefix: Mapped[str] = mapped_column(String(10), default="OZ", server_default=text("'OZ'"))
    quote_seq: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))  # son kullanılan teklif sıra no
    # Satın alma siparişi (bize -> tedarikçiye) numaralandırma
    po_prefix: Mapped[str] = mapped_column(String(10), default="P", server_default=text("'P'"))
    po_seq: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    # Kargo (CRG) numaralandırma
    shipment_prefix: Mapped[str] = mapped_column(String(10), default="CRG", server_default=text("'CRG'"))
    shipment_seq: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    # Teslimat makbuzu (OUT/NNNN) numaralandırma
    delivery_prefix: Mapped[str] = mapped_column(String(10), default="OUT", server_default=text("'OUT'"))
    delivery_seq: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    username: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(30))
    # Tedarikçi ağı için: hesap bir tedarikçi kaydına bağlanır ve yalnızca kendi teklif taleplerini görür.
    partner_id: Mapped[Optional[int]] = mapped_column(ForeignKey("partners.id"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # bcrypt hash'i; bos ise sifre henuz belirlenmemistir (giris reddedilir, admin Ayarlar'dan belirlemeli).
    password_hash: Mapped[str] = mapped_column(String(200), default="", server_default=text("''"))


class SoftDeleteMixin:
    """Çöp kutusu: silinen kayıt veritabanında kalır (geri yüklenebilir), servislerdeki listelerden/aramalardan çıkar.
    `deleted_by` bilinçli olarak yabancı anahtarsız düz bir tamsayıdır (kullanıcı silinse bile kayıt bozulmasın)."""
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[Optional[int]] = mapped_column(Integer)

class Partner(SoftDeleteMixin, Base):
    """Müşteri ve tedarikçi tek tabloda; aynı firma iki rolde de olabilir."""
    __tablename__ = "partners"
    __table_args__ = (UniqueConstraint("company_id", "short_code"), UniqueConstraint("company_id", "name"))
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    name: Mapped[str] = mapped_column(String(200))
    short_code: Mapped[Optional[str]] = mapped_column(String(20))
    is_customer: Mapped[bool] = mapped_column(Boolean, default=False)
    is_supplier: Mapped[bool] = mapped_column(Boolean, default=False)
    kind: Mapped[str] = mapped_column(String(50), default="")
    country: Mapped[str] = mapped_column(String(100), default="")
    tax_no: Mapped[str] = mapped_column(String(50), default="")
    address: Mapped[str] = mapped_column(Text, default="")
    email: Mapped[str] = mapped_column(String(200), default="")
    phone: Mapped[str] = mapped_column(String(50), default="")
    category: Mapped[str] = mapped_column(String(100), default="")
    keywords: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    req_seq: Mapped[int] = mapped_column(Integer, default=0)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Product(SoftDeleteMixin, Base):
    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("company_id", "name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    name: Mapped[str] = mapped_column(String(300))
    category: Mapped[str] = mapped_column(String(100), default="")
    spec: Mapped[str] = mapped_column(Text, default="")
    hs_code: Mapped[str] = mapped_column(String(30), default="")
    default_supplier_id: Mapped[Optional[int]] = mapped_column(ForeignKey("partners.id"))
    last_cost: Mapped[Optional[float]] = mapped_column(Float)
    notes: Mapped[str] = mapped_column(Text, default="")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Req(SoftDeleteMixin, Base):
    __tablename__ = "reqs"
    __table_args__ = (UniqueConstraint("company_id", "code"), Index("ix_reqs_stage", "company_id", "stage"))
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    code: Mapped[str] = mapped_column(String(50))
    customer_id: Mapped[int] = mapped_column(ForeignKey("partners.id"))
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    stage: Mapped[str] = mapped_column(String(20), default="talep")
    status: Mapped[str] = mapped_column(String(20), default="aktif")  # aktif | tamamlandi | rafa
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    delivery_type: Mapped[str] = mapped_column(String(20), default="Gümrük Teslim", server_default=text("'Gümrük Teslim'"))
    margin_pct: Mapped[Optional[float]] = mapped_column(Float)  # varsayılan kâr marjı (maliyet üzerine, markup); satır bazlı override edilebilir
    logistics_margin_pct: Mapped[Optional[float]] = mapped_column(Float)  # lojistik "ayrı kalem" iken kullanılan marj; boş = margin_pct
    tax_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())  # bazı tekliflerde KDV yok
    tax_pct: Mapped[float] = mapped_column(Float, default=20.0)
    logistics_mode: Mapped[str] = mapped_column(String(10), default="dahil", server_default=text("'dahil'"))  # dahil | ayri
    valid_days: Mapped[int] = mapped_column(Integer, default=30)
    payment_terms: Mapped[str] = mapped_column(Text, default="")
    quote_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    decision: Mapped[Optional[str]] = mapped_column(String(10))  # onay | ret
    shelved_reason: Mapped[str] = mapped_column(Text, default="")
    po_approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    po_number: Mapped[Optional[str]] = mapped_column(String(60))  # bizim tedarikçiye açtığımız PO no (otomatik)
    customer_po_no: Mapped[str] = mapped_column(String(100), default="")  # müşterinin kendi sipariş referansı (manuel)
    notes: Mapped[str] = mapped_column(Text, default="")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    customer: Mapped[Partner] = relationship()
    owner: Mapped[User] = relationship()
    lines: Mapped[list["ReqLine"]] = relationship(back_populates="req", cascade="all, delete-orphan", order_by="ReqLine.position, ReqLine.id")
    costs: Mapped[list["ReqCost"]] = relationship(back_populates="req", cascade="all, delete-orphan", order_by="ReqCost.id")
    events: Mapped[list["Event"]] = relationship(back_populates="req", cascade="all, delete-orphan", order_by="Event.id")
    quotes: Mapped[list["QuoteDoc"]] = relationship(back_populates="req", cascade="all, delete-orphan", order_by="QuoteDoc.version")
    deliveries: Mapped[list["DeliveryDoc"]] = relationship(back_populates="req", cascade="all, delete-orphan", order_by="DeliveryDoc.id")
    attachments: Mapped[list["Attachment"]] = relationship(back_populates="req", cascade="all, delete-orphan", order_by="Attachment.id")


class ReqLine(Base):
    __tablename__ = "req_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    req_id: Mapped[int] = mapped_column(ForeignKey("reqs.id", ondelete="CASCADE"))
    product_id: Mapped[Optional[int]] = mapped_column(ForeignKey("products.id"))
    name: Mapped[str] = mapped_column(String(300))  # ürün adının kopyası; katalog değişse de REQ bozulmaz
    qty: Mapped[float] = mapped_column(Float, default=1)
    unit_cost: Mapped[Optional[float]] = mapped_column(Float)  # None = henüz girilmedi
    unit_customs: Mapped[Optional[float]] = mapped_column(Float)  # birim gümrük; None = girilmedi (0 = yok)
    unit_logistics: Mapped[Optional[float]] = mapped_column(Float)  # birim lojistik; boş = 0
    margin_pct: Mapped[Optional[float]] = mapped_column(Float)  # satıra özel kâr marjı; boş = REQ'nin varsayılan marjı
    sale_price_override: Mapped[Optional[float]] = mapped_column(Float)  # doğrudan girilen birim satış fiyatı; doluysa marj yok sayılır
    supplier_id: Mapped[Optional[int]] = mapped_column(ForeignKey("partners.id"))  # Talep/Fiyat aşamasında seçilen tedarikçi
    position: Mapped[int] = mapped_column(Integer, default=0)

    req: Mapped[Req] = relationship(back_populates="lines")
    product: Mapped[Optional[Product]] = relationship()
    supplier: Mapped[Optional[Partner]] = relationship(foreign_keys=[supplier_id])


class ReqCost(Base):
    """Ürüne bağlı olmayan ekstra masraflar (genel lojistik, ekspertiz vb.)."""
    __tablename__ = "req_costs"
    id: Mapped[int] = mapped_column(primary_key=True)
    req_id: Mapped[int] = mapped_column(ForeignKey("reqs.id", ondelete="CASCADE"))
    label: Mapped[str] = mapped_column(String(200))
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    kind: Mapped[str] = mapped_column(String(10), default="diger", server_default=text("'diger'"))  # gumruk | lojistik | diger

    req: Mapped[Req] = relationship(back_populates="costs")


class Event(SoftDeleteMixin, Base):
    """Odoo'daki chatter'ın karşılığı: aşama geçişleri, düzenlemeler, notlar ve görevler."""
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    req_id: Mapped[Optional[int]] = mapped_column(ForeignKey("reqs.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(20))  # create | stage | edit | note | status | task
    stage: Mapped[Optional[str]] = mapped_column(String(20))  # olayın yazıldığı aşama; yetkisiz roller için filtreleme
    message: Mapped[str] = mapped_column(Text, default="")
    from_stage: Mapped[Optional[str]] = mapped_column(String(20))
    to_stage: Mapped[Optional[str]] = mapped_column(String(20))
    # kind="task" iken doludur: göreve atanan kullanıcı. done_at/cancelled_at'ten en fazla biri dolu olabilir
    # (ikisi de boş = hâlâ açık); done_at = tamamlandı, cancelled_at = iptal edildi.
    assignee_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    done_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    req: Mapped[Optional[Req]] = relationship(back_populates="events")
    user: Mapped[Optional[User]] = relationship(foreign_keys=[user_id])
    assignee: Mapped[Optional[User]] = relationship(foreign_keys=[assignee_id])


class QuoteDoc(Base):
    """Müşteriye giden numaralı teklif. İçerik oluşturulduğu andaki halidir (snapshot); sonradan REQ değişse de PDF aynı kalır.
    Aynı REQ için içerik değişince yeni revizyon (versiyon) açılır."""
    __tablename__ = "quotes"
    __table_args__ = (UniqueConstraint("company_id", "number"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    req_id: Mapped[int] = mapped_column(ForeignKey("reqs.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    number: Mapped[str] = mapped_column(String(60))
    fingerprint: Mapped[str] = mapped_column(String(64))  # müşteriye görünen içeriğin özeti; değişince yeni revizyon
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    issued_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    currency: Mapped[str] = mapped_column(String(3))
    total: Mapped[float] = mapped_column(Float)
    grand_total: Mapped[float] = mapped_column(Float)
    snapshot: Mapped[str] = mapped_column(Text)  # JSON: satırlar, toplamlar, müşteri ve şirket bilgisi (maliyet/kâr YOK)

    req: Mapped[Req] = relationship(back_populates="quotes")


class DeliveryDoc(Base):
    """Teslimat makbuzu (OUT/NNNN). Bir REQ birden fazla kısmi (ön) teslimat alabilir; içerik oluşturulduğu andaki
    halin anlık görüntüsüdür (snapshot). Tüm satırlar tam teslim edilene kadar REQ 'teslim' aşamasında kalır."""
    __tablename__ = "deliveries"
    __table_args__ = (UniqueConstraint("company_id", "number"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    req_id: Mapped[int] = mapped_column(ForeignKey("reqs.id", ondelete="CASCADE"), index=True)
    number: Mapped[str] = mapped_column(String(60))
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    issued_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    delivered_by: Mapped[str] = mapped_column(String(200), default="", server_default=text("''"))  # "Teslim Eden"
    delivered_to: Mapped[str] = mapped_column(String(200), default="", server_default=text("''"))  # "Teslim Alan"
    snapshot: Mapped[str] = mapped_column(Text)  # JSON: satırlar (sipariş edilen / bu teslimatta), müşteri & şirket bilgisi

    req: Mapped[Req] = relationship(back_populates="deliveries")
    lines: Mapped[list["DeliveryLine"]] = relationship(back_populates="delivery", cascade="all, delete-orphan", order_by="DeliveryLine.id")


class DeliveryLine(Base):
    __tablename__ = "delivery_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    delivery_id: Mapped[int] = mapped_column(ForeignKey("deliveries.id", ondelete="CASCADE"))
    req_line_id: Mapped[int] = mapped_column(ForeignKey("req_lines.id", ondelete="CASCADE"))
    qty: Mapped[float] = mapped_column(Float)  # bu teslimattaki adet

    delivery: Mapped[DeliveryDoc] = relationship(back_populates="lines")
    req_line: Mapped[ReqLine] = relationship()


class Shipment(Base):
    """Kargo/CRG kaydı. Tek bir CRG'de birden fazla REQ'in farklı ürünlerinden gelebilir (bkz. ShipmentItem);
    REQ'lerin kendi Golden Thread aşama akışından tamamen bağımsızdır — yalnızca operasyonel takip amaçlıdır."""
    __tablename__ = "shipments"
    __table_args__ = (UniqueConstraint("company_id", "code"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    code: Mapped[str] = mapped_column(String(30))  # CRG_NN
    awb_no: Mapped[str] = mapped_column(String(60), default="", server_default=text("''"))
    carrier: Mapped[str] = mapped_column(String(60), default="", server_default=text("''"))
    departure_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    logistics_status: Mapped[str] = mapped_column(String(60), default="Çıkış Hazırlığında", server_default=text("'Çıkış Hazırlığında'"))
    customs_status: Mapped[str] = mapped_column(String(60), default="Bekliyor", server_default=text("'Bekliyor'"))
    gcb_no: Mapped[str] = mapped_column(String(60), default="", server_default=text("''"))
    delivery_type: Mapped[str] = mapped_column(String(20), default="Belirtilmedi", server_default=text("'Belirtilmedi'"))
    delivery_address: Mapped[str] = mapped_column(Text, default="", server_default=text("''"))
    current_location: Mapped[str] = mapped_column(String(200), default="", server_default=text("''"))
    notes: Mapped[str] = mapped_column(Text, default="", server_default=text("''"))
    last_tracked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))  # otomatik konum çekmenin son çalıştığı an
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    items: Mapped[list["ShipmentItem"]] = relationship(back_populates="shipment", cascade="all, delete-orphan", order_by="ShipmentItem.id")
    attachments: Mapped[list["Attachment"]] = relationship(back_populates="shipment", cascade="all, delete-orphan", order_by="Attachment.id")


class ShipmentItem(Base):
    """Bir kargoya eklenen, bir REQ satırından belirli bir adet. Aynı REQ satırı birden fazla kargoya bölünerek eklenebilir;
    kalan (henüz kargoya eklenmemiş) adet REQ satırının qty'sinden bu tablodaki toplamın çıkarılmasıyla hesaplanır."""
    __tablename__ = "shipment_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    shipment_id: Mapped[int] = mapped_column(ForeignKey("shipments.id", ondelete="CASCADE"))
    req_line_id: Mapped[int] = mapped_column(ForeignKey("req_lines.id", ondelete="CASCADE"))
    req_id: Mapped[int] = mapped_column(ForeignKey("reqs.id", ondelete="CASCADE"))  # sorguları basitleştirmek için tekrar tutulur
    qty: Mapped[float] = mapped_column(Float)

    shipment: Mapped[Shipment] = relationship(back_populates="items")
    req_line: Mapped[ReqLine] = relationship()
    req: Mapped[Req] = relationship()


class Attachment(Base):
    """Kargo belgeleri (AWB, Packing List, Proforma Invoice, diğer) VEYA bir REQ'e eklenen dosyalar (ürün PDF'i,
    Excel vb. — bkz. talepler.py'deki Notlar & Görevler paneli). Tam olarak biri dolu olmalı: shipment_id ya da
    req_id. Dosya küçük olduğu için doğrudan veritabanında tutulur."""
    __tablename__ = "attachments"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    shipment_id: Mapped[Optional[int]] = mapped_column(ForeignKey("shipments.id", ondelete="CASCADE"), index=True)
    req_id: Mapped[Optional[int]] = mapped_column(ForeignKey("reqs.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="diger", server_default=text("'diger'"))  # awb | packing_list | proforma_invoice | diger
    filename: Mapped[str] = mapped_column(String(300))
    content_type: Mapped[str] = mapped_column(String(120), default="", server_default=text("''"))
    size: Mapped[int] = mapped_column(Integer, default=0)
    data: Mapped[bytes] = mapped_column(LargeBinary)
    uploaded_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    shipment: Mapped[Optional[Shipment]] = relationship(back_populates="attachments")
    req: Mapped[Optional[Req]] = relationship(back_populates="attachments")
