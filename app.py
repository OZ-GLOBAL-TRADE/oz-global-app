import streamlit as st
import pandas as pd
import pydeck as pdk
import plotly.express as px
import hashlib
import json
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
    .req-item { background-color: #1E293B; padding: 8px 12px; border-radius: 6px; margin-bottom: 6px; border-left: 3px solid #38BDF8; }
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

# --- SIDEBAR & JARVIS SOHBETİ ---
st.sidebar.image("https://img.icons8.com/fluency/96/artificial-intelligence.png", width=50)
st.sidebar.markdown(f"### 👤 {current_user['name']}")
if st.sidebar.button("🚪 Çıkış Yap"):
    st.session_state["authenticated"] = False
    st.rerun()

st.sidebar.markdown("---")
with st.sidebar:
    st.markdown("### 🤖 **Lokal JARVIS**")
    if "jarvis_chat_history" not in st.session_state:
        st.session_state["jarvis_chat_history"] = [{"role": "assistant", "content": "Sistemler devrede. Dış ticaret pipeline'ı hakkında komut verebilirsiniz.", "audio": None}]

    with st.expander("💬 Jarvis ile Operasyon", expanded=True):
        chat_box = st.container(height=350)
        with chat_box:
            for chat in st.session_state["jarvis_chat_history"]:
                if chat["role"] == "user":
                    st.markdown(f"<div style='text-align: right; background: #1E293B; padding: 8px 12px; border-radius: 10px; margin: 6px 0; color: #38BDF8; font-size: 13px;'><b>Sen:</b> {chat['content']}</div>", unsafe_allow_html=True)
                else:
                    st.markdown(f"<div style='text-align: left; background: #0F172A; border: 1px solid #334155; padding: 8px 12px; border-radius: 10px; margin: 6px 0; color: #F1F5F9; font-size: 13px;'><b>Jarvis:</b> {chat['content']}</div>", unsafe_allow_html=True)
                    if chat.get("audio"):
                        is_last = (chat == st.session_state["jarvis_chat_history"][-1])
                        st.audio(chat["audio"], format="audio/mp3", autoplay=is_last)
                        
        st.markdown("<hr style='margin: 10px 0;'>", unsafe_allow_html=True)
        user_msg = st.chat_input("Jarvis'e komut ver...", key="sidebar_chat_input")

        if user_msg:
            st.session_state["jarvis_chat_history"].append({"role": "user", "content": user_msg, "audio": None})
            try:
                df_tr, metrics_tr = get_cached_trade_data()
                ai_response = query_jarvis(user_msg, current_user["role"], metrics_tr, df_tr, "OZ GLOBAL TRADE")
                audio_file_path = generate_jarvis_audio(ai_response)
            except Exception as e:
                ai_response = f"Hata: {e}"
                audio_file_path = ""
                
            st.session_state["jarvis_chat_history"].append({"role": "assistant", "content": ai_response, "audio": audio_file_path})
            st.rerun()

st.title("🌐 OZ GLOBAL TRADE — Tedarik Komuta Merkezi")
df, metrics = get_cached_trade_data()

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📊 Konsolide Dashboard", "📈 Analitik",
    "📦 Kargo & Gümrük", "🚀 Master Pipeline (ERP)",
    "📇 Tedarikçi İstihbaratı"
])

# TAB 1: KONSOLİDE DASHBOARD
with tab1:
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Aşama Bazlı Ortalama Süreler")
        stages_df = pd.DataFrame(list(metrics["asama_ortalamalari"].items()), columns=["Aşama", "Ortalama Gün"])
        st.plotly_chart(px.bar(stages_df, x="Aşama", y="Ortalama Gün", text_auto=".1f", color="Ortalama Gün", color_continuous_scale="Blues"), use_container_width=True)
    with c2:
        st.subheader("Yönetici Bazlı Ciro & Kâr")
        mgr_df = pd.DataFrame(metrics["yonetici_ozetleri"])
        if not mgr_df.empty:
            st.plotly_chart(px.bar(mgr_df, x="Yonetici", y=["Satis_Tutari", "Brut_Kar"], barmode="group"), use_container_width=True)

