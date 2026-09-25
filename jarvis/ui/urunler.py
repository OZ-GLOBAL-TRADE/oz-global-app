import pandas as pd
import streamlit as st

from jarvis import pipeline as pl, services as sv
from jarvis.db import session_scope
from jarvis.models import Product
from jarvis.ui.common import notify_error, notify_success

PRODUCT_CATEGORIES = pl.PRODUCT_CATEGORIES  # tek kaynak: pipeline.py


def render():
    actor = st.session_state["actor"]
    st.title("Ürünler")
    st.caption("Ürün kataloğu. REQ açarken ürünler buradan seçilir; GTİP kodu gümrük aşamasında referans olur.")
    with session_scope() as s:
        products = sv.list_products(s, actor)
        suppliers = sv.list_partners(s, actor, suppliers=True)
        _table(s, actor, products)
        if actor.role in pl.MANAGE_ROLES: _add_form(s, actor, products, suppliers)


def _table(s, actor, products):
    if not products:
        st.info("Katalogda ürün yok.")
        return
    df = pd.DataFrame([{"id": p.id, "Ürün": p.name, "Kategori": p.category, "GTİP": p.hs_code, "Son Alış": p.last_cost,
                        "Özellikler": p.spec, "Notlar": p.notes} for p in products])
    fields = {"Kategori": "category", "GTİP": "hs_code", "Son Alış": "last_cost", "Özellikler": "spec", "Notlar": "notes"}
    # Gümrükçü yalnızca GTİP kodunu düzenleyebilir.
    locked = ["Ürün"] + ([c for c in fields if c != "GTİP"] if actor.role == pl.CUSTOMS_BROKER else [])
    ver = st.session_state.setdefault("prod_ver", 0)
    edited = st.data_editor(df, key=f"prod_{ver}", hide_index=True, width="stretch", column_order=[c for c in df.columns if c != "id"], disabled=locked,
                            column_config={"Son Alış": st.column_config.NumberColumn(format="%.2f", min_value=0.0)})
    if st.button("💾 Değişiklikleri kaydet", key="prod_save"):
        rows = [{"id": r["id"], **{field: r[label] for label, field in fields.items()}} for r in edited.to_dict("records")]
        try:
            changed = sv.update_records(s, actor, Product, rows)
        except sv.ServiceError as e:
            notify_error(str(e))
        else:
            st.session_state["prod_ver"] = ver + 1
            notify_success(f"{changed} alan güncellendi." if changed else "Değişiklik yok.")
            st.rerun()


def _add_form(s, actor, products, suppliers):
    with st.expander("＋ Yeni ürün ekle"):
        by_supplier = {p.name: p.id for p in suppliers}
        name = st.text_input("Ürün kodu / adı *", key="new_prod_name")
        query = name.strip().lower()
        matches = [p for p in products if query and query in p.name.lower()] if query else []
        if matches:
            st.caption("⚠️ Kataloğda benzer ürün(ler) var; aynı ürünü tekrar eklemeyin:")
            for p in matches[:8]:
                st.caption(f"• **{p.name}** · {p.category or '-'} · GTİP {p.hs_code or '-'}")
        with st.form("add_product", clear_on_submit=True):
            c2, c3 = st.columns([1.5, 1.5])
            category, hs = c2.selectbox("Kategori", PRODUCT_CATEGORIES), c3.text_input("GTİP")
            d1, d2 = st.columns([3, 1.5])
            supplier = d1.selectbox("Varsayılan tedarikçi (opsiyonel)", ["-", *by_supplier])
            last_cost = d2.number_input("Son alış fiyatı", min_value=0.0, step=1.0, format="%.2f")
            spec = st.text_area("Özellikler", height=70)
            if st.form_submit_button("Ürünü kaydet", type="primary"):
                try:
                    p = sv.add_product(s, actor, name=name, category=category, hs_code=hs, spec=spec, last_cost=last_cost or None,
                                       default_supplier_id=by_supplier.get(supplier))
                except sv.ServiceError as e:
                    notify_error(str(e))
                else:
                    st.session_state.pop("new_prod_name", None)
                    st.session_state["prod_ver"] = st.session_state.get("prod_ver", 0) + 1
                    notify_success(f"{p.name} kataloğa eklendi.")
                    st.rerun()
