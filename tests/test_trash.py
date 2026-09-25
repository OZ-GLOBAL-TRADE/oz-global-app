"""Silme (çöp kutusu), geri yükleme, kalıcı silme ve ad/kod/müşteri/not düzeltme kuralları."""
import pytest
from sqlalchemy import select

from conftest import new_req
from jarvis import services as sv
from jarvis.models import Attachment, Event, Partner, Product, Req, ReqLine


def codes(s, actor, **kw):
    return [r.code for r in sv.visible_reqs(s, actor, **kw)]


def to_teklif(s, admin, req):
    """Talep → Teklif (marj girilmiş)."""
    sv.advance_req(s, admin, req)
    sv.save_line_values(s, admin, req, "unit_cost", [{"id": l.id, "value": 10} for l in req.lines])
    sv.advance_req(s, admin, req)
    sv.save_line_values(s, admin, req, "unit_customs", [{"id": l.id, "value": 0} for l in req.lines])
    sv.advance_req(s, admin, req)
    sv.update_fields(s, admin, req, margin_pct=20.0)


# ---------------------------------------------------------------- REQ

def test_deleted_req_disappears_everywhere_and_can_be_restored(s, world):
    admin, eren = world["admin"], world["eren"]
    req = new_req(s, world, "eren")
    sv.add_note(s, eren, req, "gizlenecek görev", assignee_id=eren.id)
    assert len(sv.list_my_open_tasks(s, eren)) == 1

    sv.delete_req(s, eren, req)  # yönetici roller silebilir
    assert req.code not in codes(s, admin) and req.code not in codes(s, admin, status="aktif")
    with pytest.raises(sv.ServiceError, match="bulunamadı"):
        sv.get_req(s, admin, code=req.code)
    assert sv.list_my_open_tasks(s, eren) == []  # silinmiş REQ'in görevi bildirimde görünmez
    assert [r.code for r in sv.list_deleted_reqs(s, admin)] == [req.code]

    trashed = sv.get_req(s, admin, code=req.code, include_deleted=True)
    assert trashed.deleted_by == eren.id and trashed.deleted_at is not None
    sv.restore_req(s, admin, trashed)
    assert req.code in codes(s, admin) and sv.list_deleted_reqs(s, admin) == [] and len(sv.list_my_open_tasks(s, eren)) == 1


def test_delete_and_trash_permissions(s, world):
    admin, eren, broker = world["admin"], world["eren"], world["broker"]
    req = new_req(s, world, "eren")
    with pytest.raises(sv.ServiceError, match="yetkiniz yok"):
        sv.delete_req(s, broker, req)
    with pytest.raises(sv.ServiceError, match="yetkiniz yok"):
        sv.list_deleted_reqs(s, broker)
    sv.delete_req(s, eren, req)
    with pytest.raises(sv.ServiceError):
        sv.get_req(s, broker, code=req.code, include_deleted=True)  # gümrükçü çöp kutusuna erişemez
    with pytest.raises(sv.ServiceError, match="zaten silinmiş"):
        sv.delete_req(s, admin, sv.get_req(s, admin, code=req.code, include_deleted=True))


def test_req_linked_to_shipment_cannot_be_deleted(s, world):
    admin = world["admin"]
    req = new_req(s, world, "eren")
    sv.add_shipment_item(s, admin, sv.create_shipment(s, admin), req.lines[0].id, 2)
    with pytest.raises(sv.ServiceError, match="kargoya bağlı"):
        sv.delete_req(s, admin, req)
    assert req.code in codes(s, admin)


def test_purge_req_admin_only_typed_confirmation_and_really_deletes(s, world):
    admin, eren = world["admin"], world["eren"]
    req = new_req(s, world, "eren")
    sv.add_note(s, eren, req, "not")
    sv.upload_req_attachment(s, eren, req, "a.txt", "text/plain", b"x")
    req_id, code = req.id, req.code

    with pytest.raises(sv.ServiceError, match="Önce REQ"):
        sv.purge_req(s, admin, req, code)  # çöp kutusunda değil
    sv.delete_req(s, eren, req)
    trashed = sv.get_req(s, admin, code=code, include_deleted=True)
    with pytest.raises(sv.ServiceError, match="yetkiniz yok"):
        sv.purge_req(s, eren, trashed, code)  # yönetici rolü kalıcı silemez, yalnızca ADMIN
    with pytest.raises(sv.ServiceError, match="aynen yazın"):
        sv.purge_req(s, admin, trashed, "yanlis")
    assert s.get(Req, req_id) is not None  # başarısız denemeler bir şey silmedi

    sv.purge_req(s, admin, trashed, code)
    assert s.get(Req, req_id) is None
    assert not s.scalars(select(ReqLine).where(ReqLine.req_id == req_id)).all()
    assert not s.scalars(select(Event).where(Event.req_id == req_id)).all()
    assert not s.scalars(select(Attachment).where(Attachment.req_id == req_id)).all()


