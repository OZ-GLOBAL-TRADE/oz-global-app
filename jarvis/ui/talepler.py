import io
import json
import urllib.parse
from types import SimpleNamespace as NS

import pandas as pd
import streamlit as st

from jarvis import pipeline as pl, services as sv
from jarvis.db import session_scope
from jarvis.delivery_pdf import render_delivery_pdf
from jarvis.quote_pdf import render_quote_pdf
from jarvis.ui.common import STAGE_COLORS, SYMBOLS, fmt_date, fmt_dt, money, notify_error, notify_success, play_error_sound, req_pill

STATUS_FILTERS = {"Aktif": pl.ACTIVE, "Tamamlanan": pl.DONE, "Rafa Kaldırılan": pl.SHELVED, "Tümü": None}
MARGIN_WARN_PCT = pl.MARGIN_WARN_PCT
MOVE_BACK_REASONS, SHELVE_REASONS = pl.MOVE_BACK_REASONS, pl.SHELVE_REASONS  # tek kaynak: pipeline.py (yeni web arayüzü de kullanır)


# ---------------------------------------------------------------- durum & yardımcılar

def _open(code: str):
    st.session_state["open_req"] = code
    st.session_state["tbl_ver"] = st.session_state.get("tbl_ver", 0) + 1  # listedeki eski satır seçimi sıfırlansın
    st.query_params["req"] = code


def _close():
    st.session_state.pop("open_req", None)
    st.session_state.pop("notes_open", None)
    st.query_params.pop("req", None)


def _notes_closed():
    st.session_state.pop("notes_open", None)


def _ver(req_id: int) -> int:
    return st.session_state.setdefault(f"ver_{req_id}", 0)


def _run(steps, ok: str | None = None, goto: bool = False, bump: int | None = None):
    """Servis çağrılarını sırayla çalıştırır. İş kuralı hatası ekranda gösterilir, başarıda sayfa yenilenir."""
    try:
        for fn, args, kwargs in steps: fn(*args, **kwargs)
    except sv.ServiceError as e:
        play_error_sound()
        for message in e.errors: st.error(message)
        return
    if ok: st.session_state["_flash"] = ok
    if goto: st.session_state["_goto_tab"] = True
    if bump: st.session_state[f"ver_{bump}"] = _ver(bump) + 1
    st.rerun()


def _num(v):
    return None if v is None or pd.isna(v) else float(v)


def _reason_picker(label, options, key):
    """Sık seçilen sebeplerle açılır liste; 'Diğer' seçilirse serbest metin kutusu açılır."""
    choice = st.selectbox(label, options, key=f"{key}_choice")
    if choice == "Diğer":
        return st.text_input("Sebebi yazın", key=f"{key}_custom", placeholder="Listede olmayan bir sebep yazın")
    return choice


# ---------------------------------------------------------------- giriş noktası

def render():
    actor = st.session_state["actor"]
    code = st.session_state.get("open_req") or st.query_params.get("req")
    if code:
        st.session_state["open_req"] = code
        _detail(actor, code)
    else:
        _list(actor)


# ---------------------------------------------------------------- liste & aşama görünümü

def _list(actor):
    head = st.columns([3, 2.4, 2, 1.6], vertical_alignment="center")
    head[0].title("Talepler")
    view = head[1].segmented_control("Görünüm", ["Liste", "Aşama Görünümü"], default="Liste", required=True, key="req_view", label_visibility="collapsed")
    status_label = head[2].selectbox("Durum", list(STATUS_FILTERS), index=list(STATUS_FILTERS).index("Tümü"), key="req_status",
                                     label_visibility="collapsed", disabled=view == "Aşama Görünümü")
    if actor.role in pl.MANAGE_ROLES and head[3].button("＋ Yeni REQ", type="primary", width="stretch"):
        _new_req_dialog(actor)

    with session_scope() as s:
        reqs = sv.visible_reqs(s, actor)
    query = st.text_input("Ara", placeholder="REQ kodu, müşteri veya ürün ara...", label_visibility="collapsed", key="req_search").strip().lower()
    if query:
        reqs = [r for r in reqs if query in r.code.lower() or query in r.customer.name.lower() or any(query in l.name.lower() for l in r.lines)]

    if view == "Aşama Görünümü":
        _board(actor, reqs)
        return
    wanted = STATUS_FILTERS[status_label]
    reqs = [r for r in reqs if wanted is None or r.status == wanted]
    if not reqs:
        st.info("Bu filtrede REQ yok." if wanted else "Henüz REQ yok.")
        return
    show_amount = pl.can_view_stage(actor.role, "teklif")
    rows = []
    for r in reqs:
        row = {"REQ": r.code, "Müşteri": r.customer.name, "Yönetici": r.owner.name,
               "Aşama": pl.STAGE_BY_KEY[r.stage].label if r.status == pl.ACTIVE else pl.STATUS_LABELS[r.status],
               "Kimde": pl.STAGE_BY_KEY[r.stage].waiting if r.status == pl.ACTIVE else "-",
               "Kalem": len(r.lines), "Güncelleme": fmt_dt(r.updated_at)}
        if show_amount: row["Teklif"] = money(pl.quote_for_req(r).total, r.currency) if r.margin_pct is not None else "-"
        rows.append(row)
    df = pd.DataFrame(rows)
    event = st.dataframe(df, hide_index=True, width="stretch", on_select="rerun", selection_mode="multi-row",
                         key=f"req_table_{st.session_state.get('tbl_ver', 0)}")
    selected = event.selection.rows
    b1, b2, _sp = st.columns([1.4, 1.8, 4])
    if b1.button("📂 Ayrıntıyı aç", disabled=len(selected) != 1, width="stretch"):
        _open(reqs[selected[0]].code)
        st.rerun()
    if selected:
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            df.iloc[selected].to_excel(writer, index=False, sheet_name="Talepler")
        b2.download_button(f"⬇️ Seçilenleri indir ({len(selected)} REQ)", data=buf.getvalue(), file_name="talepler.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch")
    else:
        b2.button("⬇️ Seçilenleri indir", disabled=True, width="stretch")
    st.caption("Bir satır seçip 'Ayrıntıyı aç' ile açın; birden fazla seçip Excel'e aktarabilirsiniz.")


def _board(actor, reqs):
    show_amount = pl.can_view_stage(actor.role, "teklif")
    with st.container(key="board"):
        for col, stage in zip(st.columns(len(pl.STAGES)), pl.STAGES):
            items = [r for r in reqs if r.status == pl.ACTIVE and r.stage == stage.key]
            with col:
                st.markdown(f"<div class='colhead' style='--c:{STAGE_COLORS[stage.key]}'>{stage.label}<span>{len(items)}</span></div>", unsafe_allow_html=True)
                for r in items:
                    with st.container(border=True):
                        st.button(r.code, key=f"card_{r.id}", type="tertiary", on_click=_open, args=(r.code,))
                        st.caption(r.customer.name)
                        if show_amount and r.margin_pct is not None: st.caption(money(pl.quote_for_req(r).total, r.currency))
    closed = [r for r in reqs if r.status != pl.ACTIVE]
    if closed:
        with st.expander(f"Tamamlanan / Rafa kaldırılan ({len(closed)})"):
            for r in closed: st.button(f"{r.code} · {pl.STATUS_LABELS[r.status]}", key=f"closed_{r.id}", type="tertiary", on_click=_open, args=(r.code,))


# ---------------------------------------------------------------- yeni REQ

