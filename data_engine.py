import os
import gspread
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

# Eğer logistics_tracker dosyanız yoksa hata vermemesi için try-except bloğuna alıyoruz
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
    if any(k in p for k in ["savunma", "havacılık", "uzay", "askeri", "aviation", "aerospace", "defence", "aero", "iha", "siha", "drone"]): return "Savunma & Havacılık"
    elif any(k in p for k in ["pcb", "elektronik", "aviyonik", "datalink", "modül", "rf", "alıcı", "verici", "yazılım", "otomasyon", "sensör", "kamera", "çip"]): return "Aviyonik & Elektronik"
    elif any(k in p for k in ["motor", "esc", "servomotor", "batarya", "pil", "prop", "pervane", "güç", "enerji", "battery"]): return "İtki & Güç Sistemleri"
    elif any(k in p for k in ["cnc", "torna", "freze", "metal", "çelik", "makina", "mekanik", "kalıp", "alüminyum", "titanyum"]): return "Makina & Metal Sanayi"
    elif any(k in p for k in ["kompozit", "karbon", "kanat", "fiber", "tüp", "plaka", "kevlar", "epoksi"]): return "Karbon & Kompozit"
    elif any(k in p for k in ["lastik", "jant", "fren", "amortisör", "dingil", "şasi", "far", "silecek", "otomotiv"]): return "Otomotiv & Araç Parçaları"
    elif any(k in p for k in ["dönme dolap", "ray", "lunapark", "vinç", "redüktör", "dişli", "platform", "konstrüksiyon"]): return "Ağır Sanayi & Eğlence"
    elif any(k in p for k in ["kumaş", "tekstil", "iplik", "çadır", "branda", "maske", "eldiven", "giyim"]): return "Tekstil & Medikal"
    elif any(k in p for k in ["gıda", "tarım", "gübre", "ilaç", "tohum", "sprey"]): return "Gıda & Tarım"
    elif any(k in p for k in ["yapı", "inşaat", "seramik", "çimento", "boya", "malzeme", "boru"]): return "Yapı & İnşaat"
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
                        tedarikci = row[3].strip() if len(row) >= 17 and row[3].strip() else "Belirtilmedi"

                        all_rows.append({
                            "Yonetici": mgr,
                            "REQ_No": row[0].strip(),
                            "Musteri": row[1].strip(),
                            "Urun": urun_adi,
                            "Tedarikci": tedarikci,
                            "Kategori": detect_category(urun_adi),
                            "Sure_Cin_Iletim": clean_float(row[3 + offset]),
                            "Sure_Cin_Fiyatlama": clean_float(row[4 + offset]),
                            "Sure_Gumruk_Fiyatlama": clean_float(row[5 + offset]),
                            "Sure_Teklif_Iletim": clean_float(row[6 + offset]),
                            "Toplam_Sure": clean_float(row[7 + offset]),
                            "SLA_Durumu": row[8 + offset].strip(),
                            "Pipeline_Durumu": row[9 + offset].strip() if len(row) > (9 + offset) else "",
                            "Alis_Maliyeti": clean_currency(row[10 + offset]),
                            "Lojistik_Maliyeti": clean_currency(row[11 + offset]),
                            "Satis_Tutari": clean_currency(row[12 + offset]),
                            "Toplam_Maliyet": clean_currency(row[13 + offset]),
                            "Brut_Kar": clean_currency(row[14 + offset]) if len(row) > (14 + offset) else 0.0,
                            "Kar_Marji": clean_percent(row[15 + offset]) if len(row) > (15 + offset) else 0.0
                        })

    if len(value_ranges) > len(MANAGERS):
        raw_cargo_rows = value_ranges[len(MANAGERS)].get("values", [])

    return pd.DataFrame(all_rows), raw_cargo_rows

