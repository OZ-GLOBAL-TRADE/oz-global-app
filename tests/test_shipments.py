import pytest

from conftest import new_req
from jarvis import pipeline as pl, services as sv


def test_shipment_code_sequence_and_carrier_detection(s, world):
    admin = world["admin"]
    sh1 = sv.create_shipment(s, admin, awb_no="23512345678", carrier=pl.detect_carrier("23512345678"))
    sh2 = sv.create_shipment(s, admin)
    assert sh1.code == "CRG_01" and sh2.code == "CRG_02"
    assert sh1.carrier == "Turkish Cargo"  # 235 ile başlayan 11 haneli AWB
    assert pl.detect_carrier("1Z9999999999999999") == "UPS"
    assert pl.detect_carrier("") == "Bilinmiyor"


def test_add_items_from_two_different_reqs_into_one_shipment(s, world):
    admin, eren, beyza = world["admin"], world["eren"], world["beyza"]
    req_a = new_req(s, world, "eren")   # 10 ESC, 6 Motor
    req_b = new_req(s, world, "beyza")  # 10 ESC, 6 Motor
    shipment = sv.create_shipment(s, admin)

    sv.add_shipment_item(s, admin, shipment, req_a.lines[0].id, 4)   # AA_REQ'in 10 ESC'inden 4'ü
    sv.add_shipment_item(s, admin, shipment, req_b.lines[1].id, 2)   # BB_REQ'in 6 Motor'undan 2'si
    shipment = sv.get_shipment(s, admin, shipment_id=shipment.id)
    assert {(it.req.code, it.req_line.name, it.qty) for it in shipment.items} == {(req_a.code, "ESC", 4.0), (req_b.code, "Motor", 2.0)}

    # REQ'lerin kendi pipeline'ı bozulmadı: hâlâ 'talep' aşamasında, satır adetleri değişmedi.
    req_a_reloaded = sv.get_req(s, eren, req_id=req_a.id)
    assert req_a_reloaded.stage == "talep" and req_a_reloaded.lines[0].qty == 10.0
    assert [sh.code for sh in sv.req_shipments(s, admin, req_a_reloaded)] == [shipment.code]


def test_cannot_over_allocate_shipment_item(s, world):
    """add_shipment_item bir satırın bu kargodaki adedini MUTLAK olarak belirler (eklemez, üzerine yazar);
    sınır her zaman REQ'deki toplam adet eksi DİĞER kargolara ayrılmış miktardır."""
    admin = world["admin"]
    req = new_req(s, world, "eren")  # ESC qty=10
    sh1, sh2 = sv.create_shipment(s, admin), sv.create_shipment(s, admin)
    sv.add_shipment_item(s, admin, sh1, req.lines[0].id, 6)
    with pytest.raises(sv.ServiceError, match="en fazla"):
        sv.add_shipment_item(s, admin, sh2, req.lines[0].id, 5)  # sh1 6 aldı, boşta kalan yalnızca 4
    sv.add_shipment_item(s, admin, sh2, req.lines[0].id, 4)  # tam kalanı: sorunsuz

    sv.add_shipment_item(s, admin, sh1, req.lines[0].id, 2)  # kendi kargosunu 6'dan 2'ye düşürmek: kalan artık 10-2-4=4
    assert sv.get_shipment(s, admin, shipment_id=sh1.id).items[0].qty == 2.0
    sv.add_shipment_item(s, admin, sh1, req.lines[0].id, 6)  # kendi payı + boşta kalan (2+4=6) sınırında: sorunsuz
    with pytest.raises(sv.ServiceError, match="en fazla"):
        sv.add_shipment_item(s, admin, sh1, req.lines[0].id, 7)  # 4 (sh2'de) + 6 talep = 10'u aşar


def test_remove_shipment_item_frees_up_capacity(s, world):
    admin = world["admin"]
    req = new_req(s, world, "eren")
    shipment = sv.create_shipment(s, admin)
    sv.add_shipment_item(s, admin, shipment, req.lines[0].id, 10)
    item_id = sv.get_shipment(s, admin, shipment_id=shipment.id).items[0].id
    sv.remove_shipment_item(s, admin, shipment, item_id)
    assert sv.get_shipment(s, admin, shipment_id=shipment.id).items == []
    sv.add_shipment_item(s, admin, shipment, req.lines[0].id, 10)  # tekrar tam kapasiteyle eklenebiliyor


def test_shipment_visibility_by_role(s, world):
    admin, eren, beyza, broker = world["admin"], world["eren"], world["beyza"], world["broker"]
    req_e, req_b = new_req(s, world, "eren"), new_req(s, world, "beyza")
    sh_e, sh_b = sv.create_shipment(s, admin), sv.create_shipment(s, admin)
    sv.add_shipment_item(s, admin, sh_e, req_e.lines[0].id, 1)
    sv.add_shipment_item(s, admin, sh_b, req_b.lines[0].id, 1)

    assert {sh.code for sh in sv.list_shipments(s, admin)} == {sh_e.code, sh_b.code}
    assert {sh.code for sh in sv.list_shipments(s, broker)} == {sh_e.code, sh_b.code}
    assert {sh.code for sh in sv.list_shipments(s, eren)} == {sh_e.code}
    with pytest.raises(sv.ServiceError, match="yetkiniz"):
        sv.get_shipment(s, eren, code=sh_b.code)


def test_update_shipment_validates_status_values(s, world):
    admin = world["admin"]
    shipment = sv.create_shipment(s, admin)
    sv.update_shipment(s, admin, shipment, logistics_status="Uçuşta / Yolda", customs_status="Muayenede", awb_no="123")
    reloaded = sv.get_shipment(s, admin, shipment_id=shipment.id)
    assert reloaded.logistics_status == "Uçuşta / Yolda" and reloaded.awb_no == "123"
    with pytest.raises(sv.ServiceError, match="Geçersiz lojistik"):
        sv.update_shipment(s, admin, shipment, logistics_status="Bilinmeyen Durum")


def test_attachments_upload_download_delete_and_size_limit(s, world):
    admin = world["admin"]
    shipment = sv.create_shipment(s, admin)
    att = sv.upload_attachment(s, admin, shipment, "awb", "awb.pdf", "application/pdf", b"%PDF-fake-content")
    assert att.size == len(b"%PDF-fake-content")
    listed = sv.list_attachments(s, admin, shipment)
    assert len(listed) == 1 and listed[0].filename == "awb.pdf"
    full = sv.get_attachment(s, admin, att.id)
    assert full.data == b"%PDF-fake-content"
    sv.delete_attachment(s, admin, att.id)
    assert sv.list_attachments(s, admin, shipment) == []
    with pytest.raises(sv.ServiceError, match="büyük"):
        sv.upload_attachment(s, admin, shipment, "awb", "big.bin", "application/octet-stream", b"0" * (pl.MAX_ATTACHMENT_BYTES + 1))
    with pytest.raises(sv.ServiceError, match="tür"):
        sv.upload_attachment(s, admin, shipment, "gecersiz", "x.pdf", "application/pdf", b"data")


def test_company_shipment_numbering_cannot_go_backwards(s, world):
    admin = world["admin"]
    sv.update_company(s, admin, shipment_prefix="crg", shipment_seq=5)
    assert sv.get_company(s, admin).shipment_prefix == "CRG"
    sv.create_shipment(s, admin)  # CRG_06
    with pytest.raises(sv.ServiceError, match="geriye"):
        sv.update_company(s, admin, shipment_seq=2)
