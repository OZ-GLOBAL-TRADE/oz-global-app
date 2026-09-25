"""Jarvis ERP: yeni giriş noktası (veritabanı tabanlı). Eski Google Sheets uygulaması app.py, geçiş tamamlanana kadar çalışmaya devam eder.
Çalıştırma: streamlit run jarvis_app.py"""
import streamlit as st

from jarvis import pipeline as pl
from jarvis.ui import ayarlar, common, kargo, kisiler, panel, talepler, urunler

st.set_page_config(page_title="Jarvis · OZ Global Trade", page_icon="✨", layout="wide")
common.inject_css()

actor = common.get_actor()
st.session_state["actor"] = actor
common.maybe_play_welcome()

PAGES = {
    "panel": dict(page=panel.render, title="Panel", icon=":material/dashboard:", url_path="panel"),
    "talepler": dict(page=talepler.render, title="Talepler", icon=":material/account_tree:", url_path="talepler"),
    "kargo": dict(page=kargo.render, title="Kargo & Gümrük", icon=":material/local_shipping:", url_path="kargo"),
    "kisiler": dict(page=kisiler.render, title="Kişiler", icon=":material/groups:", url_path="kisiler"),
    "urunler": dict(page=urunler.render, title="Ürünler", icon=":material/inventory_2:", url_path="urunler"),
    "ayarlar": dict(page=ayarlar.render, title="Ayarlar", icon=":material/settings:", url_path="ayarlar"),
}
# Menü rolüne göre: gümrükçü yalnızca kendi işiyle ilgili sayfaları görür.
MENU = {
    pl.CUSTOMS_BROKER: {"Satın Alma & Satış": ["talepler"], "Lojistik": ["kargo"], "Kayıtlar": ["urunler"]},
}
menu = MENU.get(actor.role, {"Ana Menü": ["panel"], "Satın Alma & Satış": ["talepler"], "Lojistik": ["kargo"], "Kayıtlar": ["kisiler", "urunler"]})
if actor.role == pl.ADMIN: menu = {**menu, "Yönetim": ["ayarlar"]}
first = next(iter(menu.values()))[0]
pages = {key: st.Page(default=(key == first), **PAGES[key]) for section in menu.values() for key in section}
st.session_state["pages"] = pages

navigation = st.navigation({section: [pages[k] for k in keys] for section, keys in menu.items()})
common.logout_button()
common.sidebar_open_tasks(actor)
common.sidebar_tools(actor)
common.sidebar_chat(actor)
navigation.run()
