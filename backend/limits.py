"""
backend/limits.py
Request-size limits and a tiny in-memory rate limiter. Every chat turn and voice call costs model/TTS/STT
credits, so an accidental loop or a pasted novel must not be able to burn them.
Single-process only (state is a dict); use Redis or similar if the backend ever runs on several workers.
"""
import os
import time
from collections import defaultdict, deque
from typing import Annotated, Optional

from pydantic import AfterValidator, StringConstraints

from core.events import EngineEvent
from core.log import get_logger
from engine.sanitiser import _CONTROL_CHARS, CONTROL_PLACEHOLDER
from engine.summary import MAX_CHAT_CHARS  # defined in the engine, which must not import the backend

logger = get_logger("backend")

# --- size limits -----------------------------------------------------------
MAX_TOPIC_CHARS = 300
MAX_TITLE_CHARS = 200
MAX_SUMMARY_CHARS = 2000
MAX_NARRATION_CHARS = 3000
MAX_SVG_CHARS = 500_000          # same ceiling the sanitiser enforces
MAX_VOICE_SECONDS = float(os.getenv("MAX_VOICE_SECONDS", "300"))  # one live-dictation connection (Deepgram bills by audio time)

def no_control_chars(value: str) -> str:
    """Control characters in text a person (or a client) sent become the visible placeholder the sanitiser uses on the board; tab, newline and carriage return stay.
    NUL above all: Postgres refuses it in any text column, so one pasted or dictated NUL ended the request as a 500 (found in the L round)."""
    cleaned, count = _CONTROL_CHARS.subn(CONTROL_PLACEHOLDER, value)
    if count:
        logger.warn(EngineEvent.CONTROL_CHARS_REPLACED, f"Replaced {count} control character(s) in text from the client with a visible placeholder", data={"count": count})
    return cleaned


_CLEAN = AfterValidator(no_control_chars)
Topic = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_TOPIC_CHARS), _CLEAN]
Title = Annotated[str, StringConstraints(strip_whitespace=True, max_length=MAX_TITLE_CHARS), _CLEAN]
ChatText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_CHAT_CHARS), _CLEAN]
Summary = Annotated[str, StringConstraints(max_length=MAX_SUMMARY_CHARS), _CLEAN]
Narration = Annotated[str, StringConstraints(max_length=MAX_NARRATION_CHARS), _CLEAN]
Svg = Annotated[str, StringConstraints(max_length=MAX_SVG_CHARS)]


class RateLimiter:
    """Sliding window: at most `limit` hits per `window` seconds for each key."""

    def __init__(self, limit: int, window: float = 60.0):
        self.limit, self.window = limit, window
        self.hits: dict = defaultdict(deque)

    def check(self, key: str, now: Optional[float] = None) -> Optional[int]:
        """Record a hit. Returns None if allowed, else the seconds to wait before retrying."""
        now = time.monotonic() if now is None else now
        q = self.hits[key]
        while q and now - q[0] >= self.window:
            q.popleft()
        if len(q) >= self.limit:
            return max(1, int(self.window - (now - q[0])) + 1)
        q.append(now)
        return None

    def prune(self, now: Optional[float] = None) -> None:
        """Drop idle keys so the dict cannot grow without bound."""
        now = time.monotonic() if now is None else now
        for k in [k for k, q in self.hits.items() if not q or now - q[-1] >= self.window]:
            del self.hits[k]


def _per_minute(env_name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(env_name, default)))
    except ValueError:
        return default


CHAT_LIMITER = RateLimiter(_per_minute("RATE_LIMIT_CHAT_PER_MIN", 20))          # per notebook
VOICE_LIMITER = RateLimiter(_per_minute("RATE_LIMIT_VOICE_PER_MIN", 30))        # per client address

CLIENT_LOG_LIMITER = RateLimiter(_per_minute("RATE_LIMIT_CLIENT_LOG_PER_MIN", 60))       # per client address: batches of browser errors

TOO_FAST = "You're sending requests quickly. Please wait a few seconds and try again."
