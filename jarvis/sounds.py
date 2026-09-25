"""Küçük, hoş UI ses efektleri (başarı/hata). Dış dosya/servis gerekmez — tamamen Python'da (stdlib
`wave` ile) sentezlenir ve WAV bayt dizisi olarak döner; `jarvis/ui/common.py::notify_success/notify_error`
bunları `st.audio(..., autoplay=True)` ile çalar (Jarvis AI'ın sesli yanıtıyla aynı, zaten kanıtlanmış yöntem)."""
import io
import math
import struct
import wave

_SAMPLE_RATE = 22050


def _tone(freq: float, duration: float, volume: float = 0.28, fade: float = 0.015) -> list[float]:
    n = max(1, int(_SAMPLE_RATE * duration))
    fade_n = max(1, int(_SAMPLE_RATE * fade))
    out = []
    for i in range(n):
        env = min(1.0, i / fade_n, (n - i) / fade_n)
        out.append(volume * env * math.sin(2 * math.pi * freq * i / _SAMPLE_RATE))
    return out


def _silence(duration: float) -> list[float]:
    return [0.0] * int(_SAMPLE_RATE * duration)


def _to_wav_bytes(samples: list[float]) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(_SAMPLE_RATE)
        w.writeframes(b"".join(struct.pack("<h", max(-32768, min(32767, int(s * 32767)))) for s in samples))
    return buf.getvalue()


# Kısa, yükselen iki notalı "ding" (C6 -> E6, majör üçlü) — göze batmayan, hoş bir onay sesi.
SUCCESS = _to_wav_bytes(_tone(1046.5, 0.08) + _silence(0.03) + _tone(1318.5, 0.14))

# Tek, alçak, kısa bir nota — rahatsız etmeyen ama fark edilir bir uyarı sesi.
ERROR = _to_wav_bytes(_tone(220.0, 0.16, volume=0.24))

# Üç notalı, yükselen bir arpej (C5 -> E5 -> G5, majör akor) — giriş yapınca çalan, SUCCESS'ten biraz
# daha "kutlamalı" bir karşılama sesi.
WELCOME = _to_wav_bytes(_tone(523.25, 0.09) + _silence(0.02) + _tone(659.25, 0.09) + _silence(0.02) + _tone(783.99, 0.22))
