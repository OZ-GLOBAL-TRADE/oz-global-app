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
    setup_master_sheets, fetch_master_pipeline, fetch_customers_list, fetch_products_list, add_customer_db, add_product_db,
    add_master_pipeline_record, update_pipeline_statu
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

st.sidebar.image("https://img.icons8.com/fluency/96/artificial-intelligence.png", width=50)
st.sidebar.markdown(f"### 👤 {current_user['name']}")
st.sidebar.caption(f"Yetki: **{current_user['role']}**")

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

display_df = df if current_user["role"] == "ADMIN" else df[df["Yonetici"] == current_user["assigned_manager"]]
cargos = metrics.get("aktif_kargolar_crg", [])

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📊 Konsolide Dashboard", "📈 Analitik",
    "📦 Kargo & Gümrük", "🚀 Master Pipeline (ERP)",
    "📇 Tedarikçi İstihbaratı"
])

def render_cargo_module():
    st.subheader("📦 Aktif Sevkiyat Radarı & Gümrük Masası")
    city_coords = {"ISTANBUL": (28.8146, 41.2753), "ANKARA": (32.8597, 39.9334), "TRANSIT": (70.0, 35.0), "SHENZHEN": (114.0579, 22.5431)}
    location_groups = {}
    
    for c in cargos:
        durum, konum = c.get("Guncel_Durum", ""), c.get("Lojistik_Notu", "").upper()
        key, color, elevation = "SHENZHEN", [245, 158, 11, 255], 120000
        if "İSTANBUL" in konum or "İGA" in durum.upper() or "ISTANBUL" in konum: key, color, elevation = "ISTANBUL", [239, 68, 68, 255], 220000
        elif "ANKARA" in konum or "TESLİM" in durum.upper(): key, color, elevation = "ANKARA", [16, 185, 129, 255], 250000
        elif "UÇUŞTA" in durum.upper(): key, color, elevation = "TRANSIT", [56, 189, 248, 255], 170000

        if key not in location_groups: location_groups[key] = {"lon": city_coords[key][0], "lat": city_coords[key][1], "color": color, "elevation": elevation, "cargos": []}
        location_groups[key]["cargos"].append(f"• {c['CRG_No']} (AWB: {c['AWB_No']})")

    map_data = []
    for idx, (k, data) in enumerate(location_groups.items()):
        map_data.append({"Sehir": k, "lon": data["lon"] + (idx * 0.4), "lat": data["lat"] + (idx * 0.2), "color": data["color"], "elevation": data["elevation"], "TooltipHTML": f"<b>Lokasyon: {k}</b><br>{'<br>'.join(data['cargos'])}"})

    df_map = pd.DataFrame(map_data)
    if not df_map.empty:
        col_layer = pdk.Layer("ColumnLayer", data=df_map, get_position=["lon", "lat"], get_elevation="elevation", elevation_scale=300, radius=45000, get_fill_color="color", pickable=True, auto_highlight=True)
        txt_layer = pdk.Layer("TextLayer", data=df_map, get_position=["lon", "lat"], get_text="Sehir", get_size=15, get_color=[255, 255, 255, 255], get_alignment_baseline="'bottom'")
        st.pydeck_chart(pdk.Deck(layers=[col_layer, txt_layer], initial_view_state=pdk.ViewState(latitude=35.0, longitude=60.0, zoom=2.3, pitch=40), tooltip={"html": "{TooltipHTML}"}))
    st.markdown("---")

    with st.expander("➕ / 🔄 Kargo & Gümrük Girişi", expanded=False):
        all_available_reqs = sorted(display_df["REQ_No"].unique().tolist()) if not display_df.empty else []
        action_type = st.radio("İşlem Tipi:", ["Yeni Kargo Ekle", "Mevcut Kargoyu Güncelle"], horizontal=True)
        
        crg_data = {}
        if action_type == "Mevcut Kargoyu Güncelle":
            if not cargos: st.warning("Güncellenecek aktif kargo bulunmuyor.")
            else:
                existing_crgs = [c["CRG_No"] for c in cargos]
                selected_crg = st.selectbox("Güncellenecek CRG Kodunu Seçin:", existing_crgs)
                crg_data = next((c for c in cargos if c["CRG_No"] == selected_crg), {})
        else: selected_crg = f"CRG_{len(cargos)+1:02d}"

        with st.form("cargo_form", clear_on_submit=False):
            fc1, fc2, fc3 = st.columns(3)
            with fc1:
                crg_code = st.text_input("CRG Kodu:", value=selected_crg)
                default_reqs = [r for r in crg_data.get("Ilgili_REQler", []) if r in all_available_reqs]
                selected_reqs = st.multiselect("İçerdiği REQ Kodları:", options=all_available_reqs, default=default_reqs)
                awb_number = st.text_input("AWB Numarası:", value=crg_data.get("AWB_No", ""))
                carrier_opts = ["Otomatik Algıla", "Turkish Cargo", "DHL Express", "FedEx", "UPS", "Özel Hat"]
                def_c = crg_data.get("Tasiyici", "Otomatik Algıla")
                if def_c not in carrier_opts: carrier_opts.append(def_c)
                carrier_select = st.selectbox("Taşıyıcı:", carrier_opts, index=carrier_opts.index(def_c))
            with fc2:
                try: c_date = datetime.strptime(crg_data.get("Cikis_Tarihi", ""), "%d.%m.%Y").date()
                except: c_date = datetime.today().date()
                cikis_date = st.date_input("Çıkış Tarihi:", value=c_date)
                durum_opts = ["Çıkış Hazırlığında", "🛫 Uçuşta / Yolda", "🛬 İGA Terminali - İndi", "📦 Gümrük Muayene", "✅ Teslim Edildi"]
                def_d = crg_data.get("Guncel_Durum", "Çıkış Hazırlığında")
                if def_d not in durum_opts: durum_opts.append(def_d)
                durum_select = st.selectbox("Lojistik Durumu:", durum_opts, index=durum_opts.index(def_d))
                tes_opts = ["Belirtilmedi", "Kapı Teslim", "Gümrük Teslim"]
                def_t = crg_data.get("Teslimat_Tipi", "Belirtilmedi")
                if def_t not in tes_opts: tes_opts.append(def_t)
                teslimat_tipi = st.selectbox("Teslimat Tipi:", tes_opts, index=tes_opts.index(def_t))
                teslimat_adresi = st.text_input("Teslimat Adresi:", value=crg_data.get("Teslimat_Adresi", "OZ Global Trade Merkez Ofis"))
            with fc3:
                gcb_no = st.text_input("Gümrük Beyanname (GÇB) No:", value=crg_data.get("GCB_No", "-"))
                g_opts = ["Bekliyor", "Evrak Kontrolde", "Muayenede", "Vergi Onay Bekliyor", "Gümrükten Çekildi / Yola Çıktı"]
                def_g = crg_data.get("Gumruk_Statusu", "Bekliyor")
                if def_g not in g_opts: g_opts.append(def_g)
                gumruk_statusu = st.selectbox("Gümrük Statüsü:", g_opts, index=g_opts.index(def_g))
                guncel_konum = st.text_input("Mevcut Konum (Örn: ISTANBUL - TURKEY):", value=crg_data.get("Lojistik_Notu", ""))
                pl_url = st.text_input("Packing List Linki:", value=crg_data.get("Packing_List_URL", ""))
                inv_url = st.text_input("Fatura Linki:", value=crg_data.get("Fatura_URL", ""))
            
            if st.form_submit_button("💾 Kaydet ve Bildir"):
                if crg_code:
                    save_cargo_to_sheet(crg_code, selected_reqs, awb_number, carrier_select, cikis_date.strftime("%d.%m.%Y"), durum_select, pl_url, inv_url, guncel_konum, teslimat_tipi, teslimat_adresi, gcb_no, gumruk_statusu)
                    st.success("Kaydedildi ve bildirildi!")
                    st.cache_data.clear()
                    st.rerun()

    for crg in cargos:
        with st.container(border=True):
            konum_str = crg.get('Lojistik_Notu', '')
            location_badge = f"<span class='neon-location'>📍 Mevcut Konum: {konum_str}</span>" if konum_str and konum_str != "-" else "<span class='neon-location' style='background:#1F2937; color:#9CA3AF!important; border-color:#4B5563;'>📍 Mevcut Konum: Bekleniyor</span>"
            st.markdown(f"### 📦 **{crg['CRG_No']}** — AWB: `{crg['AWB_No']}` ({crg['Tasiyici']}) &nbsp;&nbsp; {location_badge}", unsafe_allow_html=True)
            st.markdown(f"**Tarih:** {crg['Cikis_Tarihi']} | **Lojistik:** `{crg['Guncel_Durum']}`")
            st.markdown(f"**Gümrük Statüsü:** `{crg.get('Gumruk_Statusu', 'Bekliyor')}` | **GÇB No:** {crg.get('GCB_No', '-')} | **Teslimat:** {crg.get('Teslimat_Tipi', '-')} ({crg.get('Teslimat_Adresi', '-')})")
            for req in crg.get("REQ_Detaylari", []):
                st.markdown(f"<div class='req-item'><b>{req.get('req_no')}</b> — {req.get('musteri')} | Maliyet: <b>${req.get('maliyet'):,.2f}</b></div>", unsafe_allow_html=True)

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

