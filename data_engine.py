import os
import json
import gspread
import pandas as pd
import streamlit as st
from datetime import datetime
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

try:
    from logistics_tracker import enrich_cargo_data, detect_carrier
except ImportError:
    def enrich_cargo_data(raw, records): return []
    def detect_carrier(awb): return "Otomatik Algıla"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))
load_dotenv(os.path.join(BASE_DIR, ".env.txt"))

MANAGERS = ["EREN MEMİŞOĞLU", "BEYZA YAZAR", "EREN ZORMAN", "ZERRİN ÖZ"]

def get_config_val(key: str, default: str = "") -> str:
    val = os.getenv(key)
    if val: return val
    try:
        if hasattr(st, "secrets") and key in st.secrets: return str(st.secrets[key])
    except Exception: pass
    return default

SPREADSHEET_KEY = get_config_val("SPREADSHEET_KEY", "1uNEFwXCZgfjmg6V49cOKGfLiM5h-JhnKu1b0n494ZEg")

@st.cache_resource(show_spinner=False)
def get_sheets_client():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    if hasattr(st, "secrets") and "gcp_service_account" in st.secrets:
        try:
            creds_dict = dict(st.secrets["gcp_service_account"])
            creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
            return gspread.authorize(creds)
        except Exception as e:
            raise ValueError(f"Streamlit Secrets okundu ancak kimlik doğrulanamadı: {e}")

    sa_path = os.path.join(BASE_DIR, "service_account.json")
    if os.path.exists(sa_path):
        creds = Credentials.from_service_account_file(sa_path, scopes=scopes)
        return gspread.authorize(creds)
        
    raise FileNotFoundError("Google kimlik bilgileri bulunamadı.")

def clean_currency(val):
    if pd.isna(val) or val == "": return 0.0
    if isinstance(val, (int, float)): return float(val)
    val_str = str(val).replace("$", "").replace("₺", "").replace("€", "").replace(" ", "").strip()
    if "." in val_str and "," in val_str:
        if val_str.rfind(",") > val_str.rfind("."): val_str = val_str.replace(".", "").replace(",", ".")
        else: val_str = val_str.replace(",", "")
    elif "," in val_str: val_str = val_str.replace(",", ".")
    elif "." in val_str:
        parts = val_str.split(".")
        if len(parts) > 1 and all(len(p) == 3 for p in parts[1:]): val_str = "".join(parts)
    try: return float(val_str)
    except ValueError: return 0.0

def clean_percent(val):
    if pd.isna(val) or val == "": return 0.0
    if isinstance(val, (int, float)): return float(val)
    val_str = str(val).replace("%", "").replace(" ", "").replace(",", ".").strip()
    try:
        num = float(val_str)
        return num if num <= 1.0 else num / 100.0
    except ValueError: return 0.0

def clean_float(val):
    if pd.isna(val) or val == "": return 0.0
    if isinstance(val, (int, float)): return float(val)
    val_str = str(val).replace("Gün", "").replace("gün", "").replace(" ", "").replace(",", ".").strip()
    try: return float(val_str)
    except ValueError: return 0.0

def detect_category(product_name: str) -> str:
    p = str(product_name).lower()
    if any(k in p for k in ["savunma", "havacılık", "uzay", "askeri", "iha", "siha", "drone"]): return "Savunma & Havacılık"
    elif any(k in p for k in ["pcb", "elektronik", "aviyonik", "datalink", "modül", "çip"]): return "Aviyonik & Elektronik"
    elif any(k in p for k in ["motor", "esc", "batarya", "pervane", "güç"]): return "İtki & Güç Sistemleri"
    elif any(k in p for k in ["cnc", "metal", "çelik", "makina"]): return "Makina & Metal Sanayi"
    elif any(k in p for k in ["kompozit", "karbon", "fiber", "kevlar"]): return "Karbon & Kompozit"
    return "Genel Ticaret / Diğer"

