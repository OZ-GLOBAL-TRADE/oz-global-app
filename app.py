import streamlit as st
import pandas as pd
import pydeck as pdk
import plotly.express as px
import hashlib
import urllib.parse
from datetime import datetime

from data_engine import (
    fetch_pipeline_data, generate_analytical_metrics, save_cargo_to_sheet, MANAGERS, fetch_supplier_pool, add_supplier_to_sheet,
    setup_master_sheets, fetch_master_pipeline, fetch_customers_list, add_master_pipeline_record, update_pipeline_statu
)
from jarvis_ai import generate_executive_briefing, query_jarvis, intelligent_match_and_draft_rfqs

try:
    from voice_engine import generate_jarvis_audio
except ImportError:
    def generate_jarvis_audio(text, voice="tr-TR-AhmetNeural"): return ""

st.set_page_config(page_title="OZ GLOBAL TRADE — Operasyon Merkezi", page_icon="🌐", layout="wide")

@st.cache_data(ttl=600, show_spinner=False)
def get_cached_trade_data():
    df, raw_cargo_rows = fetch_pipeline_data()
    metrics = generate_analytical_metrics(df, raw_cargo_rows)
    return df, metrics

st.markdown("""
    <style>
    .badge-status { background-color: #F59E0B; color: #000000; padding: 4px 12px; border-radius: 6px; font-weight: bold; font-size: 13px; display: inline-block; }
    .neon-location { background-color: #064E3B; color: #34D399 !important; border: 1px solid #10B981; padding: 3px 10px; border-radius: 6px; font-weight: bold; font-size: 12px; display: inline-block; box-shadow: 0 0 10px rgba(16, 185, 129, 0.4); animation: pulse 2s infinite; }
    @keyframes pulse { 0% { opacity: 0.8; } 50% { opacity: 1; transform: scale(1.02); } 100% { opacity: 0.8; } }
    .doc-link { background-color: #1E293B; border: 1px solid #475569; color: #38BDF8 !important; padding: 6px 14px; border-radius: 6px; text-decoration: none; font-size: 13px; font-weight: 500; display: inline-block; margin-right: 8px; }
    .doc-link:hover { background-color: #38BDF8; color: #000000 !important; }
    .req-card { background-color: #1E293B; border: 1px solid #334155; border-radius: 10px; padding: 15px; margin-bottom: 10px; cursor: pointer; transition: 0.2s; }
    .req-card:hover { border-color: #38BDF8; box-shadow: 0 0 10px rgba(56, 189, 248, 0.2); }
    .step-active { color: #10B981; font-weight: bold; border-bottom: 3px solid #10B981; padding-bottom: 5px; }
    .step-inactive { color: #64748B; font-weight: 500; border-bottom: 3px solid #334155; padding-bottom: 5px; }
    </style>
""", unsafe_allow_html=True)

def hash_pw(password: str) -> str: return hashlib.sha256(password.encode("utf-8")).hexdigest()

USERS_DB = {
    "yusuf.oz": {"name": "Yusuf Öz", "role": "ADMIN", "assigned_manager": None, "password_hash": hash_pw("OzAdmin2026!")},
    "eren.memisoglu": {"name": "Eren Memişoğlu", "role": "TRADE_MANAGER", "assigned_manager": "EREN MEMİŞOĞLU", "password_hash": hash_pw("OzTrade2026!")},
    "beyza.yazar": {"name": "Beyza Yazar", "role": "TRADE_MANAGER", "assigned_manager": "BEYZA YAZAR", "password_hash": hash_pw("OzTrade2026!")},
    "eren.zorman": {"name": "Eren Zorman", "role": "TRADE_MANAGER", "assigned_manager": "EREN ZORMAN", "password_hash": hash_pw("OzTrade2026!")},
    "zerrin.oz": {"name": "Zerrin Öz", "role": "TRADE_MANAGER", "assigned_manager": "ZERRİN ÖZ", "password_hash": hash_pw("OzTrade2026!")},
    "gumruk.ofis": {"name": "Gümrük Operasyon", "role": "CUSTOMS_BROKER", "assigned_manager": None, "password_hash": hash_pw("Gumruk2026!")}
}

DEV_MODE = True 

if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = DEV_MODE
    st.session_state["user_info"] = USERS_DB["yusuf.oz"] if DEV_MODE else None

if not st.session_state["authenticated"]:
    col_l1, col_l2, col_l3 = st.columns([1, 1.2, 1])
    with col_l2:
        with st.form("login_form"):
            username_input = st.text_input("Kullanıcı Adı:").strip().lower()
            password_input = st.text_input("Şifre:", type="password")
            if st.form_submit_button("🔒 Güvenli Giriş Yap", use_container_width=True):
                user_record = USERS_DB.get(username_input)
                if user_record and user_record["password_hash"] == hash_pw(password_input):
                    st.session_state["authenticated"] = True
                    st.session_state["user_info"] = user_record
                    st.rerun()
                else: st.error("❌ Hatalı kullanıcı adı veya şifre!")
    st.stop()

current_user = st.session_state["user_info"]

st.sidebar.image("https://img.icons8.com/fluency/96/artificial-intelligence.png", width=50)
st.sidebar.markdown(f"### 👤 {current_user['name']}")
if st.sidebar.button("🚪 Çıkış Yap"):
    st.session_state["authenticated"] = False
    st.rerun()

