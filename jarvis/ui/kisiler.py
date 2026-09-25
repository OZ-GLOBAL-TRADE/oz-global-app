import pandas as pd
import streamlit as st

from jarvis import pipeline as pl, services as sv
from jarvis.db import session_scope
from jarvis.models import Partner
from jarvis.ui.common import notify_error, notify_success

CUSTOMER_KINDS, SUPPLIER_CATEGORIES = pl.CUSTOMER_KINDS, pl.SUPPLIER_CATEGORIES  # tek kaynak: pipeline.py

# görünen sütun -> Partner alanı (düzenlenebilir olanlar)
CUSTOMER_COLUMNS = {"Sektör": "kind", "Vergi No": "tax_no", "Adres": "address", "E-posta": "email", "Telefon": "phone", "Notlar": "notes"}
SUPPLIER_COLUMNS = {"Kategori": "category", "Anahtar Kelimeler": "keywords", "Ülke": "country", "E-posta": "email", "Telefon": "phone", "Notlar": "notes"}


def render():
    actor = st.session_state["actor"]
    st.title("Kişiler")
    st.caption("Müşteri ve tedarikçi kayıtları. REQ açarken müşteriler buradan seçilir; Jarvis tedarikçi taramasını bu havuzdan yapar.")
    tab_customers, tab_suppliers = st.tabs(["Müşteriler", "Tedarikçiler"])
    with session_scope() as s:
        customers = sv.list_partners(s, actor, customers=True)
        suppliers = sv.list_partners(s, actor, suppliers=True)
        with tab_customers: _customers(s, actor, customers)
        with tab_suppliers: _suppliers(s, actor, suppliers)


def _table(s, actor, partners, columns: dict, extra: dict, key: str):
    """Düzenlenebilir tablo. columns: görünen ad -> alan, extra: salt okunur ek sütunlar."""
    if not partners:
        st.info("Kayıt yok.")
        return
    df = pd.DataFrame([{"id": p.id, "Ad": p.name, **{label: fn(p) for label, fn in extra.items()},
                        **{label: getattr(p, field) for label, field in columns.items()}} for p in partners])
    order = [c for c in df.columns if c != "id"]
    ver = st.session_state.setdefault(f"{key}_ver", 0)
    edited = st.data_editor(df, key=f"{key}_{ver}", hide_index=True, width="stretch", column_order=order,
                            disabled=["Ad", *extra])
    if st.button("💾 Değişiklikleri kaydet", key=f"{key}_save"):
        rows = [{"id": r["id"], **{field: r[label] for label, field in columns.items()}} for r in edited.to_dict("records")]
        try:
            changed = sv.update_records(s, actor, Partner, rows)
        except sv.ServiceError as e:
            notify_error(str(e))
        else:
            st.session_state[f"{key}_ver"] = ver + 1
            notify_success(f"{changed} alan güncellendi." if changed else "Değişiklik yok.")
            st.rerun()


def _customers(s, actor, customers):
    _table(s, actor, customers, CUSTOMER_COLUMNS, {"Kod": lambda p: p.short_code, "Son REQ No": lambda p: p.req_seq}, "cust")
    if actor.role not in pl.MANAGE_ROLES: return
    with st.expander("＋ Yeni müşteri ekle"):
        with st.form("add_customer", clear_on_submit=True):
            c1, c2, c3 = st.columns([3, 1.3, 1.5])
            name, code = c1.text_input("Müşteri adı *"), c2.text_input("Kısa kod", help="Boşsa otomatik önerilir (örn. Altınay → ALTN). REQ kodu: KOD_REQ_01")
            seq = c3.number_input("Son REQ no", min_value=0, step=1, help="Odoo'da bu müşteri için kullanılan son numara; yeni kodlar buradan devam eder.")
            d1, d2, d3 = st.columns(3)
            kind, tax_no, phone = d1.selectbox("Sektör", CUSTOMER_KINDS), d2.text_input("Vergi No"), d3.text_input("Telefon")
            email, address = st.text_input("E-posta"), st.text_area("Adres", height=70)
            if st.form_submit_button("Müşteriyi kaydet", type="primary"):
                try:
                    p = sv.add_partner(s, actor, name=name, is_customer=True, short_code=code, req_seq=int(seq), kind=kind, tax_no=tax_no, phone=phone, email=email, address=address)
                except sv.ServiceError as e:
                    notify_error(str(e))
                else:
                    st.session_state["cust_ver"] = st.session_state.get("cust_ver", 0) + 1
                    notify_success(f"{p.name} eklendi (kod: {p.short_code}).")
                    st.rerun()


def _suppliers(s, actor, suppliers):
    _table(s, actor, suppliers, SUPPLIER_COLUMNS, {}, "supp")
    if actor.role not in pl.MANAGE_ROLES: return
    with st.expander("＋ Yeni tedarikçi ekle"):
        with st.form("add_supplier", clear_on_submit=True):
            c1, c2 = st.columns([3, 2])
            name, category = c1.text_input("Tedarikçi firma adı *"), c2.selectbox("Kategori", SUPPLIER_CATEGORIES)
            keywords = st.text_input("Anahtar kelimeler", help="Jarvis'in ürün eşleştirmesi için (örn. Motor, ESC, Pervane)")
            d1, d2, d3 = st.columns(3)
            country, email, phone = d1.text_input("Ülke"), d2.text_input("E-posta"), d3.text_input("Telefon")
            notes = st.text_input("Notlar / tahmini termin")
            if st.form_submit_button("Tedarikçiyi kaydet", type="primary"):
                try:
                    p = sv.add_partner(s, actor, name=name, is_supplier=True, category=category, keywords=keywords, country=country, email=email, phone=phone, notes=notes)
                except sv.ServiceError as e:
                    notify_error(str(e))
                else:
                    st.session_state["supp_ver"] = st.session_state.get("supp_ver", 0) + 1
                    notify_success(f"{p.name} eklendi.")
                    st.rerun()
