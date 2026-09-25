from jarvis import sounds


def test_success_and_error_are_valid_nonempty_wav_bytes():
    for audio in (sounds.SUCCESS, sounds.ERROR, sounds.WELCOME):
        assert audio.startswith(b"RIFF") and b"WAVE" in audio[:16]
        assert len(audio) > 1000  # birkaç yüz ms'lik gerçek ses verisi, boş/bozuk değil
    assert len({sounds.SUCCESS, sounds.ERROR, sounds.WELCOME}) == 3
