"""
A hard wall-clock ceiling for one model call (engine/author.py MODEL_CEILING_S = 90 s).

The httpx timeout (60 s) limits the silence between bytes. A server that sends the headers and then trickles the body, one piece at a time with gaps under that timeout,
is never cut by it (tests/measure_timeout_semantics.py: a 5 s call with a 2 s timeout). So the call is wrapped in asyncio.wait_for. Both ways, with the REAL SDK client
against a local server, scaled to a 3 s ceiling (the 30 s healthy call of the real setting is 1 s here): a trickling body is cut at the ceiling and becomes
ModelUnreachable (a failed turn, typed 503); a normal call and a slow healthy call are untouched.
"""
import asyncio
import json
import socket
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from openai import AzureOpenAI

sys.path.insert(0, str(Path(__file__).parent.parent))

import engine.author as author
from engine.author import ModelUnreachable

CEILING = 3.0
BODY = json.dumps({"id": "x", "object": "chat.completion", "created": 0, "model": "m", "choices": [{"index": 0, "finish_reason": "stop",
      "message": {"role": "assistant", "content": "A plain answer."}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}).encode()


class Server:
    """A tiny HTTP server for one request: 'normal' answers at once, 'slow' says nothing for `delay` seconds first, 'trickle' sends the headers at once and the body in
    pieces one second apart."""

    def __init__(self, mode, delay=0.0):
        self.mode, self.delay = mode, delay
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(2)
        self.url = f"http://127.0.0.1:{self.sock.getsockname()[1]}"
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        try:
            conn, _ = self.sock.accept()
            data = b""
            while b"\r\n\r\n" not in data:
                data += conn.recv(65536)
            head, _, rest = data.partition(b"\r\n\r\n")
            need = int([l for l in head.split(b"\r\n") if l.lower().startswith(b"content-length")][0].split(b":")[1])
            while len(rest) < need:
                rest += conn.recv(65536)
            time.sleep(self.delay)
            conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: " + str(len(BODY)).encode() + b"\r\n\r\n")
            if self.mode == "trickle":
                step = len(BODY) // 9 + 1
                for i in range(0, len(BODY), step):
                    conn.sendall(BODY[i:i + step])
                    time.sleep(1)
            else:
                conn.sendall(BODY)
            conn.close()
        except OSError:
            pass            # the client gave up
        finally:
            self.sock.close()


def run(server, ceiling=CEILING):
    """One tutor turn against the local server; the httpx timeout is generous (60 s) so only the ceiling can cut a call. Returns (text or the exception, seconds).
    The seconds are taken INSIDE the coroutine: asyncio.run() joins the abandoned worker thread when it closes its loop, which a running server never does per request."""
    client = AzureOpenAI(api_key="k", azure_endpoint=server.url, api_version="2024-08-01-preview", timeout=httpx.Timeout(60.0, connect=2.0), max_retries=0)

    async def noop(*a, **k):
        pass

    async def turn():
        t0 = time.time()
        try:
            out = await author.run_whiteboard_author("nb", "pg", "active", "hi", [], {"current_svg": None, "element_count": 0}, "", set(), noop, noop)
        except ModelUnreachable as e:
            out = e
        return out, time.time() - t0
    with patch.object(author, "MODEL_CEILING_S", ceiling), patch.object(author, "get_azure_client", lambda: client), patch("engine.author.logger"):
        return asyncio.run(turn())


@pytest.fixture(scope="module", autouse=True)
def _warm_up_the_sdk():
    """The first call of a process spends over a second importing inside the worker thread; that is not what these tests measure."""
    run(Server("normal"))


def test_a_body_that_trickles_in_is_cut_at_the_ceiling_and_becomes_model_unreachable():
    out, took = run(Server("trickle"))
    assert isinstance(out, ModelUnreachable)
    assert CEILING - 0.3 <= took < CEILING + 1.0, f"cut at the ceiling ({CEILING} s), not when the 9 s body would have finished: {took:.1f} s"


def test_the_same_trickle_is_not_cut_without_the_ceiling():
    """What the ceiling is for: with only the 60 s httpx timeout the trickling call runs to its end."""
    text, took = run(Server("trickle"), ceiling=60.0)
    assert text == "A plain answer." and took > CEILING + 2


def test_a_normal_call_is_untouched():
    text, took = run(Server("normal"))
    assert text == "A plain answer." and took < 2


def test_a_slow_healthy_call_a_third_of_the_ceiling_is_untouched():
    """The real setting: a 30 s healthy call under a 90 s ceiling. Scaled: 1 s under 3 s."""
    text, took = run(Server("slow", delay=1.0))
    assert text == "A plain answer." and 0.9 <= took < CEILING
