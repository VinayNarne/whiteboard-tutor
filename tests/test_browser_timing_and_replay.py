"""
Voice timing and replay in a real browser. Needs a backend and Vite running (LP_BACKEND overrides the default
http://127.0.0.1:8001); skips itself otherwise. Uses the real ElevenLabs voice, so it spends a few hundred characters.

1. test_element_appears_on_screen_at_the_spoken_word
   The server stores, per drawing, the second at which the marked word is spoken (alignment.json). In the browser we
   read the audio clock at the moment the element is actually PAINTED (two animation frames after it enters the DOM)
   and compare it with that second. The measured error is printed.
2. test_replay_brings_elements_back_in_original_order_with_each_ones_audio
   Saves a page of 4 drawings, replays it, and checks: the board clears, elements return in the original order, and
   each element's own audio file is played, in that order.
"""
import os
import sys
import time
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).parent.parent))

from lp_env import API, BACKEND
MAX_ERROR_MS = 150


def _up(url):
    try:
        return requests.get(url, timeout=2).status_code < 500
    except requests.RequestException:
        return False


UI = next((u for u in ("http://localhost:5173", "http://localhost:5174") if _up(u)), "http://localhost:5173")
pytestmark = pytest.mark.skipif(not (_up(f"{BACKEND}/health") and _up(UI)),
                                reason="a backend (LP_BACKEND) and the Vite frontend must be running")

# Records every audio clip the page plays (which file, when it started) and keeps the latest element for clock reads.
AUDIO_PROBE = """
(() => {
  window.__plays = [];
  const play = HTMLMediaElement.prototype.play;
  HTMLMediaElement.prototype.play = function () {
    window.__audio = this;
    window.__plays.push({ src: this.currentSrc || this.src, at: performance.now() });
    return play.apply(this, arguments);
  };
})();
"""

# For each watched id: the audio clock at the first paint after the element enters the DOM.
PAINT_PROBE = """
(ids) => {
  window.__seen = [];
  const watch = new Set(ids);
  new MutationObserver(() => {
    for (const id of watch) {
      if (document.getElementById(id) && !window.__seen.some(s => s.id === id)) {
        const rec = { id, domAt: performance.now(), audioAtDom: window.__audio ? window.__audio.currentTime : null };
        window.__seen.push(rec);
        requestAnimationFrame(() => requestAnimationFrame(() => {      // after the browser has painted it
          rec.paintedAt = performance.now();
          rec.audioAtPaint = window.__audio ? window.__audio.currentTime : null;
        }));
      }
    }
  }).observe(document.body, { childList: true, subtree: true });
}
"""


def _box(eid, x, y, label):
    return (f'<g id="{eid}"><rect x="{x}" y="{y}" width="240" height="110" rx="8" fill="#CDE8E4" stroke="#0F766E"/>'
            f'<text x="{x + 30}" y="{y + 62}" font-size="18">{label}</text></g>')


@pytest.fixture()
def notebook():
    nb = requests.post(f"{API}/notebooks", json={"topic": "Timing and replay"}).json()["id"]
    pg = requests.get(f"{API}/notebooks/{nb}").json()["pages"][0]["id"]
    yield nb, pg
    requests.delete(f"{API}/notebooks/{nb}")


def _open(p, nb, pg):
    browser = p.chromium.launch(headless=True, args=["--autoplay-policy=no-user-gesture-required"])
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    ctx.add_init_script(AUDIO_PROBE)
    page = ctx.new_page()
    page.goto(f"{UI}/?notebook_id={nb}&page_id={pg}", wait_until="networkidle")
    page.wait_for_selector("#chat-input")
    return browser, page


