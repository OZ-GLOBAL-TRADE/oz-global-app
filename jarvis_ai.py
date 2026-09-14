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

def get_best_available_model():
    """Hesapta generateContent destekleyen en uygun modeli dinamik olarak seçer."""
    fallback = "gemini-1.5-flash"
    if not api_key:
        return fallback
    try:
        available_models = [
            m.name.replace("models/", "")
            for m in genai.list_models()
            if "generateContent" in m.supported_generation_methods
        ]
        priority_list = [
            "gemini-1.5-flash",
            "gemini-1.5-flash-latest",
            "gemini-1.5-flash-8b",
            "gemini-1.5-pro",
            "gemini-1.5-pro-latest",
            "gemini-pro"
        ]
        for candidate in priority_list:
            if candidate in available_models:
                return candidate
        if available_models:
            return available_models[0]
    except Exception:
        pass
    return fallback

def intelligent_match_and_draft_rfqs(req_text: str, suppliers_json: str):
    if not api_key:
        return [], "⚠️ Gemini API Anahtarı bulunamadı. Lütfen Secrets veya .env ayarlarınızı kontrol edin."
        
    prompt = f"""
    Sen OZ Global Trade dış ticaret ve tedarik zinciri asistanısın.
    Müşteriden gelen talep listesindeki her bir ürünü analiz et ve verilen tedarikçi havuzundan en uygun firmalarla eşleştir.

    TALEP LİSTESİ:
    {req_text}

    TEDARİKÇİ HAVUZU:
    {suppliers_json}

    GÖREV:
    - Listedeki her kalem için en uygun tedarikçileri tespit et.
    - Yanıtını SADECE geçerli bir JSON formatında ARRAY (liste) olarak ver.
    - Kesinlikle markdown başlığı, selamlama veya açıklama yazma.
    
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
        active_model = get_best_available_model()
        model = genai.GenerativeModel(model_name=active_model)
        
        res = model.generate_content(prompt)
        text = res.text.strip()
        
        # Markdown kod bloklarını temizle
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
            
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed, ""
        elif isinstance(parsed, dict) and "matches" in parsed:
            return parsed["matches"], ""
        return [], "Eşleşme sonucu dizi formatında çözümlenemedi."
    except Exception as e:
        # JSON ayrıştırma hatası varsa Regex ile dizi araması yap
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
        active_model = get_best_available_model()
        model = genai.GenerativeModel(model_name=active_model)
        return model.generate_content(prompt).text
    except Exception as e:
        return f"Brifing hatası: {e}"

def query_jarvis(user_msg: str, user_role: str, metrics: dict, df, company_name: str) -> str:
    if not api_key: return "API anahtarı eksik."
    prompt = f"Rol: {user_role}. Şirket: {company_name}. Kullanıcı sorusu: {user_msg}. Veriler: {metrics}"
    try:
        active_model = get_best_available_model()
        model = genai.GenerativeModel(model_name=active_model)
        return model.generate_content(prompt).text
    except Exception as e:
        return f"Jarvis yanıt üretemedi: {e}"