def save_cargo_to_sheet(crg_no, req_list, awb_no, carrier, cikis_tarihi, durum, packing_url, fatura_url, notlar, teslimat_tipi="Belirtilmedi", teslimat_adresi="Merkez Ofis", gcb_no="-", gumruk_statusu="Bekliyor"):
    client = get_sheets_client()
    spreadsheet = client.open_by_key(SPREADSHEET_KEY)
    
    try: 
        ws = spreadsheet.worksheet("KARGOLAR")
    except gspread.exceptions.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title="KARGOLAR", rows=1000, cols=20)
        header = ["NO", "CRG KODU", "İÇERDİĞİ REQ'LER", "AWB NUMARASI", "TAŞIYICI FİRMA", "ÇIKIŞ TARİHİ", "DURUMU", "PACKING LİST LİNKİ", "FATURA LİNKİ", "NOTU", "TESLİMAT TİPİ", "TESLİMAT ADRESİ", "GÇB NO", "GÜMRÜK STATÜSÜ"]
        ws.update(range_name="A1:N1", values=[header])

    all_values = ws.get_all_values()
    
    if carrier == "Otomatik Algıla": carrier = detect_carrier(awb_no)
    req_str = ", ".join(req_list) if isinstance(req_list, list) else str(req_list)
    
    has_no_col = not (all_values and len(all_values[0]) > 0 and "CRG" in all_values[0][0].upper())
    existing_row_idx = None

    for idx, row in enumerate(all_values):
        if not row: continue
        code_in_row = row[1].strip() if has_no_col and len(row) > 1 else row[0].strip()
        if code_in_row.upper() == str(crg_no).strip().upper():
            existing_row_idx = idx + 1
            break

    target_idx = existing_row_idx if existing_row_idx else len(all_values) + 1

    try:
        if target_idx > ws.row_count:
            ws.add_rows(max(10, target_idx - ws.row_count + 5))
    except Exception:
        pass

    full_row = [
        str(target_idx - 1) if not existing_row_idx else str(existing_row_idx - 1),
        str(crg_no).strip(), req_str, str(awb_no).strip(), str(carrier).strip(), str(cikis_tarihi).strip(),
        str(durum).strip(), str(packing_url).strip(), str(fatura_url).strip(), str(notlar).strip(),
        str(teslimat_tipi).strip(), str(teslimat_adresi).strip(), str(gcb_no).strip(), str(gumruk_statusu).strip()
    ]

    if not has_no_col: full_row = full_row[1:]

    end_col_letter = chr(64 + len(full_row)) 
    exact_range = f"A{target_idx}:{end_col_letter}{target_idx}"

    try:
        ws.update(values=[full_row], range_name=exact_range, value_input_option="USER_ENTERED")
    except Exception:
        try:
            ws.update(exact_range, [full_row], value_input_option="USER_ENTERED")
        except Exception:
            for i, val in enumerate(full_row):
                ws.update_acell(f"{chr(65 + i)}{target_idx}", val)

def generate_analytical_metrics(df, raw_cargo_rows):
    if df.empty:
        return {"toplam_req_sayisi": 0, "toplam_ciro_usd": 0.0, "toplam_maliyet_usd": 0.0, "toplam_brut_kar_usd": 0.0, "konsolide_marj_yuzde": 0.0, "genel_ort_teklif_suresi": 0.0, "asama_ortalamalari": {}, "en_buyuk_darbogaz": "-", "kategori_analitigi": [], "aktif_kargolar_crg": [], "sla_asimlari": [], "dusuk_marjli_talepler": [], "yonetici_ozetleri": []}

    total_sales = df["Satis_Tutari"].sum()
    total_cost = df["Toplam_Maliyet"].sum()
    total_profit = df["Brut_Kar"].sum()
    avg_margin = (total_profit / total_sales) if total_sales > 0 else 0.0
    
    avg_total_time = df["Toplam_Sure"].mean() if not df["Toplam_Sure"].empty else 0.0
    stages = {
        "1. Çin'e İletim": df["Sure_Cin_Iletim"].mean() if not df["Sure_Cin_Iletim"].empty else 0.0,
        "2. Çin Fiyatlama": df["Sure_Cin_Fiyatlama"].mean() if not df["Sure_Cin_Fiyatlama"].empty else 0.0,
        "3. Gümrük Fiyatlama": df["Sure_Gumruk_Fiyatlama"].mean() if not df["Sure_Gumruk_Fiyatlama"].empty else 0.0,
        "4. Marj & Müşteri İletim": df["Sure_Teklif_Iletim"].mean() if not df["Sure_Teklif_Iletim"].empty else 0.0
    }
    bottleneck_stage = max(stages, key=stages.get) if stages else "Belirlenemedi"

    category_summary = df.groupby("Kategori").agg({"REQ_No": "count", "Satis_Tutari": "sum", "Toplam_Maliyet": "sum", "Brut_Kar": "sum", "Sure_Cin_Fiyatlama": "mean", "Toplam_Sure": "mean"}).reset_index()
    category_summary["Kar_Marji"] = (category_summary["Brut_Kar"] / category_summary["Satis_Tutari"]).fillna(0.0)

    cargo_list = enrich_cargo_data(raw_cargo_rows, df.to_dict(orient="records"))
    sla_breaches = df[df["Toplam_Sure"] > 4.0][["Yonetici", "REQ_No", "Musteri", "Toplam_Sure", "Pipeline_Durumu"]].to_dict(orient="records")
    low_margin_reqs = df[(df["Kar_Marji"] < 0.15) & (df["Satis_Tutari"] > 0)][["Yonetici", "REQ_No", "Musteri", "Kar_Marji", "Brut_Kar"]].to_dict(orient="records")
    mgr_group = df.groupby("Yonetici").agg({"REQ_No": "count", "Satis_Tutari": "sum", "Brut_Kar": "sum", "Toplam_Sure": "mean"}).reset_index().to_dict(orient="records")

    return {"toplam_req_sayisi": len(df), "toplam_ciro_usd": total_sales, "toplam_maliyet_usd": total_cost, "toplam_brut_kar_usd": total_profit, "konsolide_marj_yuzde": avg_margin * 100, "genel_ort_teklif_suresi": avg_total_time, "asama_ortalamalari": stages, "en_buyuk_darbogaz": bottleneck_stage, "kategori_analitigi": category_summary.to_dict(orient="records"), "aktif_kargolar_crg": cargo_list, "sla_asimlari": sla_breaches, "dusuk_marjli_talepler": low_margin_reqs, "yonetici_ozetleri": mgr_group}

