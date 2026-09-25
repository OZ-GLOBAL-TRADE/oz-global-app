"""Jarvis AI: Gemini tabanlı tedarikçi eşleştirme. Eski Google Sheets sürümündeki jarvis_ai.py'nin REQ tabanlı karşılığıdır."""
import json
import re

from jarvis import config

MODEL_NAME = "gemini-3.6-flash"
_configured = False


def _client():
    """Gemini'yi ilk çağrıda yapılandırır. Anahtar yoksa None döner (google-generativeai paketi de opsiyoneldir)."""
    global _configured
    key = config.get_config_val("GEMINI_API_KEY")
    if not key: return None
    try:
        import google.generativeai as genai
    except ImportError:
        return None
    if not _configured:
        genai.configure(api_key=key)
        _configured = True
    return genai


PROMPT = """Sen OZ Global Trade dış ticaret ve tedarik zinciri asistanısın.
Aşağıdaki talep listesindeki her bir ürünü analiz et ve verilen tedarikçi havuzundan uygun firmalarla eşleştir.

TALEP LİSTESİ:
{items}

TEDARİKÇİ HAVUZU:
{suppliers}

GÖREV VE KURALLAR:
1. Listedeki HER BİR kalem için, havuzdan o ürünü sağlayabilecek TÜM tedarikçileri bul.
2. Alternatif fiyat teklifleri alabilmemiz için bir ürüne uyan birden fazla firma varsa, her biri için ayrı bir JSON nesnesi oluştur (kesinlikle tek tedarikçiyle sınırlama).
3. Sadece aşağıdaki JSON şemasına uygun bir JSON ARRAY (liste) döndür.
4. Markdown başlığı, selamlama veya açıklama yazma.

JSON ŞEMASI:
[
  {{
    "talep": "Talep edilen ürünün adı/kodu",
    "tedarikci_id": "Havuzdaki tedarikçinin id numarası",
    "tedarikci": "Havuzdaki Tedarikçi Firma Adı",
    "eposta": "Tedarikçinin e-posta adresi (yoksa '')",
    "ulke": "Ülke veya Şehir",
    "aciklama": "Neden bu firma seçildi (kısa açıklama)"
  }}
]"""


def match_suppliers(items: list[str], suppliers: list[dict]) -> tuple[list[dict], str]:
    """items: ürün adları (ve varsa özellikleri). suppliers: {id, name, category, keywords, country, email} sözlükleri.
    Dönüş: (eşleşmeler, hata mesajı). Hata durumunda eşleşmeler boş liste olur."""
    genai = _client()
    if not genai: return [], "Gemini API anahtarı bulunamadı (GEMINI_API_KEY). Ayarlar için CLAUDE.md'ye bakın."
    if not items: return [], "Talep listesi boş."
    if not suppliers: return [], "Tedarikçi havuzunuz şu an boş. Önce Kişiler sayfasından tedarikçi ekleyin."

    prompt = PROMPT.format(items="\n".join(f"- {i}" for i in items),
                           suppliers=json.dumps(suppliers, ensure_ascii=False))
    text = ""
    try:
        model = genai.GenerativeModel(model_name=MODEL_NAME, generation_config={"temperature": 0.2, "response_mime_type": "application/json"})
        text = model.generate_content(prompt).text.strip()
        parsed = json.loads(text)
        if isinstance(parsed, list): return parsed, ""
        if isinstance(parsed, dict) and "matches" in parsed: return parsed["matches"], ""
        return [], "Yapay zeka eşleşen veriyi dizi olarak döndürmedi."
    except Exception as e:
        match = re.search(r"\[.*\]", text, re.DOTALL) if text else None
        if match:
            try: return json.loads(match.group(0)), ""
            except Exception: pass
        return [], f"Eşleştirme hatası: {e}"


def transcribe_audio(audio_bytes: bytes, mime_type: str = "audio/wav") -> tuple[str, str]:
    """Jarvis AI sesli giriş: mikrofon kaydını (Gemini üzerinden, zaten var olan GEMINI_API_KEY ile) yazıya çevirir.
    Dönüş: (metin, hata mesajı). Claude'un Messages API'si ses kabul etmediği için STT için Gemini kullanılır;
    yazıya çevrilen metin sonra normal şekilde jarvis_chat.ask()'e (Claude) gider."""
    genai = _client()
    if not genai: return "", "Gemini API anahtarı bulunamadı (GEMINI_API_KEY)."
    if not audio_bytes: return "", "Ses kaydı boş."
    try:
        model = genai.GenerativeModel(model_name=MODEL_NAME)
        prompt = "Bu ses kaydındaki konuşmayı olduğu gibi yazıya çevir. Yalnızca yazıya çevrilmiş metni döndür; açıklama, tırnak veya markdown ekleme."
        response = model.generate_content([prompt, {"mime_type": mime_type, "data": audio_bytes}])
        text = (response.text or "").strip()
        return (text, "") if text else ("", "Ses kaydından metin çıkarılamadı.")
    except Exception as e:
        return "", f"Ses tanıma hatası: {e}"
