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

MODEL_NAME = "gemini-1.5-flash"
ROBUST_CONFIG = {
    "temperature": 0.2,
    "top_p": 0.95,
    "top_k": 40,
    "max_output_tokens": 4096
}

def intelligent_match_and_draft_rfqs(req_text: str, suppliers_json: str) -> list:
    if not api_key:
        return []
        
    prompt = f"""
    Sen OZ Global Trade dış ticaret uzmanısın.
    Aşağıdaki ürün talep listesini (REQ) analiz et ve tedarikçi havuzundan en uygun firmalarla eşleştir.
    Her eşleşme için profesyonel İngilizce RFQ e-posta konu ve metnini hazırla.
    
    Talep Listesi:
    {req_text}
    
    Tedarikçi Havuzu:
    {suppliers_json}
    
    ÇIKTI FORMATI:
    Kesinlikle karşılama, selamlaşma veya markdown açıklama metni yazma.
    Sadece ve sadece aşağıdaki şemaya uygun geçerli bir JSON dizisi (Array of Objects) döndür:
    
    [
      {{
        "talep": "Talep Edilen Ürün/Kalem Adı",
        "tedarikci": "Eşleşen Tedarikçi Firma Adı",
        "eposta": "Tedarikçinin e-posta adresi (yoksa '')",
        "kisi": "İletişim Kişisi (yoksa 'Sales Team')",
        "ulke": "Ülke / Bölge",
        "aciklama": "Eşleşme sebebi / Ürün yetkinliği",
        "mail_subject": "RFQ - Commercial Inquiry for [Ürün Adı] - OZ Global Trade",
        "mail_body": "Dear [Kişi veya Sales Team],\\n\\nWe are reaching out from OZ Global Trade regarding the procurement of [Ürün Adı].\\nCould you please share your official quotation including unit price, minimum order quantity (MOQ), and estimated delivery lead time?\\n\\nLooking forward to your swift response.\\n\\nBest regards,\\nOZ Global Trade Team"
      }}
    ]
    """
    try:
        model = genai.GenerativeModel(model_name=MODEL_NAME, generation_config=ROBUST_CONFIG)
        res = model.generate_content(prompt)
        text = res.text.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
            
        return json.loads(text)
    except Exception:
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                return []
        return []

def generate_executive_briefing(metrics: dict) -> str:
    if not api_key: return "API anahtarı eksik."
    prompt = f"Aşağıdaki operasyonel metrikleri özetle ve 3 maddelik yönetim brifingi oluştur: {metrics}"
    try:
        model = genai.GenerativeModel(model_name=MODEL_NAME, generation_config=ROBUST_CONFIG)
        return model.generate_content(prompt).text
    except Exception as e:
        return f"Brifing hatası: {e}"

def query_jarvis(user_msg: str, user_role: str, metrics: dict, df, company_name: str) -> str:
    if not api_key: return "API anahtarı eksik."
    prompt = f"Rol: {user_role}. Şirket: {company_name}. Kullanıcı sorusu: {user_msg}. Veriler: {metrics}"
    try:
        model = genai.GenerativeModel(model_name=MODEL_NAME, generation_config=ROBUST_CONFIG)
        return model.generate_content(prompt).text
    except Exception as e:
        return f"Jarvis yanıt üretemedi: {e}"