def test_element_appears_on_screen_at_the_spoken_word(notebook):
    from playwright.sync_api import sync_playwright

    nb, pg = notebook
    marker = "timing_box"
    narration = (f"Here we begin, and right now [[MARK:{marker}]] we highlight the primary state node on the canvas, "
                 "establishing the conceptual groundwork for the entire multi-step analysis.")
    with sync_playwright() as p:
        browser, page = _open(p, nb, pg)
        try:
            page.evaluate(PAINT_PROBE, [marker])
            r = requests.post(f"{API}/notebooks/{nb}/pages/{pg}/draw",
                              json={"element_id": marker, "svg_fragment": _box(marker, 120, 120, "State Node"), "narration": narration})
            assert r.status_code == 200, r.text

            ev = next(e for e in requests.get(f"{API}/notebooks/{nb}/pages/{pg}/events").json()["events"] if e["element_id"] == marker)
            align = requests.get(f"{BACKEND}{ev['alignment_url']}").json()
            assert align["provider"] == "elevenlabs", "this test needs the real voice (the silent fallback has no real timing)"
            expected = float(next(m for m in align["marker_timings"] if m["id"] == marker)["time"])
            assert expected >= 0.5, f"marker at {expected}s is too early to prove the element waits for the word"

            page.wait_for_timeout(150)
            assert page.query_selector(f"#whiteboard-elements #{marker}") is None, "the element showed up before its word"

            page.wait_for_selector(f"#whiteboard-elements #{marker}", timeout=15000)
            page.wait_for_function("window.__seen.length && window.__seen[0].paintedAt", timeout=3000)
            seen = page.evaluate("window.__seen[0]")
            error_ms = (seen["audioAtPaint"] - expected) * 1000
            lag_ms = seen["paintedAt"] - seen["domAt"]
            print(f"\n[voice timing] word spoken at {expected * 1000:.0f} ms; element painted when the audio clock read "
                  f"{seen['audioAtPaint'] * 1000:.0f} ms -> error {error_ms:+.0f} ms "
                  f"(DOM insert to paint: {lag_ms:.0f} ms; audio clock at DOM insert: {seen['audioAtDom'] * 1000:.0f} ms)")
            assert 0 <= error_ms <= MAX_ERROR_MS, f"painted {error_ms:+.0f} ms from the spoken word (limit {MAX_ERROR_MS} ms)"
        finally:
            browser.close()


def test_replay_brings_elements_back_in_original_order_with_each_ones_audio(notebook):
    from playwright.sync_api import sync_playwright

    nb, pg = notebook
    drawings = [("rep_a", 80, 120, "First"), ("rep_b", 400, 120, "Second"), ("rep_c", 80, 320, "Third"), ("rep_d", 400, 320, "Fourth")]
    order = [d[0] for d in drawings]
    for eid, x, y, label in drawings:
        r = requests.post(f"{API}/notebooks/{nb}/pages/{pg}/draw", json={
            "element_id": eid, "svg_fragment": _box(eid, x, y, label), "narration": f"[[MARK:{eid}]] This is the {label.lower()} box."})
        assert r.status_code == 200, r.text
    assert requests.post(f"{API}/notebooks/{nb}/pages/{pg}/save", json={}).status_code == 200

    stored = requests.get(f"{API}/notebooks/{nb}/pages/{pg}/events").json()["events"]
    assert [e["element_id"] for e in stored] == order and all(e["audio_url"] for e in stored), "setup: 4 drawings, each with audio"
    assert [e["seq"] for e in stored] == [1, 2, 3, 4]

    with sync_playwright() as p:
        browser, page = _open(p, nb, pg)
        try:
            page.wait_for_selector("#whiteboard-elements #rep_d")                      # saved page: everything visible at once
            assert page.locator("#whiteboard-elements [id^=rep_]").count() == 4
            page.evaluate(PAINT_PROBE, order)
            page.evaluate("window.__plays.length = 0")

            page.get_by_role("button", name="Replay").first.click()
            page.wait_for_timeout(120)
            cleared = page.locator("#whiteboard-elements [id^=rep_]").count()
            assert cleared < 4, "the board did not clear when replay started"

            page.wait_for_function("window.__seen.length === 4", timeout=60000)
            seen = [s["id"] for s in page.evaluate("window.__seen")]
            assert seen == order, f"elements returned as {seen}, expected {order}"

            # the app also plays a silent data: clip to unlock audio on click; only the tutor's own clips count
            page.wait_for_function("window.__plays.filter(p => p.src.includes('/static/')).length >= 4", timeout=30000)
            plays = [Path(pl["src"]).name for pl in page.evaluate("window.__plays") if "/static/" in pl["src"]][:4]
            assert plays == [Path(e["audio_url"]).name for e in stored], f"audio played {plays}"
            print(f"\n[replay] board cleared to {cleared} elements; order {seen}; audio files {plays}")
        finally:
            browser.close()