@st.dialog("Yeni Talep (REQ)", width="large")
def _new_req_dialog(actor):
    with session_scope() as s:
        customers, products = sv.list_partners(s, actor, customers=True), sv.list_products(s, actor)
        by_customer, by_product = {c.name: c for c in customers}, {p.name: p.id for p in products}

        with st.expander("＋ Yeni müşteri ekle", expanded=not customers):
            n1, n2, n3 = st.columns([3, 1.4, 1.6])
            name, short = n1.text_input("Müşteri adı", key="nc_name"), n2.text_input("Kısa kod", key="nc_code", help="Boşsa otomatik önerilir (örn. Altınay → ALTN)")
            seq = n3.number_input("Son REQ no", min_value=0, step=1, key="nc_seq", help="Odoo'da bu müşteri için kullanılan son numara; kodlar buradan devam eder.")
            tax_no = st.text_input("Vergi No (VKN/TCKN)", key="nc_tax", help="Teklif PDF'inde müşteri bilgisi altında görünür.")
            address = st.text_area("Adres", key="nc_address", height=70, help="Teklif PDF'inde müşteri bilgisi altında görünür.")
            if st.button("Müşteriyi ekle", key="nc_add"):
                try:
                    sv.add_partner(s, actor, name=name, is_customer=True, short_code=short, req_seq=int(seq), tax_no=tax_no, address=address)
                except sv.ServiceError as e:
                    notify_error(str(e))
                else:
                    st.rerun(scope="fragment")
        if not customers:
            return
        customer = st.selectbox("Müşteri", list(by_customer), key="nr_customer")
        c1, c2, c3 = st.columns([2.4, 1.6, 2])
        c1.markdown(f"Kod otomatik verilecek: **{sv.next_req_code(s, by_customer[customer].id)}**")
        currency = c2.segmented_control("Para birimi", pl.CURRENCIES, default="USD", required=True, key="nr_currency")
        delivery = c3.segmented_control("Teslimat tipi", pl.DELIVERY_TYPES, default=pl.DELIVERY_TYPES[0], required=True, key="nr_delivery")

        st.markdown("**Talep edilen ürünler**")
        empty = pd.DataFrame({"Ürün": pd.Series([], dtype="object"), "Adet": pd.Series([], dtype="float64")})
        items = st.data_editor(empty, num_rows="dynamic", width="stretch", hide_index=True, key="nr_items",
                               column_config={"Ürün": st.column_config.SelectboxColumn("Ürün", options=list(by_product), required=True),
                                              "Adet": st.column_config.NumberColumn("Adet", min_value=1, step=1, default=1, format="%g")})
        with st.expander("＋ Katalogda olmayan ürün ekle"):
            p1, p2 = st.columns([3, 1.5])
            pname, hs = p1.text_input("Ürün adı", key="np_name"), p2.text_input("GTİP (opsiyonel)", key="np_hs")
            if st.button("Ürünü kataloğa ekle", key="np_add"):
                try:
                    sv.add_product(s, actor, name=pname, hs_code=hs)
                except sv.ServiceError as e:
                    notify_error(str(e))
                else:
                    st.rerun(scope="fragment")
        note = st.text_input("Not (opsiyonel)", key="nr_note")

        if st.button("REQ'yi Aç", type="primary", width="stretch", key="nr_create"):
            chosen = [(by_product[r["Ürün"]], _num(r["Adet"]) or 1) for r in items.to_dict("records") if r["Ürün"]]
            try:
                req = sv.create_req(s, actor, customer_id=by_customer[customer].id, items=chosen, currency=currency, delivery_type=delivery, notes=note)
            except sv.ServiceError as e:
                notify_error(str(e))
            else:
                st.session_state["_flash"] = f"{req.code} açıldı."
                _open(req.code)
                st.rerun()


# ---------------------------------------------------------------- REQ ayrıntısı

def _detail(actor, code: str):
    with session_scope() as s:
        try:
            req = sv.get_req(s, actor, code=code)
        except sv.ServiceError as e:
            notify_error(str(e))
            st.button("← Talepler", on_click=_close)
            return
        products, events = sv.list_products(s, actor), sv.list_events(s, req.id, actor)
        if flash := st.session_state.pop("_flash", None): notify_success(flash)

        notes_tasks = [e for e in events if e.kind in ("note", "task")]
        open_tasks = sum(1 for e in notes_tasks if e.kind == "task" and not e.done_at and not e.cancelled_at)
        notes_label = "📋 Notlar & Görevler" + (f" ({open_tasks})" if open_tasks else "")

        head = st.columns([3.5, 1.6, 1.3, 1.2], vertical_alignment="center")
        head[0].markdown(f"## {req.code} &nbsp; {req_pill(req)}", unsafe_allow_html=True)
        head[0].caption(f"🏢 {req.customer.name} · 👤 {req.owner.name} · {req.currency} · {req.delivery_type} · Açılış {fmt_date(req.created_at)} · Son güncelleme {fmt_dt(req.updated_at)}")
        if head[1].button(notes_label, key=f"notes_btn_{req.id}", width="stretch"):
            st.session_state["notes_open"] = req.code
        # Bayrakla açık tutulur: panel içinde kaydetme/tamamlama sayfayı yeniden çalıştırınca kapanmasın;
        # yalnızca kullanıcı X ile kapatınca (on_dismiss) ya da REQ'den çıkınca kapanır.
        if st.session_state.get("notes_open") == req.code:
            _notes_dialog(s, actor, req, notes_tasks)
        if req.status == pl.ACTIVE and actor.role in pl.MANAGE_ROLES:
            with head[2].popover("✏️ Düzelt", width="stretch"):
                st.caption("Yanlış girilen REQ numarasını ya da para birimini düzeltir; aşamadan bağımsız çalışır.")
                prefix, _, current_no = req.code.rpartition("_REQ_")
                n1, n2 = st.columns([2, 1], vertical_alignment="bottom")
                new_no = n1.number_input(f"REQ no ({prefix}_REQ_…)", min_value=1, step=1,
                                         value=int(current_no) if current_no.isdigit() else 1, key=f"reqno_{req.id}",
                                         help="Önek müşterinin kısa kodudur (Kişiler'den değişir). Müşterinin sonraki REQ'i bu numaradan devam eder.")
                if n2.button("Kaydet", key=f"reqno_save_{req.id}", width="stretch"):
                    try:
                        new_code = sv.update_req_number(s, actor, req, int(new_no))
                    except sv.ServiceError as e:
                        notify_error(str(e))
                    else:
                        _open(new_code)
                        st.session_state["_flash"] = f"REQ kodu {new_code} olarak düzeltildi."
                        st.rerun()
                new_currency = st.selectbox("Para birimi", pl.CURRENCIES, index=pl.CURRENCIES.index(req.currency), key=f"cur_{req.id}")
                if new_currency != req.currency and st.button("Para birimini düzelt", key=f"cur_save_{req.id}"):
                    _run([(sv.update_currency, (s, actor, req, new_currency), {})], ok=f"Para birimi {new_currency} olarak düzeltildi.")
        head[3].button("← Talepler", on_click=_close, width="stretch")

        if req.status == pl.SHELVED:
            st.warning(f"Bu REQ rafa kaldırıldı. Sebep: {req.shelved_reason}")
            if actor.role in pl.MANAGE_ROLES and st.button("Yeniden aç", key="reopen"):
                _run([(sv.reopen_req, (s, actor, req), {})], ok="REQ yeniden açıldı.", goto=True)
        _stepper(req)

        visible = [k for k in pl.visible_stages(actor.role) if pl.stage_index(k) <= pl.stage_index(req.stage)]
        current = req.stage if req.stage in visible else visible[-1]
        tab_key = f"tab_{req.id}"
        if st.session_state.pop("_goto_tab", False) or st.session_state.get(tab_key) not in visible: st.session_state[tab_key] = current
        selected = st.segmented_control("Aşama", visible, format_func=lambda k: _tab_label(req, k), required=True, key=tab_key, label_visibility="collapsed")

        editable = req.status == pl.ACTIVE and selected == req.stage and pl.can_edit_stage(actor.role, selected)
        if req.status == pl.ACTIVE and selected == req.stage and not editable:
            st.info(f"Bu aşama şu an **{pl.STAGE_BY_KEY[selected].waiting}** tarafında; düzenleme yetkiniz yok.")
        elif req.status == pl.ACTIVE and selected != req.stage:
            st.caption("Geçmiş aşama, salt okunur. Düzeltmek için aşağıdan 'Önceki aşamaya dön'.")
        with st.container(border=True):
            PANELS[selected](s, actor, req, products, editable)

        _controls(s, actor, req)
        _history(s, actor, req, events)