# TAB 2: ANALİTİK
with tab2:
    cat_df = pd.DataFrame(metrics.get("kategori_analitigi", []))
    if not cat_df.empty:
        g1, g2 = st.columns(2)
        with g1: st.plotly_chart(px.bar(cat_df, x="Kategori", y="Satis_Tutari", color="Kar_Marji", text_auto="$.2s"), use_container_width=True)
        with g2: st.plotly_chart(px.bar(cat_df, x="Kategori", y="Sure_Cin_Fiyatlama", text_auto=".1f", color="Sure_Cin_Fiyatlama"), use_container_width=True)
        st.dataframe(cat_df, use_container_width=True)

# TAB 3: KARGO & GÜMRÜK
with tab3:
    st.info("Kargo ve Gümrük haritası aktif.")
    # Kargo içeriği çok uzun olduğu için MVP'de yer kaplamaması adına daraltıldı, isterseniz kargo radarını buraya tekrar dahil edebiliriz.

# TAB 4: YENİ MASTER PIPELINE (ODOO-KILLER)
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
                # DİKKAT: Ürünlerin alt alta girildiği çoklu giriş alanı
                icerik = st.text_area("İçerik (Her satıra BİR ürün yazın):", placeholder="Örn:\nFLYCOLOR 120A ESC\n208cc Boxer Motor")
                
                if st.form_submit_button("🔥 Talebi Pipeline'a At"):
                    if req_kodu and icerik:
                        add_master_pipeline_record(req_kodu, musteri, icerik, "1. Fiyat Araştırması")
                        st.success("Talep başarıyla açıldı!")
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error("Lütfen REQ Kodu ve İçerik giriniz.")

        st.markdown("### 📋 Aktif Süreçler")
        if not df_pipe.empty:
            for idx, row in df_pipe.iterrows():
                kodu = row.get("REQ Kodu", f"REQ_{idx}")
                statu = row.get("Statü", "Bekliyor")
                
                if st.button(f"📌 {kodu} | {statu}", key=f"req_{idx}", use_container_width=True):
                    st.session_state["selected_req"] = row.to_dict()
        else:
            st.info("Aktif talep yok.")

    with col_detail:
        if st.session_state["selected_req"]:
            req = st.session_state["selected_req"]
            req_kodu = req.get("REQ Kodu")
            mevcut_statu = req.get("Statü", "1. Fiyat Araştırması")
            
            st.markdown(f"### ⚙️ Yönetim Paneli: `{req_kodu}`")
            st.caption(f"🏢 **Müşteri:** {req.get('Müşteri')} | 🗓️ **Son Güncelleme:** {req.get('Son Güncelleme')}")
            
            # --- GÖRSEL AŞAMA (STEPPER) ÇUBUĞU ---
            stages = ["1. Fiyat Araştırması", "2. Fiyatlama & Marj", "3. Müşteri Onayı", "4. Sipariş & Lojistik", "5. Tamamlandı"]
            step_cols = st.columns(len(stages))
            current_idx = stages.index(mevcut_statu) if mevcut_statu in stages else 0
            
            for i, stage in enumerate(stages):
                with step_cols[i]:
                    if i < current_idx:
                        st.markdown(f"<div style='text-align:center; color:#10B981; font-weight:bold; border-bottom:3px solid #10B981; padding-bottom:5px;'>✔️<br>{stage}</div>", unsafe_allow_html=True)
                    elif i == current_idx:
                        st.markdown(f"<div style='text-align:center; color:#38BDF8; font-weight:bold; border-bottom:3px solid #38BDF8; padding-bottom:5px;'>📍<br>{stage}</div>", unsafe_allow_html=True)
                    else:
                        st.markdown(f"<div style='text-align:center; color:#64748B; border-bottom:3px solid #334155; padding-bottom:5px;'>⚪<br>{stage}</div>", unsafe_allow_html=True)
            
            st.markdown("<br>", unsafe_allow_html=True)
            
            # --- ÜRÜN BAZLI FİYATLANDIRMA FORMU ---
            with st.form(f"update_form_{req_kodu}"):
                # İçeriği satır satır ayırarak ürün listesi oluştur (Boş satırları at)
                raw_icerik = req.get('İçerik / Ürün', '')
                items = [x.strip() for x in str(raw_icerik).split('\n') if x.strip()]
                
                # Kayıtlı fiyatları JSON'dan çek
                try: saved_costs = json.loads(req.get('Ürün Maliyetleri', '{}'))
                except: saved_costs = {}

                st.markdown("#### 📦 Ürün Bazlı Maliyetler (Alış Fiyatları)")
                item_costs = {}
                
                if items:
                    for item in items:
                        default_val = float(saved_costs.get(item, 0.0))
                        item_costs[item] = st.number_input(f"Ürün: {item} ($):", value=default_val, format="%.2f", min_value=0.0)
                else:
                    st.info("Bu talepte listelenmiş ürün bulunmuyor.")

                st.markdown("---")
                c1, c2 = st.columns(2)
                
                def_loj = float(str(req.get("Gümrük Lojistik", "0")).replace("$", "").replace(",", ""))
                def_marj = float(str(req.get("Kâr Marjı", "20")).replace("%", ""))
                
                lojistik = c1.number_input("Gümrük & Lojistik Masrafı ($):", value=def_loj, format="%.2f")
                marj = c2.number_input("Kâr Marjı (%):", value=def_marj, format="%.1f")
                
                st.markdown("**İşlem Menüsü:**")
                next_stage = st.selectbox("Süreci Nereye Taşıyacaksınız?", stages, index=current_idx)
                
                if st.form_submit_button("🚀 Kaydet ve Durumu Güncelle", use_container_width=True):
                    # Toplam alış maliyetini sistem tüm ürünleri toplayarak otomatik hesaplar
                    toplam_alis = sum(item_costs.values())
                    toplam_maliyet = toplam_alis + lojistik
                    nihai_teklif = toplam_maliyet * (1 + (marj / 100))
                    
                    # Güncellenen verileri veritabanına gönder
                    urunler_json_str = json.dumps(item_costs, ensure_ascii=False)
                    update_pipeline_statu(
                        req_kodu, 
                        f"{toplam_alis:.2f}", 
                        f"{lojistik:.2f}", 
                        f"{marj}", 
                        f"{nihai_teklif:.2f}", 
                        next_stage, 
                        urunler_json_str
                    )
                    
                    st.success(f"Başarılı! Toplam Alış: ${toplam_alis:,.2f} | Yeni Teklif: ${nihai_teklif:,.2f}")
                    st.session_state["selected_req"] = None # Paneli temizle
                    st.cache_data.clear()
                    st.rerun()
                    
        else:
            st.info("👈 Yönetmek veya aşamasını değiştirmek istediğiniz REQ'e sol listeden tıklayın.")

