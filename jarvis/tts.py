"""Jarvis AI sesli yanıt: Microsoft Edge'in ücretsiz nöral sesleri (edge-tts) — API anahtarı gerekmez,
tarayıcının kendi robotik sesinden belirgin şekilde daha doğal. Okunacak metinden emoji ve benzeri
sembolleri temizler (kullanıcı isteği: emojiler sesli okunmasın)."""
import asyncio
import re

VOICE = "tr-TR-EmelNeural"  # kadın, doğal; alternatif: "tr-TR-AhmetNeural" (erkek)

_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FFFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF"
    "←-⇿⌀-⏿⬀-⯿️]+", flags=re.UNICODE)


def _clean(text: str) -> str:
    return re.sub(r"\s{2,}", " ", _EMOJI_RE.sub("", text)).strip()


def synthesize(text: str, voice: str = VOICE) -> bytes:
    """Metni MP3 bayt dizisine çevirir. edge-tts kurulu değilse ya da metin boşsa boş bayt döner
    (çağıran taraf bunu 'sesli okunamadı' olarak sessizce ele almalı, hataya düşmemeli)."""
    clean = _clean(text)
    if not clean:
        return b""
    try:
        import edge_tts
    except ImportError:
        return b""

    async def _run() -> bytes:
        buf = bytearray()
        async for chunk in edge_tts.Communicate(clean, voice).stream():
            if chunk["type"] == "audio":
                buf.extend(chunk["data"])
        return bytes(buf)

    try:
        return asyncio.run(_run())
    except Exception:
        return b""
