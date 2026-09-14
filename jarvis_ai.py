import os
import json
import streamlit as st
import pandas as pd
import google.generativeai as genai
from dotenv import load_dotenv

try:
    from plugin_loader import load_active_plugins
except ImportError:
    def load_active_plugins():
        return []

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    try:
        if hasattr(st, "secrets") and "GEMINI_API_KEY" in st.secrets:
            api_key = str(st.secrets["GEMINI_API_KEY"])
    except Exception:
        pass

if api_key:
    genai.configure(api_key=api_key)

ROBUST_CONFIG = {
    "temperature": 0.15,      
    "top_p": 0.85,
    "max_output_tokens": 3000
}

# GÜNCELLEME: API'nin talep ettiği en güncel model sürümü
MODEL_NAME = "gemini-3.6-flash"

def generate_executive_briefing(metrics_summary: dict) -> str:
    if not api_key: return "⚠️ Gemini API Anahtarı bulunamadı."
    prompt = f"Aşağıdaki operasyon metriklerine göre yöneticiye kısa, net bir günlük brifing hazırla:\n{json.dumps(metrics_summary, ensure_ascii=False)}"
    try:
        model = genai.GenerativeModel(model_name=MODEL_NAME, generation_config=ROBUST_CONFIG)
        return model.generate_content(prompt).text
    except Exception as e:
        return f"Brifing oluşturulamadı: {e}"

def generate_restaurant_briefing(sk_metrics: dict) -> str:
    if not api_key: return "⚠️ Gemini API Anahtarı bulunamadı."
    prompt = f"Aşağıdaki Sütlü Kavurma restoranı metriklerine göre finansal brifing hazırla:\n{json.dumps(sk_metrics, ensure_ascii=False)}"
    try:
        model = genai.GenerativeModel(model_name=MODEL_NAME, generation_config=ROBUST_CONFIG)
        return model.generate_content(prompt).text
    except Exception as e:
        return f"Brifing oluşturulamadı: {e}"

def query_jarvis(user_prompt: str, user_role: str, metrics_summary: dict, raw_df_or_json, company: str) -> str:
    if not api_key: return "⚠️ Gemini API Anahtarı bulunamadı."
    
    active_tools = load_active_plugins()
    system_instruction = f"Sen OZ GROUP karar destek asistanı JARVIS'sin. Rol: {user_role} | Şirket: {company}\nMETRİKLER: {json.dumps(metrics_summary, ensure_ascii=False)}\nGÖREVİN: Kısa ve net cevap ver. Kargo lokasyon veya durum güncellemeleri istenirse sana verilen araçları (TOOLS) kesinlikle kullan."
    
    try:
        model_kwargs = {
            "model_name": MODEL_NAME,
            "generation_config": ROBUST_CONFIG,
            "system_instruction": system_instruction
        }
        if active_tools:
            model_kwargs["tools"] = active_tools

        model = genai.GenerativeModel(**model_kwargs)
        chat = model.start_chat(enable_automatic_function_calling=bool(active_tools))
        return chat.send_message(user_prompt).text
        
    except Exception as e:
        return f"⚠️ Jarvis Hatası: {e}"

def intelligent_match_reqs(req_text: str, suppliers_json: str) -> str:
    if not api_key: return "⚠️ Gemini API Anahtarı bulunamadı."
    prompt = f"""
    Sen OZ Global Trade dış ticaret ve tedarik zinciri asistanısın. 
    Aşağıda müşteriden gelen ham talep listesi (ürün kodları, markalar ve teknik özellikler içerir) yer alıyor:
    {req_text}
    
    Aşağıda ise elimizdeki tedarikçi havuzunun veritabanı JSON formatında var:
    {suppliers_json}
    
    Görevin:
    1. Ham listedeki her bir kalem ürünü analiz et (Marka, model ve ürün türünü anla).
    2. Tedarikçi havuzundaki firmaların yetkinlikleri ve kategorileriyle akıllı anlamsal (semantic) eşleşme yap.
    3. Sonucu net, profesyonel bir tablo veya maddeleme şeklinde sun: Hangi ürün için hangi tedarikçi firma uygun, iletişim kişisi ve e-postası nedir belirt.
    4. Mail taslakları OLUŞTURMA (onları kullanıcı butonla isteyecek). Sadece akıllı eşleştirme matrisini çıkar.
    """
    try:
        model = genai.GenerativeModel(model_name=MODEL_NAME, generation_config=ROBUST_CONFIG)
        return model.generate_content(prompt).text
    except Exception as e:
        return f"Eşleştirme analizi hatası: {e}"

def generate_single_rfq_email(supplier_name: str, contact_person: str, products_text: str) -> str:
    if not api_key: return "⚠️ Gemini API Anahtarı bulunamadı."
    prompt = f"""
    Sen OZ Global Trade dış ticaret departmanının AI asistanısın. Aşağıdaki bilgilerle tedarikçiye gönderilmek üzere profesyonel, resmi ve net bir İngilizce RFQ (Request for Quotation) e-posta taslağı yaz.
    
    Tedarikçi Firma: {supplier_name}
    İlgili Kişi: {contact_person if contact_person else 'Sales Team'}
    Talep Edilen Ürünler/Kategoriler:
    {products_text}
    
    Kurallar:
    - Konu satırı (Subject) profesyonel olsun.
    - Termin süresi, MOQ (Minimum sipariş miktarı) ve fiyat teklifi talep et.
    - Sade ve kurumsal bir İngilizce kullan.
    """
    try:
        model = genai.GenerativeModel(model_name=MODEL_NAME, generation_config=ROBUST_CONFIG)
        return model.generate_content(prompt).text
    except Exception as e:
        return f"Mail oluşturma hatası: {e}"
