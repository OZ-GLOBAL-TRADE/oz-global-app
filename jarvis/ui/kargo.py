"""Kargo (CRG) modülü: AWB/taşıyıcı/durum takibi, birden fazla REQ'in ürünlerini tek kargoda birleştirme, belge yükleme.
REQ'lerin kendi Golden Thread aşama akışından tamamen bağımsızdır — yalnızca operasyonel takip amaçlıdır."""
from datetime import datetime, time

import pandas as pd
import streamlit as st

from jarvis import pipeline as pl, services as sv
from jarvis.db import session_scope
from jarvis.ui.common import TR_TZ, fmt_date, fmt_dt, notify_error, notify_success, pill, play_error_sound

STATUS_COLORS = {"Çıkış Hazırlığında": "#64748B", "Uçuşta / Yolda": "#0EA5E9", "Gümrük Bölgesinde": "#8B5CF6",
                 "Dağıtımda": "#F59E0B", "Teslim Edildi": "#22C55E"}
CUSTOMS_COLORS = {"Bekliyor": "#64748B", "Evrak Kontrolde": "#0EA5E9", "Muayenede": "#8B5CF6",
                  "Vergi Onay Bekliyor": "#F59E0B", "Gümrükten Çekildi": "#22C55E"}


def _num(v):
    return None if v is None or pd.isna(v) else float(v)


def _run(fn, *args, ok: str | None = None, bump: bool = False, **kwargs):
    try:
        fn(*args, **kwargs)
    except sv.ServiceError as e:
        play_error_sound()
        for message in e.errors: st.error(message)
        return
    if ok: st.session_state["_kargo_flash"] = ok
    if bump: st.session_state["kargo_ver"] = st.session_state.get("kargo_ver", 0) + 1
    st.rerun()


def _open(code: str):
    st.session_state["open_shipment"] = code
    st.query_params["crg"] = code


def _close():
    st.session_state.pop("open_shipment", None)
    st.query_params.pop("crg", None)


def render():
    actor = st.session_state["actor"]
    code = st.session_state.get("open_shipment") or st.query_params.get("crg")
    if code:
        st.session_state["open_shipment"] = code
        _detail(actor, code)
    else:
        _list(actor)


# ---------------------------------------------------------------- liste

def _list(actor):
    head = st.columns([4, 1.6], vertical_alignment="center")
    head[0].title("Kargo & Gümrük")
    if head[1].button("＋ Yeni Kargo", type="primary", width="stretch"): _new_dialog(actor)
    st.caption("Bir kargoda (CRG) birden fazla REQ'in farklı ürünlerinden gelebilir; buradaki kayıtlar REQ'lerin kendi aşama akışını etkilemez.")

    with session_scope() as s:
        shipments = sv.list_shipments(s, actor)
    if not shipments:
        st.info("Henüz kargo kaydı yok.")
        return
    rows = [{"Kargo": sh.code, "AWB": sh.awb_no or "-", "Taşıyıcı": sh.carrier or "-", "Lojistik": sh.logistics_status,
            "Gümrük": sh.customs_status, "REQ / Kalem": f"{len({it.req_id for it in sh.items})} REQ · {len(sh.items)} kalem",
            "Güncelleme": fmt_dt(sh.updated_at)} for sh in shipments]
    event = st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
                         key=f"crg_table_{st.session_state.get('kargo_ver', 0)}")
    st.caption("Ayrıntı için bir satıra tıklayın.")
    if event.selection.rows:
        _open(shipments[event.selection.rows[0]].code)
        st.rerun()


@st.dialog("Yeni Kargo (CRG)")
def _new_dialog(actor):
    awb = st.text_input("AWB Numarası (opsiyonel)", key="ncrg_awb")
    carrier_opts = pl.CARRIERS
    carrier = st.selectbox("Taşıyıcı", carrier_opts, key="ncrg_carrier")
    date = st.date_input("Çıkış tarihi (opsiyonel)", value=None, key="ncrg_date")
    st.caption("Diğer bilgileri ve içeriği (REQ/ürün) kargo açıldıktan sonra ayrıntı sayfasından ekleyebilirsiniz.")
    if st.button("Kargoyu Oluştur", type="primary", width="stretch", key="ncrg_create"):
        carrier_value = pl.detect_carrier(awb) if carrier == "Otomatik Algıla" else carrier
        departure = datetime.combine(date, time(12, 0), tzinfo=TR_TZ) if date else None
        with session_scope() as s:
            try:
                shipment = sv.create_shipment(s, actor, awb_no=awb, carrier=carrier_value, departure_date=departure)
            except sv.ServiceError as e:
                notify_error(str(e))
                return
        st.session_state["_kargo_flash"] = f"{shipment.code} oluşturuldu."
        _open(shipment.code)
        st.rerun()


# ---------------------------------------------------------------- ayrıntı

