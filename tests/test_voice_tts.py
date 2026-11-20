"""
Tutor narration (ElevenLabs text-to-speech). The HTTP call is replaced by a fake, so these tests are offline and
free. Whatever ElevenLabs does (rate limit, outage, odd payload, no key), the learner must still get a drawing with
usable timing, and the failure must be flagged so the UI can say "text only".
"""
import base64
import json
import sys
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine import voice

ALIGN = {"characters": list("Hello there"),
         "character_start_times_seconds": [i * 0.1 for i in range(11)],
         "character_end_times_seconds": [(i + 1) * 0.1 for i in range(11)]}


class Reply:
    def __init__(self, status=200, body=None, text=""):
        self.status_code, self._body, self.text = status, body, text

    def json(self):
        return self._body


def ok(alignment=ALIGN):
    return Reply(200, {"audio_base64": base64.b64encode(b"MP3DATA").decode(), "alignment": alignment})


@pytest.fixture()
def tts(monkeypatch, tmp_path):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    monkeypatch.setattr(voice.time, "sleep", lambda s: None)
    calls = []

    def run(*replies):
        queue = list(replies)

        def fake_post(url, **kw):
            calls.append(kw)
            r = queue.pop(0)
            if isinstance(r, Exception):
                raise r
            return r
        monkeypatch.setattr(requests, "post", fake_post)
        out = voice.generate_narration_audio("Hello there", str(tmp_path / "a.mp3"), str(tmp_path / "a.json"), "box")
        return out, json.loads((tmp_path / "a.json").read_text(encoding="utf-8")), calls
    return run


def test_success_returns_real_audio_and_timings(tts, tmp_path):
    (duration, chars, _), data, _ = tts(ok())
    assert data["provider"] == "elevenlabs" and data["is_synthetic"] is False
    assert (tmp_path / "a.mp3").read_bytes() == b"MP3DATA"
    assert duration == pytest.approx(1.1) and chars == 11
    assert data["marker_timings"][0]["id"] == "box"


def test_one_rate_limit_is_retried_then_succeeds(tts):
    _, data, calls = tts(Reply(429, text="slow down"), ok())
    assert len(calls) == 2 and data["is_synthetic"] is False


@pytest.mark.parametrize("failure", [
    Reply(500, text="boom"),
    Reply(401, text="quota exceeded"),
    Reply(429),
    requests.Timeout("too slow"),
    requests.ConnectionError("offline"),
])
def test_any_elevenlabs_failure_degrades_to_flagged_silence(tts, failure, tmp_path):
    replies = [failure, failure] if isinstance(failure, Reply) and failure.status_code == 429 else [failure]
    (duration, _, align), data, _ = tts(*replies)
    assert data["is_synthetic"] is True and data["provider"] == "synthetic_fallback"   # author.py turns this into voice_ok=False
    assert duration >= 3.0 and (tmp_path / "a.mp3").stat().st_size > 0
    assert data["marker_timings"], "the drawing still needs a reveal time"


def test_a_null_alignment_does_not_break_the_draw(tts):
    _, data, _ = tts(ok(alignment=None))
    assert data["provider"] == "elevenlabs"        # real audio is kept; the player reveals at time 0 when there is no timing


def test_no_api_key_means_silent_fallback_without_calling_out(monkeypatch, tmp_path):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.setattr(voice, "ELEVENLABS_API_KEY", None)
    monkeypatch.setattr(voice, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setattr(requests, "post", lambda *a, **k: pytest.fail("must not call ElevenLabs without a key"))
    _, _, align = voice.generate_narration_audio("Hello there", str(tmp_path / "a.mp3"), str(tmp_path / "a.json"), "box")
    assert align["is_synthetic"] is True


def test_the_text_sent_is_exactly_the_text_aligned(tts):
    _, data, calls = tts(ok())
    assert calls[0]["json"]["text"] == data["clean_text"] == "Hello there"
