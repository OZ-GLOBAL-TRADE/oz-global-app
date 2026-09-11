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