def _stepper(req):
    idx, cells = pl.stage_index(req.stage), []
    for i, stage in enumerate(pl.STAGES):
        done = i < idx or req.status == pl.DONE
        cls, mark = ("done", "✔") if done else (("now", "📍") if i == idx and req.status == pl.ACTIVE else ("todo", "○"))
        cells.append(f"<div class='step {cls}'>{mark}<br>{stage.label}</div>")
    st.markdown(f"<div class='stepper'>{''.join(cells)}</div>", unsafe_allow_html=True)


def _tab_label(req, key: str) -> str:
    i, cur = pl.stage_index(key), pl.stage_index(req.stage)
    mark = "✔" if i < cur or req.status == pl.DONE else "📍"
    return f"{mark} {pl.STAGE_BY_KEY[key].label}"


def _controls(s, actor, req):
    if req.status != pl.ACTIVE or actor.role not in pl.MANAGE_ROLES: return
    if req.stage != "talep":  # Talep aşamasında adetler zaten kendi panelinde düzenleniyor
        with st.expander("🔢 Adetleri düzelt"):
            st.caption("Yanlış girilen adetleri önceki aşamalara dönmeden düzeltin. Teslim edilen ya da kargoya ayrılan miktarın "
                       "altına inilemez. Teklif müşteriye iletildiyse, yeni teklif PDF'i revizyon (-R2) olarak oluşur.")
            qdf = pd.DataFrame([{"id": l.id, "Ürün": l.name, "Adet": l.qty} for l in req.lines])
            edited = st.data_editor(qdf, key=f"qty_{req.id}_{_ver(req.id)}", hide_index=True, width="stretch",
                                    column_order=["Ürün", "Adet"], disabled=["Ürün"],
                                    column_config={"Adet": st.column_config.NumberColumn(min_value=0.0, step=1.0, format="%g")})
            if st.button("Adetleri kaydet", key=f"qty_save_{req.id}"):
                rows = [{"id": r["id"], "qty": r["Adet"]} for r in edited.to_dict("records")]
                _run([(sv.update_line_qtys, (s, actor, req, rows), {})], ok="Adetler güncellendi.", bump=req.id)
    c1, c2 = st.columns(2)
    if pl.prev_stage(req.stage):
        with c1.expander("↩️ Önceki aşamaya dön"):
            reason = _reason_picker("Sebep", MOVE_BACK_REASONS, f"back_reason_{req.id}")
            st.caption("Sonraki aşamalardaki onaylar (teklif iletildi, müşteri kararı vb.) sıfırlanır.")
            if st.button("Geri al", key=f"back_{req.id}"): _run([(sv.move_back, (s, actor, req, reason), {})], ok="Önceki aşamaya dönüldü.", goto=True)
    with c2.expander("⏸️ Rafa kaldır"):
        reason = _reason_picker("Sebep", SHELVE_REASONS, f"shelve_reason_{req.id}")
        if st.button("Rafa kaldır", key=f"shelve_{req.id}"): _run([(sv.shelve_req, (s, actor, req, reason), {})], ok="REQ rafa kaldırıldı.")


def _history(s, actor, req, events):
    """Salt okunur sistem geçmişi (aşama geçişi, düzenleme, tamamlama). Notlar/görevler artık burada değil —
    bkz. _notes_dialog (sağdan açılan, Streamlit'in modal 'popup'ı — gerçek kaydırmalı panel değil, aşağıya bakın)."""
    log = [e for e in events if e.kind not in ("note", "task")]
    icons = {"create": "🆕", "stage": "➡️", "edit": "✏️", "status": "🏁"}
    with st.expander(f"🕘 Geçmiş ({len(log)})"):
        for e in log[:60]:
            st.markdown(f"{icons.get(e.kind, '•')} **{fmt_dt(e.created_at)}** · {e.user.name if e.user else '-'} — {e.message}")


@st.dialog("📋 Notlar & Görevler", width="large", on_dismiss=_notes_closed)
def _notes_dialog(s, actor, req, notes_tasks):
    with st.container(key="drawer_notes"):  # common.CSS: "drawer_" işareti diyaloğu sağdan kayan panele çevirir
        st.caption(req.code)
    users = sv.list_assignable_users_for_req(s, actor, req)
    with st.form(f"noteform_{req.id}", clear_on_submit=True, border=False):
        c1, c2 = st.columns([3, 1.4])
        note = c1.text_input("Not ekle ya da görev ata", placeholder="Örn: Çin ofisi fiyatı WeChat'ten iletti")
        assignee = c2.selectbox("Kime (opsiyonel)", ["Not (kimseye atama)", *[u.name for u in users]], key=f"assignee_{req.id}",
                                help="Yalnızca bu REQ'i zaten görebilen kullanıcılara görev atanabilir.")
        if st.form_submit_button("Kaydet"):
            assignee_id = next((u.id for u in users if u.name == assignee), None)
            _run([(sv.add_note, (s, actor, req, note), {"assignee_id": assignee_id})],
                 ok="Görev atandı." if assignee_id else "Not eklendi.")
    if not notes_tasks:
        st.caption("Henüz not ya da görev yok.")
    for e in notes_tasks:
        if e.kind == "task":
            who = e.assignee.name if e.assignee else "-"
            if e.done_at:
                st.markdown(f"✅ **{fmt_dt(e.created_at)}** · {e.user.name if e.user else '-'} → **{who}**: {e.message} "
                           f"_(tamamlandı {fmt_dt(e.done_at)})_")
            elif e.cancelled_at:
                st.markdown(f"🚫 **{fmt_dt(e.created_at)}** · {e.user.name if e.user else '-'} → **{who}**: {e.message} "
                           f"_(iptal edildi {fmt_dt(e.cancelled_at)})_")
            else:
                c1, c2, c3 = st.columns([4.4, 1, 1], vertical_alignment="center")
                c1.markdown(f"📌 **{fmt_dt(e.created_at)}** · {e.user.name if e.user else '-'} → **{who}**: {e.message}")
                can_act = actor.id == e.assignee_id or actor.role in pl.MANAGE_ROLES
                if can_act and c2.button("✅", key=f"done_{e.id}", width="stretch", help="Tamamlandı"):
                    _run([(sv.complete_task, (s, actor, e.id), {})], ok="Görev tamamlandı.")
                if can_act and c3.button("✖️", key=f"cancel_{e.id}", width="stretch", help="İptal et"):
                    _run([(sv.cancel_task, (s, actor, e.id), {})], ok="Görev iptal edildi.")
        else:
            st.markdown(f"💬 **{fmt_dt(e.created_at)}** · {e.user.name if e.user else '-'} — {e.message}")

    st.divider()
    _req_attachments(s, actor, req)


