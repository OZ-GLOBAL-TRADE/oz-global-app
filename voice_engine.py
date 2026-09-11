import asyncio
import edge_tts
import tempfile
import os

def generate_jarvis_audio(text: str, voice: str = "tr-TR-AhmetNeural") -> str:
    """
    JARVIS'in metin yanıtlarını akıcı bir sese (MP3) dönüştürür.
    Varsayılan ses: Türkçe erkek sesi (AhmetNeural).
    """
    # Streamlit'in oynatabileceği güvenli geçici MP3 dosyası oluştur
    fd, audio_path = tempfile.mkstemp(suffix=".mp3")
    os.close(fd)

    async def _amain():
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(audio_path)

    try:
        asyncio.run(_amain())
        return audio_path
    except Exception as e:
        print(f"[SES HATASI]: {e}")
        return ""