@st.cache_data(ttl=600, show_spinner=False)
def fetch_pipeline_data():
    client = get_sheets_client()
    spreadsheet = client.open_by_key(SPREADSHEET_KEY)
    
    ranges = [f"'{mgr}'!A1:Q30" for mgr in MANAGERS] + ["'KARGOLAR'!A1:O50"]
    try:
        batch_res = spreadsheet.values_batch_get(ranges)
        value_ranges = batch_res.get("valueRanges", [])
    except Exception:
        value_ranges = []

    all_rows = []
    raw_cargo_rows = []

    for idx, mgr in enumerate(MANAGERS):
        if idx < len(value_ranges):
            raw_data = value_ranges[idx].get("values", [])
            if len(raw_data) >= 6:
                for row in raw_data[5:25]:
                    if len(row) >= 14 and row[0].strip() != "" and row[0].strip() != "Örnek":
                        urun_adi = row[2].strip()
                        offset = 1 if len(row) >= 17 else 0
                        all_rows.append({
                            "Yonetici": mgr, "REQ_No": row[0].strip(), "Musteri": row[1].strip(), "Urun": urun_adi,
                            "Tedarikci": row[3].strip() if len(row) >= 17 and row[3].strip() else "Belirtilmedi",
                            "Kategori": detect_category(urun_adi), "Sure_Cin_Iletim": clean_float(row[3 + offset]),
                            "Sure_Cin_Fiyatlama": clean_float(row[4 + offset]), "Sure_Gumruk_Fiyatlama": clean_float(row[5 + offset]),
                            "Sure_Teklif_Iletim": clean_float(row[6 + offset]), "Toplam_Sure": clean_float(row[7 + offset]),
                            "SLA_Durumu": row[8 + offset].strip(), "Pipeline_Durumu": row[9 + offset].strip() if len(row) > (9 + offset) else "",
                            "Alis_Maliyeti": clean_currency(row[10 + offset]), "Lojistik_Maliyeti": clean_currency(row[11 + offset]),
                            "Satis_Tutari": clean_currency(row[12 + offset]), "Toplam_Maliyet": clean_currency(row[13 + offset]),
                            "Brut_Kar": clean_currency(row[14 + offset]) if len(row) > (14 + offset) else 0.0,
                            "Kar_Marji": clean_percent(row[15 + offset]) if len(row) > (15 + offset) else 0.0
                        })

    if len(value_ranges) > len(MANAGERS):
        raw_cargo_rows = value_ranges[len(MANAGERS)].get("values", [])

    return pd.DataFrame(all_rows), raw_cargo_rows

def save_cargo_to_sheet(crg_no, req_list, awb_no, carrier, cikis_tarihi, durum, packing_url, fatura_url, notlar, teslimat_tipi="Belirtilmedi", teslimat_adresi="Merkez Ofis", gcb_no="-", gumruk_statusu="Bekliyor"):
    client = get_sheets_client()
    spreadsheet = client.open_by_key(SPREADSHEET_KEY)
    try: ws = spreadsheet.worksheet("KARGOLAR")
    except:
        ws = spreadsheet.add_worksheet(title="KARGOLAR", rows=1000, cols=20)
        ws.update(range_name="A1:N1", values=[["NO", "CRG KODU", "İÇERDİĞİ REQ'LER", "AWB NUMARASI", "TAŞIYICI FİRMA", "ÇIKIŞ TARİHİ", "DURUMU", "PACKING LİST LİNKİ", "FATURA LİNKİ", "NOTU", "TESLİMAT TİPİ", "TESLİMAT ADRESİ", "GÇB NO", "GÜMRÜK STATÜSÜ"]])

    all_values = ws.get_all_values()
    has_no_col = not (all_values and len(all_values[0]) > 0 and "CRG" in all_values[0][0].upper())
    existing_row_idx = next((idx + 1 for idx, row in enumerate(all_values) if row and (row[1].strip() if has_no_col and len(row) > 1 else row[0].strip()).upper() == str(crg_no).strip().upper()), None)
    target_idx = existing_row_idx if existing_row_idx else len(all_values) + 1

    req_str = ", ".join(req_list) if isinstance(req_list, list) else str(req_list)
    full_row = [str(target_idx - 1) if not existing_row_idx else str(existing_row_idx - 1), str(crg_no).strip(), req_str, str(awb_no).strip(), str(carrier).strip(), str(cikis_tarihi).strip(), str(durum).strip(), str(packing_url).strip(), str(fatura_url).strip(), str(notlar).strip(), str(teslimat_tipi).strip(), str(teslimat_adresi).strip(), str(gcb_no).strip(), str(gumruk_statusu).strip()]
    if not has_no_col: full_row = full_row[1:]

    try:
        ws.update(values=[full_row], range_name=f"A{target_idx}:{chr(64 + len(full_row))}{target_idx}", value_input_option="USER_ENTERED")
    except Exception:
        for i, val in enumerate(full_row): ws.update_acell(f"{chr(65 + i)}{target_idx}", val)