def _req_attachments(s, actor, req):
    st.markdown("**📎 Dosyalar**")
    attachments = sv.list_req_attachments(s, actor, req)
    if attachments:
        for att in attachments:
            c1, c2, c3 = st.columns([3.4, 1, 1], vertical_alignment="center")
            c1.markdown(f"{att.filename} ({att.size // 1024} KB) · {fmt_dt(att.uploaded_at)}")
            full = sv.get_attachment(s, actor, att.id)
            c2.download_button("İndir", data=full.data, file_name=att.filename, mime=att.content_type or "application/octet-stream",
                               key=f"dl_reqatt_{att.id}", width="stretch")
            if c3.button("Sil", key=f"del_reqatt_{att.id}", width="stretch"):
                _run([(sv.delete_attachment, (s, actor, att.id), {})], ok="Dosya silindi.")
    else:
        st.caption("Henüz dosya yüklenmedi.")
    with st.form(f"reqfile_form_{req.id}", clear_on_submit=True, border=False):
        file = st.file_uploader(f"Dosya ekle (en fazla {pl.MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB)", key=f"reqfile_{req.id}")
        if st.form_submit_button("Yükle"):
            if not file: st.warning("Bir dosya seçin.")
            else: _run([(sv.upload_req_attachment, (s, actor, req, file.name, file.type, file.getvalue()), {})], ok="Dosya yüklendi.")


# ---------------------------------------------------------------- aşama panelleri

def _save_bar(req, save_step, next_label: str, next_steps, bump: bool = True, key: str = ""):
    """Kaydet / Kaydet ve sonraki aşamaya aktar düğmeleri. save_step: [(fn, args, kwargs)]."""
    b1, b2 = st.columns([1, 2])
    b = req.id if bump else None
    if b1.button("💾 Kaydet", key=f"save_{key}_{req.id}", width="stretch"):
        _run(save_step, ok="Kaydedildi.", bump=b)
    if b2.button(next_label, key=f"next_{key}_{req.id}", type="primary", width="stretch"):
        _run(save_step + next_steps, ok="Sonraki aşamaya aktarıldı.", goto=True, bump=b)


def _call(fn, *args, **kwargs):
    return (fn, args, kwargs)


def _advance(s, actor, req):
    return [_call(sv.advance_req, s, actor, req)]


def _gmail_url(data: dict) -> str:
    customer, company = data["customer"], data["company"]
    subject = f"Teklif {data['number']} - {company.get('name', '')}"
    body = (f"Sayın {customer.get('name', '')} yetkilisi,\n\n{data['number']} numaralı teklifimiz ekte yer almaktadır. "
            f"Teklif {data['valid_until']} tarihine kadar geçerlidir.\n\nİyi çalışmalar dileriz.\n{company.get('name', '')}")
    return (f"https://mail.google.com/mail/?view=cm&fs=1&to={urllib.parse.quote(customer['email'])}"
            f"&su={urllib.parse.quote(subject)}&body={urllib.parse.quote(body)}")


def _quotes_section(s, actor, req):
    """Müşteriye giden numaralı teklifler (en yeni revizyon başta). PDF, oluşturulduğu andaki içerikten üretilir."""
    quotes = sv.list_quotes(s, actor, req)
    if not quotes: return
    st.markdown("**Müşteriye giden teklifler**")
    for i, doc in enumerate(quotes):
        data = json.loads(doc.snapshot)
        c1, c2, c3 = st.columns([3.4, 1.3, 1.5], vertical_alignment="center")
        c1.markdown(f"**{doc.number}** &nbsp;·&nbsp; {fmt_dt(doc.issued_at)} &nbsp;·&nbsp; {money(doc.grand_total, doc.currency)}"
                    + (" &nbsp;·&nbsp; güncel" if i == 0 else " &nbsp;·&nbsp; eski revizyon"))
        if i < 3:
            c2.download_button("📄 PDF indir", data=render_quote_pdf(data), file_name=f"{doc.number}.pdf", mime="application/pdf",
                               key=f"dl_{doc.id}", width="stretch")
        if i == 0:
            if data["customer"].get("email"): c3.link_button("✉️ Gmail'de aç", _gmail_url(data), width="stretch")
            else: c3.caption("Müşteri e-postası kayıtlı değil")
    st.caption("PDF'i indirip e-postaya ekleyin: Gmail düğmesi konu ve metni hazırlar, dosyayı otomatik eklemez.")


def _panel_talep(s, actor, req, products, editable):
    st.markdown(f"**Müşteri:** {req.customer.name} &nbsp;·&nbsp; **Para birimi:** {req.currency}")
    if req.notes: st.caption(f"Not: {req.notes}")
    df = pd.DataFrame([{"id": l.id, "Ürün": l.name, "Adet": l.qty} for l in req.lines], columns=["id", "Ürün", "Adet"])
    if not editable:
        st.markdown(f"**Teslimat tipi:** {req.delivery_type}")
        st.dataframe(df[["Ürün", "Adet"]], hide_index=True, width="stretch")
        return
    delivery = st.segmented_control("Teslimat tipi", pl.DELIVERY_TYPES, default=req.delivery_type, required=True, key=f"deliv_{req.id}",
                                    help="Gümrük teslim: ürün gümrükte teslim edilir. Kapı teslim: müşterinin adresine kadar. Masrafları buna göre girin.")
    by_product, line_product = {p.name: p.id for p in products}, {l.id: l.product_id for l in req.lines}
    options = sorted(set(by_product) | set(df["Ürün"]))
    edited = st.data_editor(df, key=f"items_{req.id}_{_ver(req.id)}", hide_index=True, num_rows="dynamic", width="stretch",
                            column_order=["Ürün", "Adet"],
                            column_config={"Ürün": st.column_config.SelectboxColumn("Ürün", options=options, required=True),
                                           "Adet": st.column_config.NumberColumn("Adet", min_value=1, step=1, default=1, format="%g")})
    rows = [{"id": r["id"], "product_id": by_product.get(r["Ürün"]) or line_product.get(r["id"]), "qty": r["Adet"]}
            for r in edited.to_dict("records") if r["Ürün"]]
    with st.expander("＋ Katalogda olmayan ürün ekle"):
        p1, p2, p3 = st.columns([3, 1.5, 1])
        name, hs = p1.text_input("Ürün adı", key=f"qa_name_{req.id}"), p2.text_input("GTİP (opsiyonel)", key=f"qa_hs_{req.id}")
        if p3.button("Ekle", key=f"qa_add_{req.id}", width="stretch"):
            _run([_call(sv.add_product, s, actor, name=name, hs_code=hs)], ok=f"'{name}' kataloğa eklendi.")
    save = [_call(sv.update_fields, s, actor, req, delivery_type=delivery), _call(sv.save_items, s, actor, req, rows)]
    _save_bar(req, save, "Kaydet ve Fiyat Araştırması'na Aktar →", _advance(s, actor, req), key="talep")


