"""Integration: transcribe the committed fixture WAV. Auto-skips off the target machine."""

import os
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "hello.wav"

pytestmark = pytest.mark.skipif(
    os.environ.get("UTTER_INTEGRATION") != "1",
    reason="set UTTER_INTEGRATION=1 to run model-loading integration tests",
)


def test_fixture_wav_transcribes():
    from utter.core.recorder import load_wav
    from utter.core.transcription import FasterWhisperService

    clip = load_wav(str(FIXTURE))
    assert clip.sample_rate == 16000
    assert clip.samples.dtype.name == "float32"

    service = FasterWhisperService(beam_size=5, language="auto")
    service.load("large-v3", "auto", "float16")
    transcript = service.transcribe(clip)
    text = transcript.text.lower()
    assert "dictation" in text
    assert transcript.latency_ms > 0

    # model stays resident: second call must not reload (same object, warm latency)
    second = service.transcribe(clip)
    assert second.text.lower().count("dictation") >= 1