def generate_analytical_metrics(df, raw_cargo_rows):
    if df.empty: 
        return {"toplam_req_sayisi": 0, "toplam_ciro_usd": 0.0, "toplam_maliyet_usd": 0.0, "toplam_brut_kar_usd": 0.0, "konsolide_marj_yuzde": 0.0, "genel_ort_teklif_suresi": 0.0, "asama_ortalamalari": {}, "en_buyuk_darbogaz": "-", "kategori_analitigi": [], "aktif_kargolar_crg": [], "sla_asimlari": [], "dusuk_marjli_talepler": [], "yonetici_ozetleri": []}
    
    total_sales = df["Satis_Tutari"].sum()
    total_profit = df["Brut_Kar"].sum()
    stages = {
        "1. Çin'e İletim": df["Sure_Cin_Iletim"].mean() if not df["Sure_Cin_Iletim"].empty else 0.0, 
        "2. Çin Fiyatlama": df["Sure_Cin_Fiyatlama"].mean() if not df["Sure_Cin_Fiyatlama"].empty else 0.0, 
        "3. Gümrük Fiyatlama": df["Sure_Gumruk_Fiyatlama"].mean() if not df["Sure_Gumruk_Fiyatlama"].empty else 0.0, 
        "4. Marj & Müşteri İletim": df["Sure_Teklif_Iletim"].mean() if not df["Sure_Teklif_Iletim"].empty else 0.0
    }
    
    # Hatanın düzeltildiği kısım: Kar_Marji ve Sure_Cin_Fiyatlama analitik dataframe'e dahil edildi
    cat_df = df.groupby("Kategori").agg({"REQ_No": "count", "Satis_Tutari": "sum", "Toplam_Maliyet": "sum", "Brut_Kar": "sum", "Sure_Cin_Fiyatlama": "mean"}).reset_index()
    cat_df["Kar_Marji"] = (cat_df["Brut_Kar"] / cat_df["Satis_Tutari"]).fillna(0.0)

    return {
        "toplam_req_sayisi": len(df), "toplam_ciro_usd": total_sales, "toplam_maliyet_usd": df["Toplam_Maliyet"].sum(), "toplam_brut_kar_usd": total_profit, 
        "konsolide_marj_yuzde": (total_profit / total_sales * 100) if total_sales > 0 else 0.0, "genel_ort_teklif_suresi": df["Toplam_Sure"].mean() if not df["Toplam_Sure"].empty else 0.0,
        "asama_ortalamalari": stages, "en_buyuk_darbogaz": max(stages, key=stages.get) if stages else "-", 
        "kategori_analitigi": cat_df.to_dict(orient="records"), 
        "aktif_kargolar_crg": enrich_cargo_data(raw_cargo_rows, df.to_dict(orient="records")), "sla_asimlari": [], "dusuk_marjli_talepler": [], 
        "yonetici_ozetleri": df.groupby("Yonetici").agg({"REQ_No": "count", "Satis_Tutari": "sum", "Brut_Kar": "sum"}).reset_index().to_dict(orient="records")
    }

@st.cache_data(ttl=300, show_spinner=False)
def fetch_supplier_pool():
    try:
        data = get_sheets_client().open_by_key(SPREADSHEET_KEY).worksheet("TEDARIKCI_HAVUZU").get_all_values()
        return pd.DataFrame(data[1:], columns=data[0]) if len(data) > 1 else pd.DataFrame(columns=["Kategori", "Anahtar Kelime / Ürün", "Tedarikçi Firma", "Ülke / Bölge", "İletişim Kişisi", "E-Posta", "Tahmini Termin / Notlar"])
    except: return pd.DataFrame(columns=["Kategori", "Anahtar Kelime / Ürün", "Tedarikçi Firma", "Ülke / Bölge", "İletişim Kişisi", "E-Posta", "Tahmini Termin / Notlar"])

