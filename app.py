import streamlit as st
import pandas as pd
import pydeck as pdk
import plotly.express as px
import hashlib
from datetime import datetime
from data_engine import fetch_pipeline_data, generate_analytical_metrics, save_cargo_to_sheet, MANAGERS, fetch_supplier_pool, add_supplier_to_sheet
from jarvis_ai import generate_executive_briefing, query_jarvis, intelligent_match_reqs, generate_single_rfq_email

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

def hash_pw(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()

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
    st.markdown("<div style='text-align: center; margin-top: 40px;'>", unsafe_allow_html=True)
    st.image("https://img.icons8.com/fluency/96/artificial-intelligence.png", width=80)
    st.markdown("<h2>OZ GLOBAL TRADE — Lojistik & Karar Destek Ağı</h2>", unsafe_allow_html=True)
    st.markdown("<p style='color: #94A3B8;'>Dış Ticaret personeli kimlik bilgilerinizle giriş yapınız.</p></div>", unsafe_allow_html=True)

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
                else:
                    st.error("❌ Hatalı kullanıcı adı veya şifre!")
    st.stop()

current_user = st.session_state["user_info"]

st.sidebar.image("https://img.icons8.com/fluency/96/artificial-intelligence.png", width=50)
st.sidebar.markdown(f"### 👤 {current_user['name']}")
st.sidebar.caption(f"Yetki: **{current_user['role']}**")

if st.sidebar.button("🚪 Güvenli Çıkış Yap"):
    st.session_state["authenticated"] = False
    st.session_state["user_info"] = None
    st.rerun()

st.sidebar.markdown("---")
if st.sidebar.button("🔄 Lojistik Radarı Güncelle"):
    st.cache_data.clear()
    st.rerun()

with st.sidebar:
    st.markdown("---")
    st.markdown("### 🤖 **Lokal JARVIS**")
    
    if "jarvis_chat_history" not in st.session_state:
        st.session_state["jarvis_chat_history"] = [{"role": "assistant", "content": "Sistemler devrede. Dış ticaret pipeline'ı veya kargo lokasyonları hakkında komut verebilirsiniz.", "audio": None}]

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
                
                try:
                    audio_file_path = generate_jarvis_audio(ai_response)
                except Exception as e:
                    audio_file_path = ""
                    print(f"Ses motoru hatası: {e}")
                    
            except Exception as e:
                ai_response = f"Hata: {e}"
                audio_file_path = ""
                
            st.session_state["jarvis_chat_history"].append({"role": "assistant", "content": ai_response, "audio": audio_file_path})
            st.rerun()

st.title("🌐 OZ GLOBAL TRADE — Tedarik Komuta Merkezi")

if current_user["role"] == "ADMIN":
    selected_mgr = st.sidebar.selectbox("Birim Filtresi:", ["TÜM OFİS"] + MANAGERS)
elif current_user["role"] == "TRADE_MANAGER":
    selected_mgr = current_user["assigned_manager"]
    st.sidebar.caption(f"Sorumlu: **{selected_mgr}**")
else:
    selected_mgr = "TÜM OFİS"

df, metrics = get_cached_trade_data()

if df.empty:
    st.error("Lojistik veri tabanına ulaşılamıyor (Google Sheets bağlantısını kontrol edin).")
    st.stop()

display_df = df if selected_mgr in [None, "TÜM OFİS"] else df[df["Yonetici"] == selected_mgr]
cargos = metrics.get("aktif_kargolar_crg", [])

if current_user["role"] != "CUSTOMS_BROKER":
    col1, col2, col3, col4 = st.columns(4)
    if current_user["role"] == "ADMIN":
        col1.metric("Toplam Portföy (Ciro)", f"${metrics['toplam_ciro_usd']:,.0f}")
        col2.metric("Toplam Brüt Kâr", f"${metrics['toplam_brut_kar_usd']:,.0f}")
        col3.metric("Konsolide Marj", f"%{metrics['konsolide_marj_yuzde']:.1f}")
    else:
        mgr_sales = display_df["Satis_Tutari"].sum()
        mgr_profit = display_df["Brut_Kar"].sum()
        col1.metric("Birim Portföyü (Ciro)", f"${mgr_sales:,.0f}")
        col2.metric("Birim Brüt Kârı", f"${mgr_profit:,.0f}")
        col3.metric("Birim Kâr Marjı", f"%{((mgr_profit / mgr_sales)*100) if mgr_sales > 0 else 0:.1f}")
        
    col4.metric("Aktif Kargo (CRG)", f"{len(cargos)} Sevkiyat")
    st.markdown("---")

def render_cargo_module():
    st.subheader("📦 Aktif Sevkiyat Radarı & Gümrük Masası")

    city_coords = {
        "ISTANBUL": (28.8146, 41.2753),
        "ANKARA": (32.8597, 39.9334),
        "TRANSIT": (70.0, 35.0),
        "SHENZHEN": (114.0579, 22.5431)
    }

    location_groups = {}
    for c in cargos:
        durum = c.get("Guncel_Durum", "")
        konum = c.get("Lojistik_Notu", "").upper()
        
        key = "SHENZHEN"
        color = [245, 158, 11, 255] 
        elevation = 120000

        if "İSTANBUL" in konum or "İGA" in durum.upper() or "ISTANBUL" in konum:
            key = "ISTANBUL"
            color = [239, 68, 68, 255] 
            elevation = 220000
        elif "ANKARA" in konum or "TESLİM" in durum.upper():
            key = "ANKARA"
            color = [16, 185, 129, 255] 
            elevation = 250000
        elif "UÇUŞTA" in durum.upper():
            key = "TRANSIT"
            color = [56, 189, 248, 255] 
            elevation = 170000

        if key not in location_groups:
            location_groups[key] = {"lon": city_coords[key][0], "lat": city_coords[key][1], "color": color, "elevation": elevation, "cargos": []}
        
        location_groups[key]["cargos"].append(f"• {c['CRG_No']} (AWB: {c['AWB_No']})")

    map_data = []
    for idx, (k, data) in enumerate(location_groups.items()):
        offset_lon = data["lon"] + (idx * 0.4)
        offset_lat = data["lat"] + (idx * 0.2)
        cargo_list_str = "<br>".join(data["cargos"])

        map_data.append({
            "Sehir": k,
            "lon": offset_lon,
            "lat": offset_lat,
            "color": data["color"],
            "elevation": data["elevation"],
            "TooltipHTML": f"<b>Lokasyon: {k}</b><br>{cargo_list_str}"
        })

    df_map = pd.DataFrame(map_data)
    if not df_map.empty:
        column_layer = pdk.Layer(
            "ColumnLayer",
            data=df_map,
            get_position=["lon", "lat"],
            get_elevation="elevation",
            elevation_scale=300,
            radius=45000,
            get_fill_color="color",
            pickable=True,
            auto_highlight=True,
        )
        text_layer = pdk.Layer(
            "TextLayer",
            data=df_map,
            get_position=["lon", "lat"],
            get_text="Sehir",
            get_size=15,
            get_color=[255, 255, 255, 255],
            get_alignment_baseline="'bottom'",
        )
        view_state = pdk.ViewState(latitude=35.0, longitude=60.0, zoom=2.3, pitch=40)
        
        st.pydeck_chart(pdk.Deck(
            layers=[column_layer, text_layer], 
            initial_view_state=view_state, 
            tooltip={"html": "{TooltipHTML}"}
        ))
        
    st.markdown("---")

    with st.expander("➕ / 🔄 Kargo & Gümrük Girişi", expanded=False):
        all_available_reqs = sorted(display_df["REQ_No"].unique().tolist())
        action_type = st.radio("İşlem Tipi:", ["Yeni Kargo Ekle", "Mevcut Kargoyu Güncelle"], horizontal=True)
        
        crg_data = {}
        if action_type == "Mevcut Kargoyu Güncelle":
            if not cargos:
                st.warning("Güncellenecek aktif kargo bulunmuyor.")
                selected_crg = ""
            else:
                existing_crgs = [c["CRG_No"] for c in cargos]
                selected_crg = st.selectbox("Güncellenecek CRG Kodunu Seçin:", existing_crgs)
                crg_data = next((c for c in cargos if c["CRG_No"] == selected_crg), {})
        else:
            selected_crg = f"CRG_{len(cargos)+1:02d}"

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
            
            note = st.text_area("Gümrük / Operasyon Notu:", value="")
            if st.form_submit_button("💾 Kaydet ve Bildir"):
                if crg_code:
                    save_cargo_to_sheet(crg_code, selected_reqs, awb_number, carrier_select, cikis_date.strftime("%d.%m.%Y"), durum_select, pl_url, inv_url, guncel_konum, teslimat_tipi, teslimat_adresi, gcb_no, gumruk_statusu)
                    
                    from daily_notifier import send_telegram_message
                    msg = f"📦 **GÜMRÜK & KARGO GÜNCELLEMESİ**\n\n📌 **CRG Kodu:** {crg_code}\n📍 **Mevcut Konum:** {guncel_konum}\n✈️ **Lojistik:** {durum_select}\n🏢 **Gümrük Statüsü:** {gumruk_statusu}\n👤 **İşlem Yapan:** {current_user['name']}"
                    send_telegram_message(msg)
                    
                    st.success("Kaydedildi ve bildirildi!")
                    st.cache_data.clear()
                    st.rerun()

    def get_tracking_link(awb, carrier):
        awb_c = str(awb).replace(" ", "").strip()
        if "DHL" in carrier: 
            return f"https://www.dhl.com/tr-en/home/tracking/tracking-express.html?submit=1&tracking-id={awb_c}"
        elif "FedEx" in carrier: 
            return f"https://www.fedex.com/en-us/tracking.html?trknbr={awb_c}"
        elif "UPS" in carrier: 
            return f"https://www.ups.com/track?tracknum={awb_c}"
        elif "Turkish" in carrier: 
            return f"https://www.turkishcargo.com/en/cargo-tracking?AWB={awb_c}"
        return "#"

    for crg in cargos:
        with st.container(border=True):
            konum_str = crg.get('Lojistik_Notu', '')
            location_badge = f"<span class='neon-location'>📍 Mevcut Konum: {konum_str}</span>" if konum_str and konum_str != "-" else "<span class='neon-location' style='background:#1F2937; color:#9CA3AF!important; border-color:#4B5563;'>📍 Mevcut Konum: Bekleniyor</span>"

            st.markdown(f"### 📦 **{crg['CRG_No']}** — AWB: `{crg['AWB_No']}` ({crg['Tasiyici']}) &nbsp;&nbsp; {location_badge}", unsafe_allow_html=True)
            
            if current_user["role"] == "CUSTOMS_BROKER":
                st.markdown(f"**Tarih:** {crg['Cikis_Tarihi']} | **Lojistik:** `{crg['Guncel_Durum']}`")
            else:
                st.markdown(f"**Tarih:** {crg['Cikis_Tarihi']} | **Maliyet:** `${crg.get('Toplam_Maliyet_USD', 0):,.2f}` | **Lojistik:** `{crg['Guncel_Durum']}`")
            
            st.markdown(f"**Gümrük Statüsü:** `{crg.get('Gumruk_Statusu', 'Bekliyor')}` | **GÇB No:** {crg.get('GCB_No', '-')} | **Teslimat:** {crg.get('Teslimat_Tipi', '-')} ({crg.get('Teslimat_Adresi', '-')})")
            
            if current_user["role"] != "CUSTOMS_BROKER":
                for req in crg.get("REQ_Detaylari", []):
                    st.markdown(f"<div class='req-item'><b>{req.get('req_no')}</b> — {req.get('musteri')} | Maliyet: <b>${req.get('maliyet'):,.2f}</b></div>", unsafe_allow_html=True)
            
            btn_html = ""
            trk_link = get_tracking_link(crg["AWB_No"], crg["Tasiyici"])
            if trk_link != "#": 
                btn_html += f'<a href="{trk_link}" target="_blank" class="doc-link" style="background-color:#F59E0B; color:#000!">🌍 Canlı Takip (Web)</a>'
            if crg.get("Packing_List_URL"): btn_html += f'<a href="{crg["Packing_List_URL"]}" target="_blank" class="doc-link">📄 Packing List</a>'
            if crg.get("Fatura_URL"): btn_html += f'<a href="{crg["Fatura_URL"]}" target="_blank" class="doc-link">🧾 Fatura</a>'
            if btn_html: st.markdown(f"<div style='margin-top:10px;'>{btn_html}</div>", unsafe_allow_html=True)

if current_user["role"] == "CUSTOMS_BROKER":
    render_cargo_module()
else:
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📊 Konsolide Dashboard", "📈 Tedarik & Kategori Matrisi",
        "📦 Kargo & Gümrük Masası", "📋 Detaylı REQ Pipeline",
        "📇 Tedarikçi İstihbarat Ağı"
    ])
    
    with tab1:
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("Aşama Bazlı Ortalama Süreler")
            stages_df = pd.DataFrame(list(metrics["asama_ortalamalari"].items()), columns=["Aşama", "Ortalama Gün"])
            st.plotly_chart(px.bar(stages_df, x="Aşama", y="Ortalama Gün", text_auto=".1f", color="Ortalama Gün", color_continuous_scale="Blues"), use_container_width=True)
        with c2:
            st.subheader("Yönetici Bazlı Ciro & Kâr")
            mgr_df = pd.DataFrame(metrics["yonetici_ozetleri"])
            st.plotly_chart(px.bar(mgr_df, x="Yonetici", y=["Satis_Tutari", "Brut_Kar"], barmode="group"), use_container_width=True)

        st.subheader("📝 Jarvis Günlük Operasyon Brifingi")
        b_col1, b_col2 = st.columns([1, 1])
        with b_col1:
            if st.button("⚡ Günlük Yönetici Brifingi Üret", use_container_width=True):
                with st.spinner("Jarvis analiz ediyor..."):
                    st.session_state["trade_briefing"] = generate_executive_briefing(metrics)
        with b_col2:
            if st.button("📲 Brifingi Telegram'a İlet", use_container_width=True):
                with st.spinner("Telegram'a gönderiliyor..."):
                    from daily_notifier import send_telegram_message
                    current_b = st.session_state.get("trade_briefing") or generate_executive_briefing(metrics)
                    st.session_state["trade_briefing"] = current_b
                    msg_text = f"🌐 OZ GLOBAL TRADE — GÜNLÜK YÖNETİCİ BRİFİNGİ\n\n{current_b}"
                    if send_telegram_message(msg_text): st.success("✅ İletildi!")
                    else: st.error("❌ Gönderim başarısız.")

        if "trade_briefing" in st.session_state and st.session_state["trade_briefing"]:
            with st.container(border=True):
                st.markdown(st.session_state["trade_briefing"])
                
    with tab2:
        cat_df = pd.DataFrame(metrics.get("kategori_analitigi", []))
        if not cat_df.empty:
            g1, g2 = st.columns(2)
            with g1: st.plotly_chart(px.bar(cat_df, x="Kategori", y="Satis_Tutari", color="Kar_Marji", text_auto="$.2s"), use_container_width=True)
            with g2: st.plotly_chart(px.bar(cat_df, x="Kategori", y="Sure_Cin_Fiyatlama", text_auto=".1f", color="Sure_Cin_Fiyatlama"), use_container_width=True)
            st.dataframe(cat_df, use_container_width=True)
            
    with tab3:
        render_cargo_module()
        
    with tab4:
        st.dataframe(display_df, use_container_width=True)

    with tab5:
        df_suppliers = fetch_supplier_pool()
        
        col_form, col_ai = st.columns([1, 1.2])
        
        with col_form:
            st.subheader("➕ Yeni Katalog / Tedarikçi Ekle")
            with st.form("supplier_form", clear_on_submit=True):
                s_kat = st.selectbox("Kategori:", ["Savunma & Havacılık", "Aviyonik & Elektronik", "İtki & Güç Sistemleri", "Makina & Metal Sanayi", "Karbon & Kompozit", "Otomotiv & Araç Parçaları", "Ağır Sanayi & Eğlence", "Tekstil & Medikal", "Gıda & Tarım", "Yapı & İnşaat", "Lojistik & Ambalaj", "Genel Ticaret / Diğer"])
                s_urun = st.text_input("Anahtar Kelimeler / Ürünler (Örn: GEPRC, SIYI, LIDAR, Motor):")
                s_firma = st.text_input("Tedarikçi Firma Adı:")
                s_ulke = st.text_input("Ülke / Bölge:")
                
                sc1, sc2 = st.columns(2)
                s_kisi = sc1.text_input("İletişim Kişisi:")
                s_mail = sc2.text_input("E-Posta:")
                s_not = st.text_area("Termin Süresi & Notlar:")
                
                if st.form_submit_button("💾 Havuza Kaydet"):
                    add_supplier_to_sheet(s_kat, s_urun, s_firma, s_ulke, s_kisi, s_mail, s_not)
                    st.success("Tedarikçi havuza eklendi!")
                    st.cache_data.clear()
                    st.rerun()
                    
            with st.expander("📂 Mevcut Tedarikçi Havuzu"):
                st.dataframe(df_suppliers, use_container_width=True)
        
        with col_ai:
            st.subheader("🧠 Akıllı REQ Eşleştirme (Jarvis Semantic)")
            st.markdown("Müşteriden gelen karmaşık ürün listesini (marka ve model kodlarıyla birlikte) buraya yapıştırın. Jarvis havuzla akıllı eşleştirme yapsın.")
            req_input = st.text_area("Talep (REQ) Listesi:", height=150, placeholder="Örn:\n2 EFT E410P Only Propellers set\n8 GEPRC GR1404 4500KV Motor\n11 TF02-PRO (LIDAR)")
            
            if st.button("⚡ Akıllı Eşleştirme Analizi Yap", use_container_width=True):
                if req_input and not df_suppliers.empty:
                    with st.spinner("Jarvis teknik özellikleri ve markaları analiz ediyor..."):
                        suppliers_json = df_suppliers.to_json(orient="records", force_ascii=False)
                        match_result = intelligent_match_reqs(req_input, suppliers_json)
                        st.session_state["ai_match_result"] = match_result
                elif df_suppliers.empty:
                    st.warning("Tedarikçi havuzunuz şu an boş.")
                else:
                    st.warning("Lütfen talep listesi girin.")

            if "ai_match_result" in st.session_state:
                st.markdown("---")
                st.subheader("🎯 Eşleşme Sonuçları")
                st.markdown(st.session_state["ai_match_result"])
                
                st.markdown("---")
                st.subheader("✉️ Seçmeli RFQ Mail Üretici")
                mail_sup = st.selectbox("Mail Yazılacak Tedarikçi Firma:", df_suppliers["Tedarikçi Firma"].tolist() if not df_suppliers.empty else [])
                mail_item = st.text_input("İlgili Ürün / Kalem Açıklaması:")
                
                if st.button("🚀 Bu Firma İçin İngilizce RFQ Taslağı Oluştur"):
                    if mail_sup and mail_item:
                        sup_row = df_suppliers[df_suppliers["Tedarikçi Firma"] == mail_sup].iloc[0]
                        with st.spinner("Mail yazılıyor..."):
                            draft = generate_single_rfq_email(mail_sup, sup_row.get("İletişim Kişisi", ""), mail_item)
                            st.code(draft, language="markdown")