st.sidebar.markdown("---")
with st.sidebar.expander("💬 Jarvis Chat", expanded=False):
    st.info("Jarvis aktif.")

st.title("🌐 OZ GLOBAL TRADE — Tedarik Komuta Merkezi")
df, metrics = get_cached_trade_data()

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📊 Konsolide Dashboard", "📈 Analitik",
    "📦 Kargo & Gümrük", "🚀 Master Pipeline (ERP)",
    "📇 Tedarikçi İstihbaratı"
])

with tab1:
    st.info("Geliştirme aşamasında...")

with tab4:
    st.subheader("🎯 Otonom REQ & İş Akışı Döngüsü (The Golden Thread)")
    
    setup_master_sheets()
    df_pipe = fetch_master_pipeline()
    customer_list = fetch_customers_list()
    
    if "selected_req" not in st.session_state:
        st.session_state["selected_req"] = None

    col_list, col_detail = st.columns([1, 2.2])
    
    with col_list:
        with st.expander("➕ Yeni Talep (REQ) Aç", expanded=False):
            with st.form("new_req_form", clear_on_submit=True):
                req_kodu = st.text_input("REQ Kodu (Örn: TTRA_REQ_17):")
                musteri = st.selectbox("Müşteri Seçin:", customer_list)
                icerik = st.text_input("İçerik (Örn: FLYCOLOR 120A ESC):")
                
                if st.form_submit_button("🔥 Talebi Pipeline'a At"):
                    add_master_pipeline_record(req_kodu, musteri, icerik, "1. Fiyat Araştırması 🔍")
                    st.success("Talep açıldı!")
                    st.cache_data.clear()
                    st.rerun()

        st.markdown("### 📋 Aktif Süreçler")
        if not df_pipe.empty:
            for idx, row in df_pipe.iterrows():
                kodu = row.get("REQ Kodu", f"REQ_{idx}")
                statu = row.get("Statü", "Bekliyor")
                
                # REQ Kartı Butonu
                if st.button(f"📌 {kodu} | {statu}", key=f"req_{idx}", use_container_width=True):
                    st.session_state["selected_req"] = row.to_dict()
        else:
            st.info("Aktif talep yok.")

    with col_detail:
        if st.session_state["selected_req"]:
            req = st.session_state["selected_req"]
            req_kodu = req.get("REQ Kodu")
            mevcut_statu = req.get("Statü", "")
            
            st.markdown(f"### ⚙️ Yönetim Paneli: `{req_kodu}`")
            st.caption(f"🏢 **Müşteri:** {req.get('Müşteri')} | 📦 **İçerik:** {req.get('İçerik / Ürün')} | 🗓️ **Güncelleme:** {req.get('Son Güncelleme')}")
            
            # STEPPER UI (Aşamalar)
            stages = ["1. Fiyat Araştırması 🔍", "2. Fiyatlama & Marj 🧮", "3. Müşteri Onayı ⏳", "4. Sipariş & Lojistik 🚀", "5. Tamamlandı ✅"]
            
            # Bulunduğu aşamayı renklendir
            step_html = "<div style='display: flex; justify-content: space-between; margin: 20px 0;'>"
            for stage in stages:
                cls = "step-active" if stage == mevcut_statu else "step-inactive"
                step_html += f"<div class='{cls}'>{stage.split(' ')[0]}</div>"
            step_html += "</div>"
            st.markdown(step_html, unsafe_allow_html=True)
            
            st.markdown("---")
            
            # Fiyatlandırma Formu
            with st.form(f"update_form_{req_kodu}"):
                c1, c2, c3 = st.columns(3)
                
                def_alis = float(str(req.get("Alış Maliyeti", "0")).replace("$", "").replace(",", ""))
                def_loj = float(str(req.get("Gümrük Lojistik", "0")).replace("$", "").replace(",", ""))
                def_marj = float(str(req.get("Kâr Marjı", "20")).replace("%", ""))
                
                alis = c1.number_input("Alış Maliyeti ($):", value=def_alis, format="%.2f")
                lojistik = c2.number_input("Gümrük & Lojistik ($):", value=def_loj, format="%.2f")
                marj = c3.number_input("Kâr Marjı (%):", value=def_marj, format="%.1f")
                
                st.markdown("<br>", unsafe_allow_html=True)
                
                # Aşama Taşıyıcı Butonlar
                st.markdown("**İşlem Menüsü:**")
                next_stage = st.selectbox("Süreci Nereye Taşıyacaksınız?", stages, index=stages.index(mevcut_statu) if mevcut_statu in stages else 0)
                
                if st.form_submit_button("🚀 Kaydet ve Durumu Güncelle", use_container_width=True):
                    toplam_maliyet = alis + lojistik
                    nihai_teklif = toplam_maliyet * (1 + (marj / 100))
                    
                    update_pipeline_statu(req_kodu, f"{alis:.2f}", f"{lojistik:.2f}", f"{marj}", f"{nihai_teklif:.2f}", next_stage)
                    st.success(f"Başarılı! Yeni Teklif: ${nihai_teklif:,.2f}")
                    
                    st.session_state["selected_req"] = None # Paneli sıfırla
                    st.cache_data.clear()
                    st.rerun()
                    
        else:
            st.info("👈 Yönetmek veya aşamasını değiştirmek istediğiniz REQ'e sol listeden tıklayın.")

with tab5:
    st.info("Tedarikçi ağınız burada.")
