"""
Live dictation relay (/api/ws/voice): browser microphone <-> Deepgram. Deepgram is replaced by a fake, so these
tests are offline and free. They pin the behaviour the client depends on: the events it asks Deepgram for, the
final words surviving "Done", a dropped upstream closing the browser, and the session-length cap.
"""
import asyncio
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

sys.path.insert(0, str(Path(__file__).parent.parent))

import backend.main as main
from backend import limits


class FakeDeepgram:
    """Async-context-manager stand-in for the Deepgram socket. `script` is what it says; it can wait for CloseStream."""

    def __init__(self, script=(), after_close=(), hang=False):
        self.script, self.after_close, self.hang = list(script), list(after_close), hang
        self.received, self.closed_by_client = [], asyncio.Event()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def send(self, data):
        self.received.append(data)
        if isinstance(data, str) and json.loads(data).get("type") == "CloseStream":
            self.closed_by_client.set()

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for m in self.script:
            yield m
        if self.hang:
            await asyncio.sleep(3600)
        if self.after_close:                       # Deepgram flushes its last results only after CloseStream
            await self.closed_by_client.wait()
            for m in self.after_close:
                yield m


@pytest.fixture()
def relay(monkeypatch):
    """Returns (client, seen) where `seen` collects the Deepgram URL and the fake socket used."""
    limits.VOICE_LIMITER.hits.clear()
    monkeypatch.setenv("DEEPGRAM_API_KEY", "test-key")
    seen = {}

    def install(fake):
        def connect(url, **kw):
            seen["url"], seen["fake"] = url, fake
            return fake
        monkeypatch.setattr(main.websockets, "connect", connect)
        return seen

    client = TestClient(main.app)
    client.install = install
    yield client
    limits.VOICE_LIMITER.hits.clear()


def test_the_client_asks_deepgram_for_the_events_it_relies_on(relay):
    """SpeechStarted (barge-in) needs vad_events; UtteranceEnd (hands-free send) needs utterance_end_ms."""
    seen = relay.install(FakeDeepgram(script=['{"type":"Results"}']))
    with relay.websocket_connect("/api/ws/voice/nb") as ws:
        ws.receive_text()
    for needed in ("vad_events=true", "utterance_end_ms=", "interim_results=true", "model=nova-3"):
        assert needed in seen["url"], seen["url"]


def test_transcripts_flow_back_and_the_browser_is_closed_when_deepgram_ends(relay):
    relay.install(FakeDeepgram(script=['{"type":"SpeechStarted"}', '{"type":"Results","is_final":true}']))
    with relay.websocket_connect("/api/ws/voice/nb") as ws:
        assert json.loads(ws.receive_text())["type"] == "SpeechStarted"
        assert json.loads(ws.receive_text())["type"] == "Results"
        with pytest.raises(WebSocketDisconnect):   # upstream ended -> the browser is told, not left "listening"
            ws.receive_text()


def test_audio_is_forwarded_and_the_last_words_survive_done(relay):
    seen = relay.install(FakeDeepgram(after_close=['{"type":"Results","is_final":true,"speech_final":true}']))
    with relay.websocket_connect("/api/ws/voice/nb") as ws:
        ws.send_bytes(b"\x01\x02\x03")
        ws.send_text('{"type":"CloseStream"}')
        # the final transcript arrives AFTER the learner pressed Done and must still reach the browser
        assert json.loads(ws.receive_text())["speech_final"] is True
    assert seen["fake"].received[0] == b"\x01\x02\x03"
    assert json.loads(seen["fake"].received[-1])["type"] == "CloseStream"


def test_a_session_cannot_stream_forever(relay, monkeypatch):
    monkeypatch.setattr(main, "MAX_VOICE_SECONDS", 0.4)
    relay.install(FakeDeepgram(hang=True))
    with relay.websocket_connect("/api/ws/voice/nb") as ws:
        with pytest.raises(WebSocketDisconnect):
            ws.receive_text()


def test_oversized_streams_are_cut_off(relay, monkeypatch):
    monkeypatch.setattr(main, "MAX_VOICE_STREAM_BYTES", 10)
    seen = relay.install(FakeDeepgram(hang=True))
    with relay.websocket_connect("/api/ws/voice/nb") as ws:
        ws.send_bytes(b"x" * 64)
        with pytest.raises(WebSocketDisconnect):
            ws.receive_text()
    assert json.loads(seen["fake"].received[-1])["type"] == "CloseStream"


def test_missing_key_or_foreign_origin_is_refused(relay, monkeypatch):
    relay.install(FakeDeepgram())
    monkeypatch.delenv("DEEPGRAM_API_KEY")
    with pytest.raises(WebSocketDisconnect):
        with relay.websocket_connect("/api/ws/voice/nb"):
            pass
    monkeypatch.setenv("DEEPGRAM_API_KEY", "test-key")
    with pytest.raises(WebSocketDisconnect):
        with relay.websocket_connect("/api/ws/voice/nb", headers={"origin": "https://evil.example"}):
            pass