# ---------------------------------------------------------------- müşteri / tedarikçi

def test_deleted_customer_is_hidden_blocks_new_reqs_and_name_reuse_until_restored(s, world):
    admin, cust = world["admin"], world["cust"]
    req = new_req(s, world, "eren")
    sv.delete_partner(s, admin, cust.id)
    assert cust.id not in [p.id for p in sv.list_partners(s, admin, customers=True)]
    assert [p.id for p in sv.list_partners(s, admin, deleted=True)] == [cust.id]
    with pytest.raises(sv.ServiceError, match="Geçerli bir müşteri"):
        new_req(s, world, "eren")  # silinmiş müşteriye yeni REQ açılamaz
    assert req.code in codes(s, admin)  # mevcut REQ'ler kalır (adı da)
    with pytest.raises(sv.ServiceError, match="silinenler arasında"):
        sv.add_partner(s, admin, name="titra teknoloji", is_customer=True)  # aynı ad, yenisini eklemek yerine geri yükle
    sv.restore_partner(s, admin, cust.id)
    assert new_req(s, world, "eren").code.endswith("_18")


def test_purge_customer_blocked_while_reqs_exist_supplier_purge_clears_references(s, world):
    admin, cust = world["admin"], world["cust"]
    req = new_req(s, world, "eren")
    supplier = sv.add_partner(s, admin, name="Tedarik Ltd", is_supplier=True)
    sv.add_product(s, admin, name="Kabloluk", default_supplier_id=supplier.id)
    sv.advance_req(s, admin, req)
    sv.save_line_suppliers(s, admin, req, [{"id": req.lines[0].id, "supplier_id": supplier.id}])

    sv.delete_partner(s, admin, cust.id)
    with pytest.raises(sv.ServiceError, match="REQ var"):
        sv.purge_partner(s, admin, cust.id, cust.name)
    usage = sv.partner_usage(s, admin)
    assert usage[supplier.id] == {"lines": 1, "products": 1}

    sv.delete_partner(s, admin, supplier.id)
    with pytest.raises(sv.ServiceError, match="aynen yazın"):
        sv.purge_partner(s, admin, supplier.id, "yanlış")
    with pytest.raises(sv.ServiceError, match="yetkiniz yok"):
        sv.purge_partner(s, world["eren"], supplier.id, supplier.name)
    sv.purge_partner(s, admin, supplier.id, supplier.name)
    assert s.get(Partner, supplier.id) is None
    s.refresh(req.lines[0])
    assert req.lines[0].supplier_id is None  # satır kaldı, tedarikçi bağlantısı boşaltıldı
    assert s.scalar(select(Product).where(Product.name == "Kabloluk")).default_supplier_id is None


def test_deleted_supplier_cannot_be_picked_but_existing_pick_survives(s, world):
    admin = world["admin"]
    req = new_req(s, world, "eren")
    sup = sv.add_partner(s, admin, name="Eski Tedarikçi", is_supplier=True)
    sv.save_line_suppliers(s, admin, req, [{"id": req.lines[0].id, "supplier_id": sup.id}])
    sv.delete_partner(s, admin, sup.id)
    with pytest.raises(sv.ServiceError, match="Geçersiz tedarikçi"):
        sv.set_line_supplier(s, admin, req, req.lines[1].id, sup.id)
    sv.save_line_suppliers(s, admin, req, [{"id": req.lines[0].id, "supplier_id": sup.id}])  # değişmeyen mevcut seçim hata vermez
    assert req.lines[0].supplier_id == sup.id


# ---------------------------------------------------------------- ürün