def _detail(actor, code: str):
    with session_scope() as s:
        try:
            shipment = sv.get_shipment(s, actor, code=code)
        except sv.ServiceError as e:
            notify_error(str(e))
            st.button("← Kargo Listesi", on_click=_close)
            return
        if flash := st.session_state.pop("_kargo_flash", None): notify_success(flash)

        head = st.columns([5, 1.3], vertical_alignment="center")
        head[0].markdown(f"## {shipment.code} &nbsp; {pill(shipment.logistics_status, STATUS_COLORS.get(shipment.logistics_status, '#64748B'))} "
                         f"{pill(shipment.customs_status, CUSTOMS_COLORS.get(shipment.customs_status, '#64748B'))}", unsafe_allow_html=True)
        caption = f"Oluşturulma {fmt_date(shipment.created_at)} · Son güncelleme {fmt_dt(shipment.updated_at)}"
        if shipment.last_tracked_at: caption += f" · Son otomatik takip {fmt_dt(shipment.last_tracked_at)}"
        head[0].caption(caption)
        head[1].button("← Kargo Listesi", on_click=_close, width="stretch")

        _tracking_section(s, actor, shipment)
        _fields_form(s, actor, shipment)
        st.markdown("---")
        _items_section(s, actor, shipment)
        st.markdown("---")
        _attachments_section(s, actor, shipment)


def _tracking_section(s, actor, shipment):
    """Taşıyıcının kendi takip sayfasına bağlantı (her taşıyıcı) + DHL için resmi API'den otomatik konum çekme."""
    if not shipment.awb_no:
        st.caption("AWB numarası girilince taşıyıcı takip sayfası ve otomatik konum çekme burada görünür.")
        return
    url = pl.tracking_url(shipment.carrier, shipment.awb_no)
    c1, c2 = st.columns([1.6, 1.6])
    if url: c1.link_button(f"🔗 {shipment.carrier or 'Taşıyıcı'} takip sayfasını aç", url, width="stretch")
    if pl.carrier_needs_manual_awb(shipment.carrier):
        c1.caption("Bu taşıyıcının sitesi AWB'yi otomatik doldurmuyor; numarayı kopyalayıp açılan sayfaya yapıştırın:")
        c1.code(shipment.awb_no, language=None)
    if shipment.carrier in pl.AUTO_TRACKING_CARRIERS:
        if c2.button("🔄 Konumu DHL'den otomatik çek", key=f"dhl_track_{shipment.id}", width="stretch"):
            try:
                description = sv.refresh_dhl_tracking(s, actor, shipment)
            except sv.ServiceError as e:
                notify_error(str(e))
            else:
                st.session_state["_kargo_flash"] = f"DHL'den güncellendi: {description}"
                st.rerun()
    elif shipment.carrier:
        c2.caption("Bu taşıyıcı için otomatik konum çekme yok (belgelenmiş genel API bulunmuyor); yukarıdaki bağlantıdan elle kontrol edip "
                  "'Mevcut konum' alanına yazabilirsiniz.")


def _fields_form(s, actor, shipment):
    with st.form(f"crg_form_{shipment.id}", border=False):
        c1, c2, c3 = st.columns(3)
        awb = c1.text_input("AWB Numarası", value=shipment.awb_no)
        carrier_opts = list(dict.fromkeys([*pl.CARRIERS, shipment.carrier] if shipment.carrier else pl.CARRIERS))
        carrier = c2.selectbox("Taşıyıcı", carrier_opts, index=carrier_opts.index(shipment.carrier) if shipment.carrier in carrier_opts else 0)
        current_date = shipment.departure_date.astimezone(TR_TZ).date() if shipment.departure_date else None
        date = c3.date_input("Çıkış tarihi", value=current_date)

        c4, c5 = st.columns(2)
        logi = c4.selectbox("Lojistik durumu", pl.LOGISTICS_STATUSES, index=pl.LOGISTICS_STATUSES.index(shipment.logistics_status))
        customs = c5.selectbox("Gümrük statüsü", pl.CUSTOMS_STATUSES, index=pl.CUSTOMS_STATUSES.index(shipment.customs_status))

        c6, c7, c8 = st.columns(3)
        gcb = c6.text_input("GÇB No", value=shipment.gcb_no)
        delivery_opts = [*pl.DELIVERY_TYPES, "Belirtilmedi"]
        delivery_type = c7.selectbox("Teslimat tipi", delivery_opts, index=delivery_opts.index(shipment.delivery_type) if shipment.delivery_type in delivery_opts else 2)
        location = c8.text_input("Mevcut konum", value=shipment.current_location, placeholder="Örn: ISTANBUL - TURKEY")
        address = st.text_input("Teslimat adresi", value=shipment.delivery_address)
        notes = st.text_area("Notlar", value=shipment.notes, height=70)

        if st.form_submit_button("💾 Kaydet", type="primary"):
            carrier_value = pl.detect_carrier(awb) if carrier == "Otomatik Algıla" else carrier
            departure = datetime.combine(date, time(12, 0), tzinfo=TR_TZ) if date else None
            _run(sv.update_shipment, s, actor, shipment, awb_no=awb, carrier=carrier_value, departure_date=departure,
                logistics_status=logi, customs_status=customs, gcb_no=gcb, delivery_type=delivery_type,
                delivery_address=address, current_location=location, notes=notes, ok="Kaydedildi.")


