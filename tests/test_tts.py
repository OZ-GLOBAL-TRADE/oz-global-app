from jarvis import tts


def test_clean_strips_emoji_but_keeps_text():
    assert tts._clean("Merhaba! 9 aktif REQ var. ✅🚀 Test tamam. 🎤") == "Merhaba! 9 aktif REQ var. Test tamam."
    assert tts._clean("   ") == ""


def test_synthesize_returns_empty_bytes_for_empty_or_emoji_only_text():
    assert tts.synthesize("") == b""
    assert tts.synthesize("✅🚀") == b""