def _price_frame(req, products, extras: list[tuple] | None = None):
    """Satır tablosu; extras=[(sütun adı, satır alanı), ...] ile düzenlenecek ek sütunlar eklenir."""
    catalog = {p.id: p for p in products}
    rows = []
    for l in req.lines:
        product = catalog.get(l.product_id)
        row = {"id": l.id, "Ürün": l.name, "GTİP": product.hs_code if product else "", "Adet": l.qty,
               "Katalog Son Alış": product.last_cost if product else None, "Birim Alış": l.unit_cost}
        for label, attr in extras or []: row[label] = getattr(l, attr)
        rows.append(row)
    return pd.DataFrame(rows)


def _rfq_gmail_url(product: str, supplier: dict) -> str:
    subject = f"RFQ - Quotation Request for {product} - OZ Global Trade"
    body = (f"Dear {supplier.get('kisi') or 'Sales Team'},\n\nWe are reaching out from OZ Global Trade regarding the procurement of '{product}'.\n\n"
            "Could you please provide your official quotation including:\n1. Unit price (EXW / FOB)\n2. Minimum Order Quantity (MOQ)\n"
            "3. Estimated production / delivery lead time\n\nWe look forward to your prompt response.\n\nBest regards,\nOZ Global Trade Team")
    return f"https://mail.google.com/mail/?view=cm&fs=1&to={urllib.parse.quote(supplier['eposta'])}&su={urllib.parse.quote(subject)}&body={urllib.parse.quote(body)}"


def _supplier_search_section(s, actor, req):
    with st.expander("🔍 Tedarikçi Ara (Jarvis AI)"):
        st.caption("REQ'deki ürünleri tedarikçi havuzuyla (Kişiler > Tedarikçiler) eşleştirir, RFQ e-posta taslağı hazırlar. "
                  "Seçtiğiniz tedarikçi bu REQ satırına kaydedilir (bilgi amaçlıdır, fiyatı etkilemez).")
        key = f"sup_matches_{req.id}"
        if st.button("🚀 Tedarikçileri Tara", key=f"search_sup_{req.id}"):
            with st.spinner("Tedarikçi havuzu taranıyor..."):
                matches, error = sv.search_suppliers(s, actor, req)
            if error: notify_error(error)
            elif not matches: st.warning("Bu ürünler için tedarikçi havuzunda eşleşen firma bulunamadı.")
            st.session_state[key] = matches

        grouped = {}
        for m in st.session_state.get(key) or []: grouped.setdefault(m.get("talep", "Genel Talep"), []).append(m)
        by_name = {l.name: l for l in req.lines}
        for product, sups in grouped.items():
            st.markdown(f"**{product}**")
            line = by_name.get(product)
            for i, m in enumerate(sups):
                c1, c2, c3 = st.columns([3, 1.3, 1.5], vertical_alignment="center")
                c1.markdown(f"🏢 {m.get('tedarikci', '-')} ({m.get('ulke', '-')})")
                c1.caption(m.get("aciklama", "") + ("" if m.get("eposta") else " · ⚠️ e-posta kayıtlı değil"))
                if m.get("eposta"): c2.link_button("✉️ RFQ Gönder", _rfq_gmail_url(product, m), width="stretch", key=f"rfq_{req.id}_{product}_{i}")
                if line:
                    picked = line.supplier_id == m.get("tedarikci_id")
                    if c3.button("✅ Seçildi" if picked else "Bu tedarikçiyi seç", key=f"pick_{req.id}_{line.id}_{m.get('tedarikci_id')}",
                                width="stretch", disabled=picked):
                        _run([_call(sv.set_line_supplier, s, actor, req, line.id, m["tedarikci_id"])], ok=f"{m['tedarikci']} seçildi.")
                st.divider()


def _panel_fiyat(s, actor, req, products, editable):
    cur = SYMBOLS.get(req.currency, req.currency)
    st.caption("Çin ofisinden / tedarikçiden gelen birim alış fiyatlarını girin. Katalogdaki son alış fiyatı referans içindir.")
    if editable: _supplier_search_section(s, actor, req)
    df = _price_frame(req, products)
    df["Tedarikçi"] = [l.supplier.name if l.supplier else "-" for l in req.lines]
    suppliers = {p.name: p.id for p in sv.list_partners(s, actor, suppliers=True)}
    cfg = {"Adet": st.column_config.NumberColumn(format="%g"), "Katalog Son Alış": st.column_config.NumberColumn(format="%.2f"),
           "Birim Alış": st.column_config.NumberColumn(f"Birim Alış ({cur})", min_value=0.0, format="%.2f"),
           "Tedarikçi": st.column_config.SelectboxColumn("Tedarikçi", options=["-", *suppliers],
                                                         help="Kişiler > Tedarikçiler'deki firmalardan elle seçin (akıllı arama zorunlu değil).")}
    order = ["Ürün", "Tedarikçi", "Adet", "Katalog Son Alış", "Birim Alış"]
    if not editable:
        st.dataframe(df[order], hide_index=True, width="stretch", column_config=cfg)
        edited = df
    else:
        if not suppliers: st.caption("Tedarikçi listesi boş — önce Kişiler > Tedarikçiler'den ekleyin.")
        edited = st.data_editor(df, key=f"fiyat_{req.id}_{_ver(req.id)}", hide_index=True, width="stretch", column_order=order,
                                disabled=["Ürün", "Adet", "Katalog Son Alış"], column_config=cfg)
    total = sum(r["Adet"] * (_num(r["Birim Alış"]) or 0.0) for r in edited.to_dict("records"))
    st.metric("Toplam ürün alış maliyeti", money(total, req.currency))
    if editable:
        records = edited.to_dict("records")
        rows = [{"id": r["id"], "value": _num(r["Birim Alış"])} for r in records]
        picks = [{"id": r["id"], "supplier_id": suppliers.get(r["Tedarikçi"])} for r in records]
        _save_bar(req, [_call(sv.save_line_suppliers, s, actor, req, picks), _call(sv.save_line_values, s, actor, req, "unit_cost", rows)],
                  "Kaydet ve Gümrük'e Aktar →", _advance(s, actor, req), key="fiyat")