@st.cache_data(ttl=300, show_spinner=False)
def fetch_supplier_pool():
    client = get_sheets_client()
    spreadsheet = client.open_by_key(SPREADSHEET_KEY)
    try:
        ws = spreadsheet.worksheet("TEDARIKCI_HAVUZU")
        data = ws.get_all_values()
        if len(data) > 1:
            return pd.DataFrame(data[1:], columns=data[0])
        return pd.DataFrame(columns=["Kategori", "Anahtar Kelime / Ürün", "Tedarikçi Firma", "Ülke / Bölge", "İletişim Kişisi", "E-Posta", "Tahmini Termin / Notlar"])
    except Exception:
        return pd.DataFrame(columns=["Kategori", "Anahtar Kelime / Ürün", "Tedarikçi Firma", "Ülke / Bölge", "İletişim Kişisi", "E-Posta", "Tahmini Termin / Notlar"])

def add_supplier_to_sheet(kategori, urunler, firma, ulke, kisi, eposta, notlar):
    client = get_sheets_client()
    spreadsheet = client.open_by_key(SPREADSHEET_KEY)
    try:
        ws = spreadsheet.worksheet("TEDARIKCI_HAVUZU")
    except Exception:
        ws = spreadsheet.add_worksheet(title="TEDARIKCI_HAVUZU", rows=1000, cols=10)
        ws.append_row(["Kategori", "Anahtar Kelime / Ürün", "Tedarikçi Firma", "Ülke / Bölge", "İletişim Kişisi", "E-Posta", "Tahmini Termin / Notlar"])
    ws.append_row([kategori, urunler, firma, ulke, kisi, eposta, notlar])

# --- YENİ ODOO-KILLER (TEKİL PIPELINE) FONKSİYONLARI ---

def setup_master_sheets():
    """Yusuf Bey'e sunulacak yeni SQL simülasyon sayfalarını Google Sheets'te oluşturur."""
    client = get_sheets_client()
    spreadsheet = client.open_by_key(SPREADSHEET_KEY)
    
    try:
        ws_cat = spreadsheet.worksheet("URUN_KATALOGU")
    except gspread.exceptions.WorksheetNotFound:
        ws_cat = spreadsheet.add_worksheet(title="URUN_KATALOGU", rows=500, cols=10)
        ws_cat.append_row(["Ürün Kodu/Adı", "Kategori", "Tedarikçi", "Son Alış Fiyatı (USD)", "Tarih", "Notlar"])

    try:
        ws_pipe = spreadsheet.worksheet("REQ_PIPELINE")
    except gspread.exceptions.WorksheetNotFound:
        ws_pipe = spreadsheet.add_worksheet(title="REQ_PIPELINE", rows=1000, cols=10)
        ws_pipe.append_row([
            "REQ Kodu", "Müşteri", "İçerik / Ürün", "Tedarikçi & Alış Maliyeti", 
            "Gümrük & Lojistik", "Kâr Marjı (%)", "Müşteri Teklif Fiyatı", "Süreç Statüsü"
        ])

@st.cache_data(ttl=60, show_spinner=False)
def fetch_master_pipeline():
    """REQ_PIPELINE sayfasındaki verileri çeker."""
    client = get_sheets_client()
    spreadsheet = client.open_by_key(SPREADSHEET_KEY)
    try:
        ws = spreadsheet.worksheet("REQ_PIPELINE")
        data = ws.get_all_values()
        if len(data) > 1:
            return pd.DataFrame(data[1:], columns=data[0])
        else:
            return pd.DataFrame(columns=data[0]) if data else pd.DataFrame()
    except Exception:
        return pd.DataFrame()

def add_master_pipeline_record(req_kodu, musteri, icerik, alis_maliyeti, lojistik, marj, teklif_fiyati, statu):
    client = get_sheets_client()
    spreadsheet = client.open_by_key(SPREADSHEET_KEY)
    try:
        ws = spreadsheet.worksheet("REQ_PIPELINE")
        ws.append_row([req_kodu, musteri, icerik, alis_maliyeti, lojistik, marj, teklif_fiyati, statu])
    except Exception as e:
        st.error(f"Kayıt eklenirken hata oluştu: {e}")
