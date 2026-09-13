import os
import sys

import pytest

from outloud.tts import MacSayBackend, get_backend, parse_say_voices, pick_default_voice

SAMPLE = """Alex                en_US    # Most people recognize me by my voice.
Eddy (English (UK)) en_GB    # Hello! My name is Eddy.
Samantha (Enhanced) en_US    # Hello! My name is Samantha.
Amélie              fr_CA    # Bonjour! Je m'appelle Amélie.
"""


def test_parse_say_voices_handles_spaces_and_parens():
    voices = parse_say_voices(SAMPLE)
    assert [v.name for v in voices] == ["Alex", "Eddy (English (UK))", "Samantha (Enhanced)", "Amélie"]
    assert voices[1].lang == "en_GB"


def test_backend_exists_for_this_platform():
    assert get_backend().name


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS say only")
def test_say_synthesizes_to_file_silently(tmp_path):
    backend = MacSayBackend()
    voice = pick_default_voice(backend.voices())
    assert voice, "no English voice installed"
    out = tmp_path / "t.aiff"
    backend.speak("Testing, one two three.", voice, 220, out_file=str(out))
    # ~1 second of 22 kHz 16-bit audio; a Siri system voice yields a 4 KB stub instead
    assert out.exists() and os.path.getsize(out) > 20_000


def test_default_voice_prefers_premium_then_samantha():
    from outloud.tts import Voice
    if sys.platform != "darwin":
        assert pick_default_voice([Voice("x", "x", "en_US")]) is None
        return
    vs = [Voice("Samantha", "Samantha", "en_US"), Voice("Ava (Premium)", "Ava (Premium)", "en_US"), Voice("Amelie", "Amelie", "fr_CA")]
    assert pick_default_voice(vs) == "Ava (Premium)"
    assert pick_default_voice(vs[:1] + vs[2:]) == "Samantha"
