import os
import time
import requests
from datetime import datetime
from dotenv import load_dotenv
from data_engine import fetch_pipeline_data, generate_analytical_metrics
from jarvis_ai import generate_executive_briefing

load_dotenv()
if not os.getenv("TELEGRAM_BOT_TOKEN"):
    load_dotenv(".env.txt")

def send_telegram_message(text: str):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id: return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
        return True
    except:
        return False

def check_cargo_location_updates(cargos):
    # Günlük saat 12.00 kontrollerinde konum değişimlerini algılayan mekanizma
    alerts = []
    for c in cargos:
        crg_no = c.get("CRG_No")
        notlar = str(c.get("Lojistik_Notu", "")).upper()
        
        if "İSTANBUL" in notlar or "İGA" in notlar:
            alerts.append(f"📍 **{crg_no}** kargosunun güncel konumu **İSTANBUL** olarak güncellendi. (AWB: {c['AWB_No']})")
        elif "ANKARA" in notlar or "TESLİM" in notlar:
            alerts.append(f"🏁 **{crg_no}** kargosu **ANKARA** hedefine ulaştı!")

    if alerts:
        msg = "⏰ **GÜNLÜK LOJİSTİK KONUM RADARI (12:00)** ⏰\n\n" + "\n".join(alerts)
        send_telegram_message(msg)

def run_daily_briefing():
    print("🔄 E-Tablolar ve Kargo verileri taranıyor...")
    df, raw_cargo_rows = fetch_pipeline_data()
    
    if df.empty: return

    metrics = generate_analytical_metrics(df, raw_cargo_rows)
    cargos = metrics.get("aktif_kargolar_crg", [])
    
    # Konum güncellemelerini tetikle
    check_cargo_location_updates(cargos)
    
    # Günlük brifing
    briefing = generate_executive_briefing(metrics)
    full_message = f"🌐 OZ GLOBAL TRADE — GÜNLÜK YÖNETİCİ BRİFİNGİ\n\n{briefing}"
    send_telegram_message(full_message)

if __name__ == "__main__":
    # Her gün saat 12.00'da otomatik kontrol döngüsü
    print("🤖 Lojistik Otomasyon Zamanlayıcısı Devrede (Her gün 12:00)...")
    while True:
        now = datetime.now()
        if now.hour == 12 and now.minute == 0:
            run_daily_briefing()
            time.sleep(60) # Aynı dakika içinde tekrar tetiklenmeyi önle
        time.sleep(30)