# TAB 5: TEDARİKÇİ İSTİHBARATI
with tab5:
    df_suppliers = fetch_supplier_pool()
    col_form, col_ai = st.columns([1, 1.3])
    
    with col_form:
        st.subheader("➕ Yeni Tedarikçi Ekle")
        with st.form("supplier_form", clear_on_submit=True):
            s_kat = st.selectbox("Kategori:", ["Savunma", "Elektronik", "İtki & Güç", "Diğer"])
            s_urun = st.text_input("Anahtar Kelimeler (Örn: Motor, ESC):")
            s_firma = st.text_input("Tedarikçi Firma Adı:")
            sc1, sc2 = st.columns(2)
            s_mail = sc1.text_input("E-Posta:")
            s_ulke = sc2.text_input("Ülke:")
            if st.form_submit_button("Havuza Kaydet"):
                add_supplier_to_sheet(s_kat, s_urun, s_firma, s_ulke, "-", s_mail, "-")
                st.success("Tedarikçi eklendi!")
                st.cache_data.clear()
                st.rerun()

    with col_ai:
        st.subheader("⚡ Otonom REQ Eşleştirme")
        req_input = st.text_area("Talep (REQ) Listesini Yapıştırın:", height=140)
        
        if st.button("🚀 Eşleştir ve Gmail RFQ Oluştur", use_container_width=True):
            if req_input and not df_suppliers.empty:
                with st.spinner("Tedarikçiler taranıyor..."):
                    suppliers_json = df_suppliers.to_json(orient="records", force_ascii=False)
                    match_results, err_msg = intelligent_match_and_draft_rfqs(req_input, suppliers_json)
                    if err_msg: st.error(err_msg)
                    else: st.session_state["rfq_match_list"] = match_results

        if "rfq_match_list" in st.session_state and st.session_state["rfq_match_list"]:
            st.markdown("---")
            for item in st.session_state["rfq_match_list"]:
                st.markdown(f"**{item.get('talep')}** -> {item.get('tedarikci')} ({item.get('eposta')})")