def test_deleted_product_leaves_existing_lines_intact_and_cannot_be_newly_added(s, world):
    admin = world["admin"]
    req = new_req(s, world, "eren")          # ESC ve Motor satırları
    esc = world["prods"][0]
    sv.delete_product(s, admin, esc.id)
    assert esc.id not in [p.id for p in sv.list_products(s, admin)] and [p.id for p in sv.list_products(s, admin, deleted=True)] == [esc.id]

    # Talep kaydedilirken mevcut (silinmiş ürünlü) satır düşmemeli; adedi güncellenebilir
    rows = [{"id": l.id, "product_id": l.product_id, "qty": 7 if l.name == "ESC" else l.qty} for l in req.lines]
    sv.save_items(s, admin, req, rows)
    assert [(l.name, l.qty) for l in req.lines] == [("ESC", 7.0), ("Motor", 6.0)]
    with pytest.raises(sv.ServiceError, match="Geçersiz ürün"):
        sv.create_req(s, admin, customer_id=world["cust"].id, items=[(esc.id, 1)])
    sv.restore_product(s, admin, esc.id)
    assert esc.id in [p.id for p in sv.list_products(s, admin)]


def test_purged_product_keeps_line_name_and_line_survives_talep_save(s, world):
    admin = world["admin"]
    req = new_req(s, world, "eren")
    esc = world["prods"][0]
    assert sv.product_usage(s, admin)[esc.id] == 1
    sv.delete_product(s, admin, esc.id)
    with pytest.raises(sv.ServiceError, match="aynen yazın"):
        sv.purge_product(s, admin, esc.id, "esc")  # ad tam eşleşmeli
    sv.purge_product(s, admin, esc.id, "ESC")
    assert s.get(Product, esc.id) is None
    line = next(l for l in req.lines if l.name == "ESC")
    s.refresh(line)
    assert line.product_id is None and line.name == "ESC"  # ad kopyası korunur

    # ürünü olmayan satırı Talep formu ürün_id=None ile geri gönderir: satır düşmemeli, yalnızca adet güncellenmeli
    sv.save_items(s, admin, req, [{"id": l.id, "product_id": l.product_id, "qty": 3 if l.name == "ESC" else l.qty} for l in req.lines])
    assert [(l.name, l.qty) for l in req.lines] == [("ESC", 3.0), ("Motor", 6.0)]


def test_rename_partner_and_product_rules(s, world):
    admin, eren = world["admin"], world["eren"]
    other = sv.add_partner(s, admin, name="Başka Firma", is_customer=True)
    with pytest.raises(sv.ServiceError, match="zaten kayıtlı"):
        sv.rename_partner(s, admin, other.id, "  titra   teknoloji ")  # boşluk/büyük-küçük/Türkçe harf farkı yok sayılır
    with pytest.raises(sv.ServiceError, match="boş"):
        sv.rename_partner(s, admin, other.id, "   ")
    with pytest.raises(sv.ServiceError, match="yetkiniz yok"):
        sv.rename_partner(s, world["broker"], other.id, "Yeni Ad")
    assert sv.rename_partner(s, admin, other.id, "Yeni  Ad  Ltd").name == "Yeni Ad Ltd"
    assert sv.rename_partner(s, admin, other.id, "yeni ad ltd").name == "yeni ad ltd"  # kaydın KENDİ adının büyük/küçük harf değişimi çakışma sayılmaz
    esc = world["prods"][0]
    with pytest.raises(sv.ServiceError, match="kataloğda var"):
        sv.rename_product(s, admin, esc.id, "motor")
    assert sv.rename_product(s, eren, esc.id, "ESC Pro").name == "ESC Pro"


def test_change_short_code_only_affects_new_reqs_and_rejects_clashes(s, world):
    admin, cust = world["admin"], world["cust"]
    old = new_req(s, world, "eren")                      # TTRA_REQ_17
    other = sv.add_partner(s, admin, name="Diğer Müşteri", is_customer=True, short_code="DGR")
    with pytest.raises(sv.ServiceError, match="başka bir müşteride"):
        sv.change_short_code(s, admin, other.id, "ttra")
    with pytest.raises(sv.ServiceError, match="en az 2"):
        sv.change_short_code(s, admin, other.id, "x")
    with pytest.raises(sv.ServiceError, match="yalnızca müşteriler"):
        sv.change_short_code(s, admin, sv.add_partner(s, admin, name="Tedarik", is_supplier=True).id, "ABC")

    sv.change_short_code(s, admin, cust.id, "titr")      # küçük harf/Türkçe girdi normalleşir
    assert cust.short_code == "TITR" and old.code == "TTRA_REQ_17"  # mevcut REQ kodu değişmedi
    assert new_req(s, world, "eren").code == "TITR_REQ_18"  # sayaç kaldığı yerden, yeni önekle

    # eski önek (TTRA) artık serbest ama o önekle başlayan REQ başka müşteriye ait → başka müşteriye verilemez
    with pytest.raises(sv.ServiceError, match="başka bir müşteriye ait"):
        sv.change_short_code(s, admin, other.id, "TTRA")


