"""Input size limits and rate limiting (they protect model / voice credits)."""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient

from backend import limits
from backend.database import init_db
from backend.limits import MAX_CHAT_CHARS, MAX_TOPIC_CHARS, RateLimiter
from backend.main import app

init_db()
client = TestClient(app)


# ----------------------------------------------------------------- sliding-window limiter (fake clock)
def test_limiter_allows_up_to_limit_then_reports_wait_and_recovers():
    rl = RateLimiter(limit=3, window=60)
    assert [rl.check("k", now=t) for t in (0, 1, 2)] == [None, None, None]
    wait = rl.check("k", now=3)
    assert wait is not None and 56 <= wait <= 60           # oldest hit expires at t=60
    assert rl.check("other", now=3) is None                # keys are independent
    assert rl.check("k", now=61) is None                   # window slid past the first hit


def test_limiter_prune_drops_idle_keys():
    rl = RateLimiter(limit=2, window=10)
    rl.check("a", now=0)
    rl.check("b", now=95)
    rl.prune(now=100)
    assert list(rl.hits) == ["b"]                           # "a" idle for 100s is gone; "b" (5s ago) stays


# ----------------------------------------------------------------- size limits
def test_topic_limits():
    assert client.post("/api/notebooks", json={"topic": "x" * (MAX_TOPIC_CHARS + 1)}).status_code == 422
    assert client.post("/api/notebooks", json={"topic": "   "}).status_code == 422       # whitespace only
    r = client.post("/api/notebooks", json={"topic": "  padded topic  "})
    assert r.status_code == 201 and r.json()["topic"] == "padded topic"                  # trimmed
    client.delete(f"/api/notebooks/{r.json()['id']}")


@pytest.fixture()
def notebook():
    nb = client.post("/api/notebooks", json={"topic": "Limits"}).json()["id"]
    limits.CHAT_LIMITER.hits.clear()
    yield nb
    client.delete(f"/api/notebooks/{nb}")
    limits.CHAT_LIMITER.hits.clear()


def test_chat_message_limits(notebook):
    too_long = client.post(f"/api/notebooks/{notebook}/chat", json={"message": "x" * (MAX_CHAT_CHARS + 1)})
    assert too_long.status_code == 422
    assert client.post(f"/api/notebooks/{notebook}/chat", json={"message": "   "}).status_code == 422
    assert client.post(f"/api/notebooks/{notebook}/chat",
                       json={"message": "hi", "selected_element_ids": ["a"] * 11}).status_code == 422


# ----------------------------------------------------------------- rate limiting over HTTP
def test_chat_rate_limit_returns_429_with_retry_after_and_is_per_notebook(notebook):
    other = client.post("/api/notebooks", json={"topic": "Other"}).json()["id"]

    async def fake_author(**kwargs):
        return "ok"

    try:
        with patch.object(limits.CHAT_LIMITER, "limit", 3), \
             patch("backend.main.run_whiteboard_author", side_effect=fake_author):
            codes = [client.post(f"/api/notebooks/{notebook}/chat", json={"message": "hi"}).status_code for _ in range(5)]
            assert codes == [200, 200, 200, 429, 429]
            blocked = client.post(f"/api/notebooks/{notebook}/chat", json={"message": "hi"})
            assert blocked.status_code == 429 and int(blocked.headers["retry-after"]) >= 1
            assert "quickly" in blocked.json()["detail"]
            # a different notebook has its own budget
            assert client.post(f"/api/notebooks/{other}/chat", json={"message": "hi"}).status_code == 200
    finally:
        client.delete(f"/api/notebooks/{other}")


def test_unknown_notebook_does_not_consume_or_create_rate_limit_state():
    before = len(limits.CHAT_LIMITER.hits)
    assert client.post("/api/notebooks/does-not-exist/chat", json={"message": "hi"}).status_code == 404
    assert len(limits.CHAT_LIMITER.hits) == before


def test_voice_transcription_is_rate_limited_per_client():
    limits.VOICE_LIMITER.hits.clear()
    try:
        with patch.object(limits.VOICE_LIMITER, "limit", 2):
            codes = [client.post("/api/transcribe-voice", content=b"x").status_code for _ in range(3)]
        assert codes[2] == 429 and codes[0] != 429 and codes[1] != 429
    finally:
        limits.VOICE_LIMITER.hits.clear()