def _panel_gumruk(s, actor, req, products, editable):
    cur = SYMBOLS.get(req.currency, req.currency)
    kind_of = {label: key for key, label in pl.COST_KINDS.items()}
    st.caption(f"Teslimat tipi: **{req.delivery_type}**. Ürün başına gümrük ve lojistik masrafını ayrı girin "
               "(gümrük yoksa 0 yazın; lojistik boş kalabilir). Ürüne bağlı olmayan masrafları aşağıya tür seçerek ekleyin.")
    df = _price_frame(req, products, [("Birim Gümrük", "unit_customs"), ("Birim Lojistik", "unit_logistics")])
    cfg = {"Adet": st.column_config.NumberColumn(format="%g"), "Birim Alış": st.column_config.NumberColumn(f"Birim Alış ({cur})", format="%.2f"),
           "Birim Gümrük": st.column_config.NumberColumn(f"Birim Gümrük ({cur})", min_value=0.0, format="%.2f"),
           "Birim Lojistik": st.column_config.NumberColumn(f"Birim Lojistik ({cur})", min_value=0.0, format="%.2f")}
    order = ["Ürün", "GTİP", "Adet", "Birim Alış", "Birim Gümrük", "Birim Lojistik"]
    costs = pd.DataFrame([{"Masraf": c.label, "Tür": pl.COST_KINDS.get(c.kind, "Diğer"), "Tutar": c.amount} for c in req.costs], columns=["Masraf", "Tür", "Tutar"])
    cost_cfg = {"Masraf": st.column_config.TextColumn(required=True),
                "Tür": st.column_config.SelectboxColumn(options=list(pl.COST_KINDS.values()), required=True, default=pl.COST_KINDS["lojistik"]),
                "Tutar": st.column_config.NumberColumn(f"Tutar ({cur})", min_value=0.0, format="%.2f")}
    if not editable:
        st.dataframe(df[order], hide_index=True, width="stretch", column_config=cfg)
        if not costs.empty: st.dataframe(costs, hide_index=True, width="stretch", column_config=cost_cfg)
        edited, edited_costs = df, costs
    else:
        edited = st.data_editor(df, key=f"gumruk_{req.id}_{_ver(req.id)}", hide_index=True, width="stretch", column_order=order,
                                disabled=["Ürün", "GTİP", "Adet", "Birim Alış"], column_config=cfg)
        st.markdown("**Ekstra masraflar** (ürüne bağlı olmayanlar: nakliye, ekspertiz, gümrük müşavir ücreti vb.)")
        edited_costs = st.data_editor(costs, key=f"costs_{req.id}_{_ver(req.id)}", hide_index=True, num_rows="dynamic", width="stretch", column_config=cost_cfg)

    totals = {"gumruk": 0.0, "lojistik": 0.0, "diger": 0.0}
    for r in edited.to_dict("records"):
        totals["gumruk"] += r["Adet"] * (_num(r["Birim Gümrük"]) or 0.0)
        totals["lojistik"] += r["Adet"] * (_num(r["Birim Lojistik"]) or 0.0)
    for r in edited_costs.to_dict("records"):
        if r["Masraf"]: totals[kind_of.get(r["Tür"], "diger")] += _num(r["Tutar"]) or 0.0
    m1, m2, m3 = st.columns(3)
    m1.metric("Toplam gümrük", money(totals["gumruk"], req.currency))
    m2.metric("Toplam lojistik", money(totals["lojistik"], req.currency))
    m3.metric("Diğer masraflar", money(totals["diger"], req.currency))
    if hint := pl.delivery_hint(req.delivery_type, totals["gumruk"]): st.warning(hint)
    if editable:
        customs = [{"id": r["id"], "value": _num(r["Birim Gümrük"])} for r in edited.to_dict("records")]
        logistics = [{"id": r["id"], "value": _num(r["Birim Lojistik"])} for r in edited.to_dict("records")]
        cost_rows = [{"label": r["Masraf"], "amount": _num(r["Tutar"]), "kind": kind_of.get(r["Tür"], "diger")} for r in edited_costs.to_dict("records")]
        save = [_call(sv.save_line_values, s, actor, req, "unit_customs", customs), _call(sv.save_line_values, s, actor, req, "unit_logistics", logistics),
                _call(sv.save_costs, s, actor, req, cost_rows)]
        _save_bar(req, save, "Kaydet ve Teklif Aşamasına Aktar →", _advance(s, actor, req), key="gumruk")

def _margin_label(r) -> str:
    if r["kind"] == "lojistik": return f"Lojistik marjı %{r['margin_pct']:g}" if r["margin_pct"] is not None else "-"
    if r["override"]: return "Sabit fiyat"
    return f"%{r['margin_pct']:g}" if r["margin_pct"] is not None else "-"


