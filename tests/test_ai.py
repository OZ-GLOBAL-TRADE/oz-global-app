from types import SimpleNamespace

from jarvis import ai


class _FakeModel:
    def __init__(self, text): self._text = text

    def generate_content(self, contents): return SimpleNamespace(text=self._text)


class _FakeGenai:
    def __init__(self, text): self._text = text

    def GenerativeModel(self, model_name): return _FakeModel(self._text)


def test_transcribe_audio_returns_text_from_gemini(monkeypatch):
    monkeypatch.setattr(ai, "_client", lambda: _FakeGenai("REQ_04'ün durumu ne?"))
    text, err = ai.transcribe_audio(b"fake-wav-bytes")
    assert text == "REQ_04'ün durumu ne?" and err == ""


def test_transcribe_audio_without_key_or_empty_audio(monkeypatch):
    monkeypatch.setattr(ai, "_client", lambda: None)
    text, err = ai.transcribe_audio(b"anything")
    assert text == "" and "GEMINI_API_KEY" in err

    monkeypatch.setattr(ai, "_client", lambda: _FakeGenai("should not be reached"))
    text, err = ai.transcribe_audio(b"")
    assert text == "" and "boş" in err


def test_transcribe_audio_handles_gemini_error(monkeypatch):
    class _Boom:
        def GenerativeModel(self, model_name): raise RuntimeError("quota exceeded")

    monkeypatch.setattr(ai, "_client", lambda: _Boom())
    text, err = ai.transcribe_audio(b"fake-wav-bytes")
    assert text == "" and "quota exceeded" in err