def add_supplier_to_sheet(kategori, urunler, firma, ulke, kisi, eposta, notlar):
    client, spreadsheet = get_sheets_client(), get_sheets_client().open_by_key(SPREADSHEET_KEY)
    try: ws = spreadsheet.worksheet("TEDARIKCI_HAVUZU")
    except:
        ws = spreadsheet.add_worksheet(title="TEDARIKCI_HAVUZU", rows=1000, cols=10)
        ws.append_row(["Kategori", "Anahtar Kelime / Ürün", "Tedarikçi Firma", "Ülke / Bölge", "İletişim Kişisi", "E-Posta", "Tahmini Termin / Notlar"])
    ws.append_row([kategori, urunler, firma, ulke, kisi, eposta, notlar])

# --- ODOO-KILLER (TEKİL PIPELINE) FONKSİYONLARI ---

def setup_master_sheets():
    spreadsheet = get_sheets_client().open_by_key(SPREADSHEET_KEY)
    
    try: spreadsheet.worksheet("MUSTERILER")
    except:
        ws = spreadsheet.add_worksheet(title="MUSTERILER", rows=500, cols=3)
        ws.append_row(["Müşteri Adı", "İletişim", "Tip"])
        ws.append_rows([["TİTRA TEKNOLOJİ", "-", "Savunma"], ["ASELSAN", "-", "Savunma"], ["BAYKAR", "-", "Savunma"], ["ROKETSAN", "-", "Savunma"]])

    try: spreadsheet.worksheet("REQ_PIPELINE")
    except:
        ws = spreadsheet.add_worksheet(title="REQ_PIPELINE", rows=1000, cols=10)
        ws.append_row(["REQ Kodu", "Müşteri", "İçerik / Ürün", "Alış Maliyeti", "Gümrük Lojistik", "Kâr Marjı", "Nihai Teklif", "Statü", "Son Güncelleme", "Ürün Maliyetleri"])

@st.cache_data(ttl=5, show_spinner=False)
def fetch_master_pipeline():
    try:
        data = get_sheets_client().open_by_key(SPREADSHEET_KEY).worksheet("REQ_PIPELINE").get_all_values()
        return pd.DataFrame(data[1:], columns=data[0]) if len(data) > 1 else pd.DataFrame(columns=["REQ Kodu", "Müşteri", "İçerik / Ürün", "Alış Maliyeti", "Gümrük Lojistik", "Kâr Marjı", "Nihai Teklif", "Statü", "Son Güncelleme", "Ürün Maliyetleri"])
    except: return pd.DataFrame()

@st.cache_data(ttl=120, show_spinner=False)
def fetch_customers_list():
    try:
        data = get_sheets_client().open_by_key(SPREADSHEET_KEY).worksheet("MUSTERILER").get_all_values()
        return [row[0] for row in data[1:] if row[0]]
    except: return ["Manuel Giriş"]

def add_master_pipeline_record(req_kodu, musteri, icerik, statu):
    get_sheets_client().open_by_key(SPREADSHEET_KEY).worksheet("REQ_PIPELINE").append_row(
        [req_kodu, musteri, icerik, "0.0", "0.0", "20", "0.0", statu, datetime.today().strftime("%d.%m.%Y"), "{}"]
    )

def update_pipeline_statu(req_kodu, alis, lojistik, marj, teklif, yeni_statu, urun_maliyetleri_json):
    """Bulunan REQ satırının tüm maliyet, marj ve JSON değerlerini tek seferde günceller."""
    ws = get_sheets_client().open_by_key(SPREADSHEET_KEY).worksheet("REQ_PIPELINE")
    records = ws.get_all_values()
    
    for idx, row in enumerate(records):
        if len(row) > 0 and row[0].strip() == str(req_kodu).strip():
            row_num = idx + 1
            update_data = [[str(alis), str(lojistik), str(marj), str(teklif), str(yeni_statu), datetime.today().strftime("%d.%m.%Y"), str(urun_maliyetleri_json)]]
            ws.update(range_name=f"D{row_num}:J{row_num}", values=update_data, value_input_option="USER_ENTERED")
            return