def _panel_teklif(s, actor, req, products, editable):
    cur = req.currency
    if editable:
        c1, c2, c3 = st.columns([1, 1.3, 1])
        margin = c1.number_input("Varsayılan kâr marjı (%)", min_value=0.0, step=1.0, format="%.1f", key=f"marj_{req.id}",
                                 value=req.margin_pct if req.margin_pct is not None else 20.0,
                                 help="Maliyetin üzerine eklenir (markup). Aşağıdaki tabloda kendi marjı veya doğrudan fiyatı olmayan tüm ürünler bu marjı kullanır.")
        tax_on = c2.toggle("KDV uygula", value=req.tax_enabled, key=f"kdvon_{req.id}", help="Bazı tekliflerde KDV yoktur; kapatınca teklifte KDV satırı çıkmaz.")
        tax = c2.number_input("KDV (%)", min_value=0.0, max_value=100.0, step=1.0, format="%.0f", key=f"kdv_{req.id}", value=req.tax_pct, disabled=not tax_on)
        valid = c3.number_input("Geçerlilik (gün)", min_value=1, step=1, key=f"valid_{req.id}", value=int(req.valid_days))
        terms = st.text_area("Ödeme koşulları", key=f"terms_{req.id}", value=req.payment_terms, height=80,
                             placeholder="Her satır PDF'de ayrı bir madde olarak görünür.\nÖrn:\n%50 peşin\n%50 sevkiyat öncesi",
                             help="Satır satır yazın; teklif PDF'inde banka bilgilerinin altında, madde madde listelenir.")
        modes = list(pl.LOGISTICS_MODES)
        mode = st.radio("Lojistik teklifte nasıl görünsün?", modes, index=modes.index(req.logistics_mode), format_func=pl.LOGISTICS_MODES.get,
                        horizontal=True, key=f"lmode_{req.id}",
                        help="Toplam tutar aynı kalır, yalnızca sunum değişir. 'Ayrı kalem': ürünlerin ham fiyatı değişmez, lojistik tek satır olarak eklenir.")
        logi_margin = None
        if mode == "ayri":
            lc1, lc2 = st.columns([1.3, 1])
            use_own = lc1.checkbox("Lojistik için ayrı kâr marjı kullan", value=req.logistics_margin_pct is not None, key=f"logiown_{req.id}",
                                   help="Kapalıyken lojistik de varsayılan kâr marjını kullanır.")
            if use_own:
                logi_margin = lc2.number_input("Lojistik kâr marjı (%)", min_value=0.0, step=1.0, format="%.1f", key=f"logimarj_{req.id}",
                                               value=req.logistics_margin_pct if req.logistics_margin_pct is not None else margin)
    else:
        margin, tax_on, tax, valid, terms, mode = req.margin_pct, req.tax_enabled, req.tax_pct, req.valid_days, req.payment_terms, req.logistics_mode
        logi_margin = req.logistics_margin_pct
        st.markdown(f"**Varsayılan kâr marjı:** %{margin if margin is not None else '-'} &nbsp;·&nbsp; **KDV:** {f'%{tax:g}' if tax_on else 'uygulanmıyor'} &nbsp;·&nbsp; "
                    f"**Geçerlilik:** {valid} gün &nbsp;·&nbsp; **Lojistik:** {pl.LOGISTICS_MODES[mode]}"
                    + (f" (marj %{logi_margin:g})" if mode == "ayri" and logi_margin is not None else "")
                    + f" &nbsp;·&nbsp; **Teslimat:** {req.delivery_type}")
        if terms: st.caption("Ödeme koşulları: " + " · ".join(l for l in terms.splitlines() if l.strip()))
    if margin is None:
        st.info("Kâr marjı henüz girilmedi.")
        return

    # Ürün bazlı kâr marjı / doğrudan satış fiyatı: boş bırakılan hücreler yukarıdaki varsayılan marjı kullanır.
    # Not: Doğrudan Satış Fiyatı'na 0 (ya da hiç) girilmesi "boş" sayılır — kimse ürünü gerçekten $0'a satmak istemez,
    # bu yüzden yanlışlıkla o sütuna 0 yazılması sessizce marja geri düşer (save_line_values'daki kuralla birebir aynı).
    cost_preview = pl.calculate_quote(req.lines, req.costs, 0, 0, mode)
    df_margin = pd.DataFrame([{"id": l.id, "Ürün": l.name, "Adet": l.qty, "Maliyet": cost_preview.rows[i]["cost"],
                               "Kâr Marjı %": l.margin_pct, "Doğrudan Satış Fiyatı": l.sale_price_override}
                              for i, l in enumerate(req.lines)])
    margin_cfg = {"Adet": st.column_config.NumberColumn(format="%g"), "Maliyet": st.column_config.NumberColumn(format="%.2f"),
                  "Kâr Marjı %": st.column_config.NumberColumn(min_value=0.0, format="%.1f",
                                                                help="Boş bırakılırsa bu ürün yukarıdaki varsayılan marjı kullanır."),
                  "Doğrudan Satış Fiyatı": st.column_config.NumberColumn(min_value=0.0, format="%.2f",
                                                                         help="Doldurursanız marj tamamen yok sayılır, birim satış fiyatı doğrudan bu olur. "
                                                                              "Boş (ya da 0) = marjdan hesapla.")}
    order = ["Ürün", "Adet", "Maliyet", "Kâr Marjı %", "Doğrudan Satış Fiyatı"]
    if editable:
        st.markdown("**Ürün bazlı kâr marjı / doğrudan satış fiyatı (opsiyonel)**")
        st.caption("İki sütundan yalnızca biri geçerli olur: 'Doğrudan Satış Fiyatı' doluysa 'Kâr Marjı %' yok sayılır. "
                  "Hangi ürünün hangi yöntemle fiyatlandığını aşağıdaki 'Fiyatlandırma' satırından anında görebilirsiniz.")
        edited_margin = st.data_editor(df_margin, key=f"margins_{req.id}_{_ver(req.id)}", hide_index=True, width="stretch", column_order=order,
                                       disabled=["Ürün", "Adet", "Maliyet"], column_config=margin_cfg)
    else:
        edited_margin = df_margin

    def _clean_override(v):  # arayüzdeki canlı önizleme, kaydedilince olacak durumla birebir eşleşsin (0 = boş)
        n = _num(v)
        return None if n is not None and n <= 0 else n

    patched = [NS(name=l.name, qty=l.qty, unit_cost=l.unit_cost, unit_customs=l.unit_customs, unit_logistics=l.unit_logistics,
                  margin_pct=_num(r["Kâr Marjı %"]), sale_price_override=_clean_override(r["Doğrudan Satış Fiyatı"]))
               for l, r in zip(req.lines, edited_margin.to_dict("records"))]
    q = pl.calculate_quote(patched, req.costs, margin, tax if tax_on else 0.0, mode, logi_margin)
    if editable:
        st.caption("**Fiyatlandırma:** " + " &nbsp;·&nbsp; ".join(f"{r['name']}: {_margin_label(r)}" for r in q.rows if r["kind"] == "urun"))
    if any(l.unit_cost is None for l in req.lines): st.warning("Bazı ürünlerde birim alış fiyatı yok; teklif eksik hesaplanıyor.")
    if margin > MARGIN_WARN_PCT: st.warning(f"Varsayılan kâr marjı %{margin:g}: alışılmadık derecede yüksek. Emin misiniz?")
    if hint := pl.delivery_hint(req.delivery_type, q.cost_customs): st.warning(hint)

    st.markdown("**Maliyet dağılımı**")
    costs = [("Ürün alış", q.cost_products), ("Gümrük", q.cost_customs), ("Lojistik", q.cost_logistics), ("Diğer masraflar", q.cost_other), ("Toplam maliyet", q.cost_total)]
    for col, (label, value) in zip(st.columns(len(costs)), costs): col.metric(label, money(value, cur))
    st.markdown("**Teklif**")
    sale = [("Kâr", q.profit), ("Teklif tutarı (KDV hariç)" if tax_on else "Teklif tutarı (KDV yok)", q.total)]
    if tax_on: sale += [(f"KDV %{tax:g}", q.tax), ("KDV dahil toplam", q.grand_total)]
    for col, (label, value) in zip(st.columns(len(sale)), sale): col.metric(label, money(value, cur))

    table = pd.DataFrame([{"Ürün": r["name"], "Adet": r["qty"], "Birim Maliyet": r["cost"] / r["qty"] if r["qty"] else 0.0,
                           "Birim Satış": r["unit_price"], "Satır Toplamı": r["line_total"], "Marj / Fiyat": _margin_label(r)} for r in q.rows])
    st.dataframe(table, hide_index=True, width="stretch", column_config={
        "Adet": st.column_config.NumberColumn(format="%g"), "Birim Maliyet": st.column_config.NumberColumn(format="%.2f"),
        "Birim Satış": st.column_config.NumberColumn(format="%.2f"), "Satır Toplamı": st.column_config.NumberColumn(format="%.2f")})
    if mode == "ayri": st.caption("Lojistik ayrı kalem olarak gösteriliyor; ürün birim fiyatları lojistik içermiyor.")
    elif q.cost_logistics or q.cost_other: st.caption("Lojistik ve ekstra masraflar ürün maliyetlerine oranlı dağıtıldı; her ürün kendi marjıyla fiyatlanır.")
    if req.quote_sent_at: st.success(f"Teklif müşteriye iletildi ({fmt_dt(req.quote_sent_at)}).")
    _quotes_section(s, actor, req)
    if editable:
        margin_rows = [{"id": r["id"], "value": _num(r["Kâr Marjı %"])} for r in edited_margin.to_dict("records")]
        price_rows = [{"id": r["id"], "value": _num(r["Doğrudan Satış Fiyatı"])} for r in edited_margin.to_dict("records")]
        fields = dict(margin_pct=margin, logistics_margin_pct=logi_margin, tax_enabled=bool(tax_on), tax_pct=tax,
                     valid_days=int(valid), payment_terms=terms.strip(), logistics_mode=mode)
        save = [_call(sv.update_fields, s, actor, req, **fields), _call(sv.save_line_values, s, actor, req, "margin_pct", margin_rows),
               _call(sv.save_line_values, s, actor, req, "sale_price_override", price_rows)]
        b1, b2, b3 = st.columns([1, 1.5, 2.6])
        if b1.button("💾 Kaydet", key=f"save_teklif_{req.id}", width="stretch"): _run(save, ok="Kaydedildi.")
        if b2.button("📄 Teklif PDF'i oluştur", key=f"pdf_teklif_{req.id}", width="stretch"):
            _run(save + [_call(sv.issue_quote, s, actor, req)], ok="Teklif PDF'i hazır.")
        if b3.button("✉️ Müşteriye iletildi olarak işaretle ve Karar'a geç →", type="primary", key=f"next_teklif_{req.id}", width="stretch"):
            _run(save + [_call(sv.mark_quote_sent, s, actor, req), _call(sv.advance_req, s, actor, req)], ok="Sonraki aşamaya aktarıldı.", goto=True)
        st.caption("Sıra: PDF'i oluşturun, indirip müşteriye gönderin, sonra 'iletildi' olarak işaretleyin. İçerik değişirse yeni revizyon (-R2) açılır.")