# ---------------------------------------------------------------- REQ müşterisi / not / teslimat tipi

def test_change_req_customer_keeps_code_and_is_blocked_after_documents_exist(s, world):
    admin, eren = world["admin"], world["eren"]
    new_customer = sv.add_partner(s, admin, name="Yeni Müşteri", is_customer=True, short_code="YNMS")
    supplier = sv.add_partner(s, admin, name="Sadece Tedarikçi", is_supplier=True)
    req = new_req(s, world, "eren")
    code = req.code

    with pytest.raises(sv.ServiceError, match="Geçerli bir müşteri"):
        sv.change_req_customer(s, eren, req, supplier.id)  # müşteri olmayan
    with pytest.raises(sv.ServiceError, match="yetkiniz yok"):
        sv.change_req_customer(s, world["broker"], req, new_customer.id)
    sv.change_req_customer(s, eren, req, new_customer.id)
    assert req.customer.name == "Yeni Müşteri" and req.code == code
    assert "REQ kodu değişmedi" in sv.list_events(s, req.id)[0].message

    sv.delete_partner(s, admin, new_customer.id)
    with pytest.raises(sv.ServiceError, match="bulunamadı"):
        sv.change_req_customer(s, eren, req, new_customer.id)  # silinmiş müşteriye taşınamaz

    # teklif PDF'i çıktıktan sonra müşteri değiştirilemez
    req2 = new_req(s, world, "eren")
    to_teklif(s, admin, req2)
    sv.issue_quote(s, admin, req2)
    another = sv.add_partner(s, admin, name="Bir Başkası", is_customer=True)
    with pytest.raises(sv.ServiceError, match="teklif ya da teslimat"):
        sv.change_req_customer(s, admin, req2, another.id)
    assert req2.customer.name == "TİTRA TEKNOLOJİ"  # reddedilen işlem müşteriyi değiştirmedi


def test_update_req_meta_any_stage_but_only_for_active_reqs(s, world):
    admin, eren = world["admin"], world["eren"]
    req = new_req(s, world, "eren")
    to_teklif(s, admin, req)
    assert req.stage == "teklif"
    sv.update_req_meta(s, eren, req, notes="  Müşteri notu ", delivery_type="Kapı Teslim")  # Talep dışındaki aşamada
    assert req.notes == "Müşteri notu" and req.delivery_type == "Kapı Teslim"
    assert sv.list_events(s, req.id)[0].message.startswith("Düzeltildi:")
    with pytest.raises(sv.ServiceError, match="Geçersiz teslimat"):
        sv.update_req_meta(s, eren, req, delivery_type="Uzay Teslim")
    with pytest.raises(sv.ServiceError, match="yetkiniz yok"):
        sv.update_req_meta(s, world["broker"], req, notes="x")
    sv.shelve_req(s, admin, req, "Bütçe yok")
    with pytest.raises(sv.ServiceError, match="aktif değil"):
        sv.update_req_meta(s, admin, req, notes="y")


# ---------------------------------------------------------------- not / görev silme

def test_delete_note_author_or_manager_only_and_hidden_from_history_but_logged(s, world):
    admin, eren, beyza, broker = world["admin"], world["eren"], world["beyza"], world["broker"]
    req = new_req(s, world, "eren")
    sv.add_note(s, eren, req, "Erenin notu")
    sv.add_note(s, admin, req, "Gizli görev", assignee_id=eren.id)
    note = next(e for e in sv.list_events(s, req.id) if e.message == "Erenin notu")
    task = next(e for e in sv.list_events(s, req.id) if e.message == "Gizli görev")

    sv.delete_note(s, beyza, note.id)      # başka bir yönetici de silebilir (yönetici rolü)
    messages = [e.message for e in sv.list_events(s, req.id)]
    assert "Erenin notu" not in messages and "Not silindi." in messages  # içerik gizli, silindiği kayıtlı
    with pytest.raises(sv.ServiceError, match="bulunamadı"):
        sv.delete_note(s, eren, note.id)   # zaten silinmiş

    assert len(sv.list_my_open_tasks(s, eren)) == 1
    sv.delete_note(s, admin, task.id)
    assert sv.list_my_open_tasks(s, eren) == []
    with pytest.raises(sv.ServiceError, match="Görev bulunamadı"):
        sv.complete_task(s, eren, task.id)  # silinmiş göreve işlem yapılamaz
    with pytest.raises(sv.ServiceError, match="bulunamadı"):
        sv.delete_note(s, broker, sv.list_events(s, req.id)[0].id)  # sistem kaydı not/görev değil
