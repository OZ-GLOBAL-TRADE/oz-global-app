import os
import json
import re
import google.generativeai as genai
import streamlit as st

def get_gemini_api_key():
    if hasattr(st, "secrets") and "GEMINI_API_KEY" in st.secrets:
        return str(st.secrets["GEMINI_API_KEY"]).strip()
    return os.getenv("GEMINI_API_KEY", "").strip()

api_key = get_gemini_api_key()
if api_key:
    genai.configure(api_key=api_key)

MODEL_NAME = "gemini-3.6-flash"

def intelligent_match_and_draft_rfqs(req_text: str, suppliers_json: str):
    if not api_key:
        return [], "⚠️ Gemini API Anahtarı bulunamadı. Lütfen Secrets veya .env ayarlarınızı kontrol edin."
        
    prompt = f"""
    Sen OZ Global Trade dış ticaret ve tedarik zinciri asistanısın.
    Müşteriden gelen talep listesindeki her bir ürünü analiz et ve verilen tedarikçi havuzundan uygun firmalarla eşleştir.

    TALEP LİSTESİ:
    {req_text}

    TEDARİKÇİ HAVUZU:
    {suppliers_json}

    GÖREV VE KURALLAR:
    1. Listedeki HER BİR kalem için, havuzdan o ürünü sağlayabilecek TÜM tedarikçileri bul. 
    2. Alternatif fiyat teklifleri alabilmemiz için bir ürüne uyan birden fazla firma varsa, her biri için ayrı bir JSON nesnesi oluştur (Kesinlikle tek tedarikçiyle sınırlama).
    3. Sadece aşağıdaki JSON şemasına uygun bir JSON ARRAY (liste) döndür.
    4. Markdown başlığı, selamlama veya açıklama yazma.
    
    JSON ŞEMASI:
    [
      {{
        "talep": "Talep edilen ürünün adı/kodu",
        "tedarikci": "Havuzdaki Tedarikçi Firma Adı",
        "eposta": "Tedarikçinin e-posta adresi (yoksa '')",
        "kisi": "İlgili Kişi Adı (yoksa 'Sales Team')",
        "ulke": "Ülke veya Şehir",
        "aciklama": "Neden bu firma seçildi (kısa açıklama)"
      }}
    ]
    """
    try:
        model = genai.GenerativeModel(
            model_name=MODEL_NAME,
            generation_config={
                "temperature": 0.2, # Birden fazla alternatif bulması için yaratıcılığı hafif artırdık
                "response_mime_type": "application/json"
            }
        )
        res = model.generate_content(prompt)
        text = res.text.strip()
        
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed, ""
        elif isinstance(parsed, dict) and "matches" in parsed:
            return parsed["matches"], ""
        return [], "Yapay zeka eşleşen veri formatını dizi olarak döndüremedi."
    except Exception as e:
        try:
            match = re.search(r'\[.*\]', text, re.DOTALL)
            if match:
                return json.loads(match.group(0)), ""
        except Exception:
            pass
        return [], f"Eşleştirme API Hatası: {e}"

def generate_executive_briefing(metrics: dict) -> str:
    if not api_key: return "API anahtarı eksik."
    prompt = f"Aşağıdaki operasyonel metrikleri özetle ve 3 maddelik yönetim brifingi oluştur: {metrics}"
    try:
        model = genai.GenerativeModel(model_name=MODEL_NAME)
        return model.generate_content(prompt).text
    except Exception as e:
        return f"Brifing hatası: {e}"

def query_jarvis(user_msg: str, user_role: str, metrics: dict, df, company_name: str) -> str:
    if not api_key: return "API anahtarı eksik."
    prompt = f"Rol: {user_role}. Şirket: {company_name}. Kullanıcı sorusu: {user_msg}. Veriler: {metrics}"
    try:
        model = genai.GenerativeModel(model_name=MODEL_NAME)
        return model.generate_content(prompt).text
    except Exception as e:
        return f"Jarvis yanıt üretemedi: {e}"
