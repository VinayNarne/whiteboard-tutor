import os
import sys
import io
import wave
import struct
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.database import init_db

init_db()
client = TestClient(app)


def make_silent_wav() -> bytes:
    """Generate a valid 0.5s silent 16kHz mono WAV file."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(struct.pack("<" + ("h" * 8000), *([0] * 8000)))
    return buf.getvalue()


live_deepgram = pytest.mark.skipif(not os.getenv("DEEPGRAM_API_KEY"), reason="calls the real Deepgram service: needs DEEPGRAM_API_KEY")


def test_without_a_key_voice_input_says_it_is_not_configured(monkeypatch):
    monkeypatch.delenv("DEEPGRAM_API_KEY", raising=False)
    res = client.post("/api/transcribe-voice", content=b"x", headers={"content-type": "audio/webm"})
    assert res.status_code == 503 and "DEEPGRAM_API_KEY" in res.json()["detail"]


def test_transcribe_voice_empty_payload(monkeypatch):
    """Empty payload should return 400 (checked before Deepgram is called, so a placeholder key is enough)."""
    monkeypatch.setenv("DEEPGRAM_API_KEY", "placeholder-not-used")
    res = client.post("/api/transcribe-voice", content=b"", headers={"content-type": "audio/webm"})
    assert res.status_code == 400


@live_deepgram
def test_transcribe_voice_valid_audio():
    """Valid WAV bytes sent to Deepgram Nova-3 returns 200 with transcript field."""
    wav_bytes = make_silent_wav()
    res = client.post("/api/transcribe-voice", content=wav_bytes, headers={"content-type": "audio/wav"})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert "transcript" in data
    assert "confidence" in data


@live_deepgram
def test_voice_websocket_handshake():
    """Test connecting to voice websocket and closing cleanly."""
    with client.websocket_connect("/api/ws/voice/test-notebook-voice") as ws:
        # Send CloseStream control packet
        ws.send_text('{"type": "CloseStream"}')
        # Server should receive or close gracefully without crashing


def test_interrupt_barge_in_endpoint():
    """Test that POST /api/notebooks/{id}/interrupt responds with 200 and interrupted status."""
    res = client.post("/api/notebooks/test-nb-bargein/interrupt")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "interrupted"
    assert "was_active" in data
    assert data["notebook_id"] == "test-nb-bargein"