def _items_section(s, actor, shipment):
    st.markdown("### 📦 İçerik")
    if shipment.items:
        rows = [{"item_id": it.id, "REQ": it.req.code, "Müşteri": it.req.customer.name if it.req.customer_id else "-",
                "Ürün": it.req_line.name, "Bu kargoda": it.qty, "REQ'de toplam": it.req_line.qty} for it in shipment.items]
        for r in rows:
            c1, c2 = st.columns([5, 1], vertical_alignment="center")
            c1.markdown(f"**{r['REQ']}** ({r['Müşteri']}) — {r['Ürün']}: **{r['Bu kargoda']:g}** / {r['REQ\'de toplam']:g} adet")
            if c2.button("Çıkar", key=f"rmitem_{r['item_id']}", width="stretch"):
                _run(sv.remove_shipment_item, s, actor, shipment, r["item_id"], ok="Ürün kargodan çıkarıldı.")
    else:
        st.caption("Bu kargoya henüz ürün eklenmedi.")

    with st.expander("＋ REQ'den ürün ekle"):
        reqs = [r for r in sv.visible_reqs(s, actor, status=pl.ACTIVE) if r.lines]
        if not reqs:
            st.caption("Eklenebilecek aktif REQ yok.")
            return
        by_code = {f"{r.code} — {r.customer.name} ({pl.STAGE_BY_KEY[r.stage].label})": r for r in reqs}
        chosen = st.selectbox("REQ seçin", list(by_code), key=f"crg_req_pick_{shipment.id}")
        req = by_code[chosen]
        info = sv.shippable_lines(s, actor, req, exclude_shipment_id=shipment.id)
        df = pd.DataFrame([{"id": x["line"].id, "Ürün": x["line"].name, "REQ'de Toplam": x["line"].qty,
                            "Kalan (boşta)": x["remaining"], "Eklenecek Adet": 0.0} for x in info if x["remaining"] > 0])
        if df.empty:
            st.caption("Bu REQ'in tüm ürünleri zaten bir kargoya eklenmiş.")
            return
        edited = st.data_editor(df, key=f"crg_add_{shipment.id}_{req.id}_{st.session_state.get('kargo_ver', 0)}", hide_index=True, width="stretch",
                                disabled=["Ürün", "REQ'de Toplam", "Kalan (boşta)"],
                                column_config={"REQ'de Toplam": st.column_config.NumberColumn(format="%g"), "Kalan (boşta)": st.column_config.NumberColumn(format="%g"),
                                              "Eklenecek Adet": st.column_config.NumberColumn(min_value=0.0, format="%g")})
        if st.button("Kargoya ekle", key=f"crg_add_btn_{shipment.id}_{req.id}", type="primary"):
            to_add = [(int(r["id"]), _num(r["Eklenecek Adet"])) for r in edited.to_dict("records") if (_num(r["Eklenecek Adet"]) or 0) > 0]
            if not to_add:
                st.warning("Eklenecek adet girmediniz.")
                return
            for line_id, qty in to_add:
                try:
                    sv.add_shipment_item(s, actor, shipment, line_id, qty)
                except sv.ServiceError as e:
                    notify_error(str(e))
                    return
            _run(lambda: None, ok=f"{len(to_add)} kalem eklendi.", bump=True)


def _attachments_section(s, actor, shipment):
    st.markdown("### 📎 Belgeler")
    st.caption("AWB, Packing List (PL), Proforma Invoice (PI) ve diğer belgeler. Dosya başına en fazla "
              f"{pl.MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB.")
    attachments = sv.list_attachments(s, actor, shipment)
    if attachments:
        for att in attachments:
            c1, c2, c3 = st.columns([3.4, 1, 1], vertical_alignment="center")
            c1.markdown(f"**{pl.ATTACHMENT_KINDS.get(att.kind, att.kind)}** — {att.filename} ({att.size // 1024} KB)")
            full = sv.get_attachment(s, actor, att.id)
            c2.download_button("İndir", data=full.data, file_name=att.filename, mime=att.content_type or "application/octet-stream",
                               key=f"dl_att_{att.id}", width="stretch")
            if c3.button("Sil", key=f"del_att_{att.id}", width="stretch"):
                _run(sv.delete_attachment, s, actor, att.id, ok="Belge silindi.")
    else:
        st.caption("Henüz belge yüklenmedi.")

    with st.form(f"upload_form_{shipment.id}", clear_on_submit=True, border=False):
        c1, c2 = st.columns([1.3, 3])
        kind = c1.selectbox("Belge türü", list(pl.ATTACHMENT_KINDS), format_func=pl.ATTACHMENT_KINDS.get, key=f"kind_{shipment.id}")
        file = c2.file_uploader("Dosya", key=f"file_{shipment.id}", label_visibility="collapsed")
        if st.form_submit_button("Yükle"):
            if not file:
                st.warning("Bir dosya seçin.")
            else:
                _run(sv.upload_attachment, s, actor, shipment, kind, file.name, file.type, file.getvalue(), ok="Belge yüklendi.")
