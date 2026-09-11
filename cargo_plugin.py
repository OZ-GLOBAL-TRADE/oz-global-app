import streamlit as st
from data_engine import fetch_pipeline_data, save_cargo_to_sheet
from logistics_tracker import enrich_cargo_data
from daily_notifier import send_telegram_message

def kargo_guncelle_eklentisi(crg_kodu: str, yeni_konum: str, yeni_durum: str) -> str:
    """
    Bir kargonun lojistik durumunu ve mevcut konumunu E-Tablolarda günceller.
    Kullanıcı kargo konumunu veya lojistik durumunu değiştirmek istediğinde bu aracı ÇAĞIR.
    
    Args:
        crg_kodu: Güncellenecek kargo kodu (Örn: CRG_01, CRG_02).
        yeni_konum: Kargonun ulaştığı yeni lokasyon (Örn: ISTANBUL - TURKEY veya ANKARA).
        yeni_durum: Yeni lojistik statüsü (Çıkış Hazırlığında, Uçuşta, İGA Terminali - İndi, Gümrük Muayene, Teslim Edildi).
    """
    df, raw_cargo_rows = fetch_pipeline_data()
    cargos = enrich_cargo_data(raw_cargo_rows, df.to_dict(orient="records"))
    
    target_crg = next((c for c in cargos if c["CRG_No"].upper() == crg_kodu.upper()), None)
    if not target_crg:
        return f"İşlem başarısız: {crg_kodu} kodlu kargo sistemde bulunamadı."
        
    save_cargo_to_sheet(
        crg_no=target_crg["CRG_No"],
        req_list=target_crg["Ilgili_REQler"],
        awb_no=target_crg["AWB_No"],
        carrier=target_crg["Tasiyici"],
        cikis_tarihi=target_crg["Cikis_Tarihi"],
        durum=yeni_durum,
        packing_url=target_crg.get("Packing_List_URL", ""),
        fatura_url=target_crg.get("Fatura_URL", ""),
        notlar=yeni_konum,
        teslimat_tipi=target_crg.get("Teslimat_Tipi", "Belirtilmedi"),
        teslimat_adresi=target_crg.get("Teslimat_Adresi", ""),
        gcb_no=target_crg.get("GCB_No", "-"),
        gumruk_statusu=target_crg.get("Gumruk_Statusu", "Bekliyor")
    )
    
    st.cache_data.clear()
    
    msg = f"🤖 **JARVIS OTONOM İŞLEM**\n\n📌 **CRG Kodu:** {target_crg['CRG_No']}\n📍 **Yeni Konum:** {yeni_konum}\n✈️ **Yeni Durum:** {yeni_durum}\n👤 **Tetikleyen:** JARVIS AI"
    send_telegram_message(msg)
    
    return f"{crg_kodu} için yeni konum {yeni_konum} ve durum {yeni_durum} olarak başarıyla kaydedildi ve yetkililere bildirildi."

# Sistemin tarayacağı ana araç
plugin_tool = kargo_guncelle_eklentisi