# TAB 3: KARGO
with tab3:
    render_cargo_module()

# TAB 4: YENİ MASTER PIPELINE (ODOO-KILLER)
with tab4:
    st.subheader("🎯 Otonom REQ & İş Akışı Döngüsü (The Golden Thread)")
    
    setup_master_sheets()
    df_pipe = fetch_master_pipeline()
    customer_list = fetch_customers_list()
    product_list = fetch_products_list()
    
    if "selected_req" not in st.session_state:
        st.session_state["selected_req"] = None

    col_list, col_detail = st.columns([1.2, 2])
    
    with col_list:
        # VERİTABANI YÖNETİMİ
        with st.expander("⚙️ Veritabanı Yönetimi (Müşteri & Ürün Ekle)", expanded=False):
            t_cust, t_prod = st.tabs(["Müşteri Ekle", "Ürün (Katalog) Ekle"])
            with t_cust:
                with st.form("add_cust_form", clear_on_submit=True):
                    n_ad = st.text_input("Müşteri Adı:")
                    n_tip = st.selectbox("Sektör / Tip:", ["Savunma", "Sivil", "Ticari", "Kurumsal"])
                    if st.form_submit_button("Müşteriyi Kaydet"):
                        add_customer_db(n_ad, "-", n_tip)
                        st.success("Müşteri eklendi!")
                        st.cache_data.clear()
                        st.rerun()
            with t_prod:
                with st.form("add_prod_form", clear_on_submit=True):
                    p_ad = st.text_input("Ürün Kodu veya Adı:")
                    p_kat = st.selectbox("Kategori:", ["Savunma", "Elektronik", "İtki", "Mekanik", "Diğer"])
                    p_fiyat = st.number_input("Tahmini Geçmiş Alış Fiyatı ($):", value=0.0)
                    if st.form_submit_button("Ürünü Kataloğa Ekle"):
                        add_product_db(p_ad, p_kat, "-", p_fiyat, "-")
                        st.success("Ürün eklendi!")
                        st.cache_data.clear()
                        st.rerun()

        # YENİ REQ AÇMA FORMU (Form yapısı kaldırıldı, anında güncelleniyor!)
        with st.expander("➕ Yeni Talep (REQ) Aç", expanded=False):
            st.markdown("Veritabanına kayıtlı Müşteri ve Ürünleri seçiniz.")
            req_kodu = st.text_input("REQ Kodu (Örn: TTRA_REQ_17):", key="new_req_kodu")
            musteri = st.selectbox("Müşteri Seçin:", customer_list, key="new_req_musteri")
            
            secilen_urunler = st.multiselect("Talep Edilen Ürünleri Seçin:", product_list, key="new_req_urunler")
            
            urun_adetleri = {}
            if secilen_urunler:
                st.markdown("📍 **Seçilen Ürünlerin Adetleri:**")
                for urun in secilen_urunler:
                    urun_adetleri[urun] = st.number_input(f"{urun} (Adet):", min_value=1, value=1, key=f"req_yeni_{urun}")
            
            if st.button("🔥 Talebi Pipeline'a At", use_container_width=True):
                if req_kodu and urun_adetleri:
                    add_master_pipeline_record(req_kodu, musteri, urun_adetleri, "1. Fiyat Araştırması")
                    st.success("Talep başarıyla açıldı!")
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.error("Lütfen REQ Kodu giriniz ve en az bir ürün seçiniz.")

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
            
            # --- REQ İÇERİĞİ VE BİRİM FİYAT DÜZENLEME (FORM KALDIRILDI) ---
            with st.container(border=True):
                try: saved_costs = json.loads(req.get('Ürün Maliyetleri', '{}'))
                except: saved_costs = {}

                current_items = list(saved_costs.keys())
                combined_product_list = list(set(product_list + current_items)) # Mevcutlar katalogda olmasa bile kaybolmasın
                
                st.markdown("#### 📦 REQ İçeriğini (Ürünleri) Düzenle")
                active_products = st.multiselect("Talep Edilen Ürünleri Ekle / Çıkar:", combined_product_list, default=current_items, key=f"edit_prod_{req_kodu}")
                
                st.markdown("#### 💵 Ürün Adetleri ve Birim Maliyetleri")
                new_saved_data = {}
                toplam_alis = 0.0
                
                if active_products:
                    for item in active_products:
                        old_info = saved_costs.get(item, {"adet": 1, "fiyat": 0.0})
                        if not isinstance(old_info, dict): 
                            old_info = {"adet": 1, "fiyat": float(old_info)} # Eski veri uyumluluğu
                            
                        c_q, c_p = st.columns([1, 1])
                        n_qty = c_q.number_input(f"{item} - Adet:", value=int(old_info["adet"]), min_value=1, key=f"q_{req_kodu}_{item}")
                        n_prc = c_p.number_input(f"{item} - Birim Alış ($):", value=float(old_info["fiyat"]), format="%.2f", min_value=0.0, key=f"p_{req_kodu}_{item}")
                        
                        new_saved_data[item] = {"adet": n_qty, "fiyat": n_prc}
                        toplam_alis += (n_qty * n_prc)
                else:
                    st.warning("Bu talebe atanmış ürün yok.")

                st.markdown(f"**Toplam Ürün Maliyeti:** <span style='color:#10B981;'>${toplam_alis:,.2f}</span>", unsafe_allow_html=True)
                st.markdown("---")
                
                c1, c2 = st.columns(2)
                def_loj = float(str(req.get("Gümrük Lojistik", "0")).replace("$", "").replace(",", ""))
                def_marj = float(str(req.get("Kâr Marjı", "20")).replace("%", ""))
                
                lojistik = c1.number_input("Gümrük & Lojistik Masrafı ($):", value=def_loj, format="%.2f", key=f"loj_{req_kodu}")
                marj = c2.number_input("Kâr Marjı (%):", value=def_marj, format="%.1f", key=f"marj_{req_kodu}")
                
                st.markdown("**İşlem Menüsü:**")
                next_stage = st.selectbox("Süreci Nereye Taşıyacaksınız?", stages, index=current_idx, key=f"stage_{req_kodu}")
                
                if st.button("🚀 Kaydet ve Durumu Güncelle", use_container_width=True, key=f"save_{req_kodu}"):
                    toplam_maliyet = toplam_alis + lojistik
                    nihai_teklif = toplam_maliyet * (1 + (marj / 100))
                    
                    urunler_json_str = json.dumps(new_saved_data, ensure_ascii=False)
                    guncel_icerik_str = ", ".join([f"{k} ({v['adet']} Adet)" for k, v in new_saved_data.items()])
                    
                    update_pipeline_statu(
                        req_kodu, f"{toplam_alis:.2f}", f"{lojistik:.2f}", f"{marj}", f"{nihai_teklif:.2f}", next_stage, urunler_json_str, guncel_icerik_str
                    )
                    
                    st.success(f"Başarılı! Yeni Teklif Müşteriye Sunulmaya Hazır: ${nihai_teklif:,.2f}")
                    st.session_state["selected_req"] = None
                    st.cache_data.clear()
                    st.rerun()
                    
        else:
            st.info("👈 Yönetmek veya içeriğini değiştirmek istediğiniz REQ'e sol listeden tıklayın.")

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

    # O EFSANEVİ ARAYÜZ GERİ GELDİ!
    with col_ai:
        st.subheader("⚡ Otonom REQ Eşleştirme (Jarvis AI)")
        req_input = st.text_area("Müşteri Talep (REQ) Listesini Yapıştırın:", height=140, placeholder="Örn:\nEFT E410P Only Propellers set\nGEPRC GR1404 4500KV Motor")
        
        if st.button("🚀 Eşleştir ve Gmail RFQ Butonlarını Oluştur", use_container_width=True):
            if req_input and not df_suppliers.empty:
                with st.spinner("Tedarikçiler taranıyor ve Gmail taslakları oluşturuluyor..."):
                    suppliers_json = df_suppliers.to_json(orient="records", force_ascii=False)
                    match_results, err_msg = intelligent_match_and_draft_rfqs(req_input, suppliers_json)
                    
                    if err_msg: st.error(err_msg)
                    elif not match_results: st.warning("Bu ürünler için tedarikçi havuzunda doğrudan eşleşen bir firma bulunamadı.")
                    else: st.session_state["rfq_match_list"] = match_results
            elif df_suppliers.empty: st.warning("Tedarikçi havuzunuz şu an boş.")
            else: st.warning("Lütfen talep listesi girin.")

        if "rfq_match_list" in st.session_state and st.session_state["rfq_match_list"]:
            st.markdown("---")
            results = st.session_state["rfq_match_list"]
            
            # Talebe göre grupla
            grouped = {}
            for item in results:
                t = item.get("talep", "Genel Talep")
                grouped.setdefault(t, []).append(item)

            for product, sups in grouped.items():
                with st.container(border=True):
                    st.markdown(f"#### 🎯 **Talep Kalemi:** `{product}`")
                    
                    for idx, s in enumerate(sups):
                        firma = s.get("tedarikci", "-")
                        email = s.get("eposta", "").strip()
                        kisi = s.get("kisi", "Sales Team")
                        ulke = s.get("ulke", "-")
                        aciklama = s.get("aciklama", "")

                        subject = f"RFQ - Quotation Request for {product} - OZ Global Trade"
                        body = (
                            f"Dear {kisi if kisi else 'Sales Team'},\n\n"
                            f"We are reaching out from OZ Global Trade regarding the procurement of '{product}'.\n\n"
                            f"Could you please provide your official quotation including:\n"
                            f"1. Unit price (EXW / FOB)\n"
                            f"2. Minimum Order Quantity (MOQ)\n"
                            f"3. Estimated production / delivery lead time\n\n"
                            f"We look forward to your prompt response.\n\n"
                            f"Best regards,\n"
                            f"OZ Global Trade Team"
                        )

                        c_info, c_btn = st.columns([3, 1.2])
                        with c_info:
                            st.markdown(f"**🏢 {firma}** ({ulke}) &nbsp;•&nbsp; 👤 *{kisi}*")
                            if email:
                                st.caption(f"📧 `{email}` | 💡 {aciklama}")
                            else:
                                st.caption(f"⚠️ *E-posta kayıtlı değil* | 💡 {aciklama}")
                        
                        with c_btn:
                            if email and "@" in email:
                                gmail_url = f"https://mail.google.com/mail/?view=cm&fs=1&to={urllib.parse.quote(email)}&su={urllib.parse.quote(subject)}&body={urllib.parse.quote(body)}"
                                st.link_button("✉️ Gmail'de Gönder", gmail_url, type="primary", use_container_width=True)
                            else:
                                st.button("❌ E-Posta Yok", disabled=True, use_container_width=True, key=f"dis_{firma}_{product}_{idx}")
                        
                        if idx < len(sups) - 1: st.divider()
