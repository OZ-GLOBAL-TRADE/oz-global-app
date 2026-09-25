import os
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, ".env"))
load_dotenv(os.path.join(BASE_DIR, ".env.txt"))


def get_config_val(key: str, default: str = "") -> str:
    val = os.getenv(key)
    if val: return val
    try:
        import streamlit as st
        if key in st.secrets: return str(st.secrets[key])
    except Exception: pass
    return default


# Bulutta Supabase/Postgres bağlantı adresi; yerelde varsayılan SQLite dosyası.
# Yerel varsayılan: jarvis_dev.db. Uygulamanın eski adından (Spark) kalan spark_dev.db varsa, yerel veri kaybolmasın diye o kullanılır.
_LEGACY_DB = os.path.join(BASE_DIR, "spark_dev.db")
_LOCAL_DB = _LEGACY_DB if os.path.exists(_LEGACY_DB) else os.path.join(BASE_DIR, "jarvis_dev.db")
DATABASE_URL = get_config_val("DATABASE_URL", f"sqlite:///{_LOCAL_DB}")
# Canlıya alınana kadar açık (otomatik admin girişi). Kapatmak için JARVIS_DEV_MODE=0.
DEV_MODE = get_config_val("JARVIS_DEV_MODE", "1") == "1"
COMPANY_CODE = "OZ"
COMPANY_NAME = "OZ Global Trade"
COMPANY_LEGAL_NAME = "OZ HAVACILIK ve SAVUNMA SAN. TİC A.Ş."  # teklif PDF başlığı; Ayarlar sayfasından değiştirilir