def _panel_karar(s, actor, req, products, editable):
    q = pl.quote_for_req(req)
    st.metric("Müşteriye verilen teklif" + (" (KDV hariç)" if req.tax_enabled else " (KDV yok)"), money(q.total, req.currency))
    if req.decision == "onay": st.success("Müşteri teklifi onayladı.")
    _quotes_section(s, actor, req)
    if not editable: return
    c1, c2 = st.columns(2)
    if c1.button("✅ Müşteri onayladı → Sipariş", type="primary", width="stretch", key=f"approve_{req.id}"):
        _run([_call(sv.decide, s, actor, req, True)], ok="Teklif onaylandı, sipariş aşamasına geçildi.", goto=True)
    with c2: reason = _reason_picker("Ret sebebi", SHELVE_REASONS, f"ret_reason_{req.id}")
    if c2.button("⏸️ Müşteri reddetti → Rafa kaldır", width="stretch", key=f"reject_{req.id}"):
        _run([_call(sv.decide, s, actor, req, False, reason)], ok="REQ rafa kaldırıldı.")


def _panel_siparis(s, actor, req, products, editable):
    po_no = st.text_input("Müşteri sipariş referans no (opsiyonel)", value=req.customer_po_no, key=f"po_{req.id}", disabled=not editable,
                          help="Müşterinin kendi sipariş numarası; bizim tedarikçiye açtığımız PO numarasından farklı ve bağımsızdır.")
    approved = st.toggle("Çin ofisine satın alma onayı verildi", value=req.po_approved_at is not None, key=f"poa_{req.id}", disabled=not editable,
                         help="Onaylanınca bizim tedarikçiye açacağımız PO numarası otomatik oluşturulur.")
    if req.po_number: st.caption(f"Satın alma sipariş no (PO): **{req.po_number}**" + (f" · onay: {fmt_dt(req.po_approved_at)}" if req.po_approved_at else ""))
    if not editable: return
    save = [_call(sv.update_fields, s, actor, req, customer_po_no=po_no.strip())]
    if approved != (req.po_approved_at is not None): save.append(_call(sv.set_po_approved, s, actor, req, approved))
    _save_bar(req, save, "Kaydet ve Lojistik'e Aktar →", _advance(s, actor, req), bump=False, key="siparis")


def _panel_lojistik(s, actor, req, products, editable):
    shipments = sv.req_shipments(s, actor, req)
    if shipments:
        st.markdown("**Bağlı kargolar (CRG)**")
        for sh in shipments:
            qty_here = sum(it.qty for it in sh.items if it.req_id == req.id)
            c1, c2 = st.columns([4, 1.4], vertical_alignment="center")
            c1.markdown(f"**{sh.code}** &nbsp;·&nbsp; {sh.logistics_status} &nbsp;·&nbsp; AWB: {sh.awb_no or '-'} &nbsp;·&nbsp; bu REQ'den {qty_here:g} kalem")
            if c2.button("Kargoyu aç →", key=f"gotoship_{req.id}_{sh.id}", width="stretch"):
                st.session_state["open_shipment"] = sh.code
                st.session_state.pop("open_req", None)
                st.switch_page(st.session_state["pages"]["kargo"])
    else:
        st.info("Bu REQ henüz bir kargoya eklenmedi.")
    if st.button("📦 Kargo modülünde ürün ekle / görüntüle →", key=f"kargo_link_{req.id}"):
        st.session_state.pop("open_req", None)
        st.switch_page(st.session_state["pages"]["kargo"])
    st.caption("AWB, taşıyıcı, GÇB, gümrük statüsü ve belgeler (AWB/PL/PI) Kargo modülünde tutulur; birden fazla REQ tek kargoda birleşebilir. "
              "Bu, REQ'in kendi aşama akışını etkilemez.")
    if editable and st.button("✅ Sevkiyat tamamlandı → Teslim aşamasına geç", type="primary", key=f"logi_{req.id}"):
        _run(_advance(s, actor, req), ok="Teslim aşamasına geçildi.", goto=True)


def _deliveries_section(s, actor, req):
    docs = sv.list_deliveries(s, actor, req)
    if not docs: return
    st.markdown("**Teslimat makbuzları**")
    for doc in docs:
        data = json.loads(doc.snapshot)
        c1, c2 = st.columns([4, 1.4], vertical_alignment="center")
        total = sum(r["delivered"] for r in data["rows"])
        c1.markdown(f"**{doc.number}** &nbsp;·&nbsp; {fmt_dt(doc.issued_at)} &nbsp;·&nbsp; {total:g} kalem")
        c2.download_button("📄 PDF indir", data=render_delivery_pdf(data), file_name=f"{doc.number.replace('/', '_')}.pdf",
                           mime="application/pdf", key=f"dl_del_{doc.id}", width="stretch")


def _panel_teslim(s, actor, req, products, editable):
    delivered = {l.id: pl.delivered_qty(req, l.id) for l in req.lines}
    all_delivered = all(delivered[l.id] >= (l.qty or 0) - 1e-9 for l in req.lines)
    if req.status == pl.DONE:
        st.success("REQ tamamlandı.")
        _deliveries_section(s, actor, req)
        return

    st.caption("Teslim edilecek ürünleri ve adetlerini onaylayın; kısmi (ön) teslimat da yapılabilir. Her teslimat için ayrı bir makbuz (OUT/NNNN) oluşur; "
              "tüm ürünler tam teslim edilince REQ tamamlanabilir.")
    df = pd.DataFrame([{"id": l.id, "Ürün": l.name, "Sipariş Edilen": l.qty, "Şimdiye Kadar Teslim": delivered[l.id],
                        "Kalan": (l.qty or 0) - delivered[l.id], "Bu Teslimatta": 0.0} for l in req.lines])
    cfg = {c: st.column_config.NumberColumn(format="%g") for c in ("Sipariş Edilen", "Şimdiye Kadar Teslim", "Kalan")}
    cfg["Bu Teslimatta"] = st.column_config.NumberColumn(min_value=0.0, format="%g", help="Boş/0 = bu makbuza dahil edilmez.")
    order = ["Ürün", "Sipariş Edilen", "Şimdiye Kadar Teslim", "Kalan", "Bu Teslimatta"]
    if editable:
        edited = st.data_editor(df, key=f"deliver_{req.id}_{_ver(req.id)}", hide_index=True, width="stretch", column_order=order,
                                disabled=["Ürün", "Sipariş Edilen", "Şimdiye Kadar Teslim", "Kalan"], column_config=cfg)
        c1, c2 = st.columns(2)
        delivered_by = c1.text_input("Teslim Eden", key=f"delby_{req.id}")
        delivered_to = c2.text_input("Teslim Alan", key=f"delto_{req.id}", value=req.customer.name)
        if st.button("📄 Teslimat Makbuzu Oluştur", key=f"mkdel_{req.id}", type="primary", width="stretch"):
            rows = [{"line_id": r["id"], "qty": r["Bu Teslimatta"]} for r in edited.to_dict("records")]
            _run([_call(sv.create_delivery, s, actor, req, rows, delivered_by, delivered_to)], ok="Teslimat makbuzu oluşturuldu.", bump=True)
    else:
        st.dataframe(df[order], hide_index=True, width="stretch", column_config=cfg)

    _deliveries_section(s, actor, req)

    if not editable: return
    if all_delivered:
        if st.button("✅ Tüm ürünler teslim edildi: REQ'yi tamamla", type="primary", key=f"done_{req.id}"):
            _run(_advance(s, actor, req), ok="REQ tamamlandı.")
    else:
        st.info("Tüm ürünler tam teslim edilince REQ'yi tamamlama düğmesi burada görünecek.")


PANELS = {"talep": _panel_talep, "fiyat": _panel_fiyat, "gumruk": _panel_gumruk, "teklif": _panel_teklif,
          "karar": _panel_karar, "siparis": _panel_siparis, "lojistik": _panel_lojistik, "teslim": _panel_teslim}
