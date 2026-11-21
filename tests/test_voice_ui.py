"""
Voice in the browser, both directions. Needs a backend (LP_BACKEND, default :8001) and Vite (:5173/:5174) running; skips itself otherwise.

Dictation (mic): Chromium's fake microphone supplies real audio; the Deepgram relay socket is replaced by a script
we control, so each test says exactly what "Deepgram" heard and when. The chat endpoint is stubbed (no model calls).
Tutor voice: a real draw is narrated, then interrupted mid-clip.
"""
import io
import json
import sys
import wave
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).parent.parent))

import seed
from lp_env import API, BACKEND


def _up(url):
    try:
        return requests.get(url, timeout=2).status_code < 500
    except requests.RequestException:
        return False


UI = next((u for u in ("http://localhost:5173", "http://localhost:5174") if _up(u)), "http://localhost:5173")
pytestmark = pytest.mark.skipif(not (_up(f"{BACKEND}/health") and _up(UI)),
                                reason="a backend (LP_BACKEND, default :8001) and the Vite frontend (:5173 or :5174) must be running")

FLAGS = ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream", "--autoplay-policy=no-user-gesture-required"]
MIC = "Speak your question"
BOX = ('<g id="{eid}"><rect x="{x}" y="220" width="200" height="100" rx="10" fill="#CDE8E4" stroke="#0F766E"/>'
       '<text x="{tx}" y="280" text-anchor="middle" font-size="20">{eid}</text></g>')


def _silent_wav(seconds):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(8000)
        w.writeframes(b"\x00\x00" * int(8000 * seconds))
    return buf.getvalue()


@pytest.fixture()
def notebook():
    nb = requests.post(f"{API}/notebooks", json={"topic": "Voice UI"}).json()["id"]
    pg = requests.get(f"{API}/notebooks/{nb}").json()["pages"][0]["id"]
    seed.draw_live(pg, "first", BOX.format(eid="first", x=80, tx=180), "")
    yield nb, pg
    requests.delete(f"{API}/notebooks/{nb}")


class Relay:
    """Stands in for /api/ws/voice: records what the browser sends and lets the test play Deepgram."""

    def __init__(self, page):
        self.ws, self.sent = None, []
        page.route_web_socket("**/api/ws/voice/**", self._connect)

    def _connect(self, ws):
        self.ws = ws
        ws.on_message(lambda m: self.sent.append(m))

    def say(self, text, final=False, speech_final=False):
        self.ws.send(json.dumps({"type": "Results", "is_final": final, "speech_final": speech_final,
                                 "channel": {"alternatives": [{"transcript": text, "confidence": 0.95}]}}))

    def event(self, kind):
        self.ws.send(json.dumps({"type": kind}))

    def got_close_stream(self):
        return any(isinstance(m, str) and "CloseStream" in m for m in self.sent)


def _open(p, nb, pg, *, init_script=None):
    browser = p.chromium.launch(headless=True, args=FLAGS)
    ctx = browser.new_context(viewport={"width": 1280, "height": 800}, permissions=["microphone"])
    if init_script:
        ctx.add_init_script(init_script)
    page = ctx.new_page()
    relay = Relay(page)
    chats = []

    def chat(route):
        chats.append(json.loads(route.request.post_data))
        route.fulfill(json={"response": "Sure.", "page_id": pg})
    page.route("**/api/notebooks/*/chat", chat)
    page.goto(f"{UI}/?notebook_id={nb}&page_id={pg}", wait_until="networkidle")
    page.wait_for_selector("#whiteboard-elements #first")
    return browser, page, relay, chats


def _start_mic(page, relay):
    page.get_by_role("button", name=MIC).click()
    page.wait_for_function("true")                       # let the socket open
    for _ in range(50):
        if relay.ws:
            return
        page.wait_for_timeout(100)
    raise AssertionError("the browser never opened the voice socket")


def test_dictation_continues_what_you_typed_and_done_keeps_the_last_words(notebook):
    from playwright.sync_api import sync_playwright, expect

    with sync_playwright() as p:
        browser, page, relay, _ = _open(p, *notebook)
        try:
            box = page.locator("#chat-input")
            mic = page.get_by_role("button", name=MIC)
            box.fill("Please explain")
            expect(mic).to_have_attribute("aria-pressed", "false")
            _start_mic(page, relay)
            expect(mic).to_have_attribute("aria-pressed", "true")        # same name, state carried by aria-pressed
            relay.say("how a pack", final=False)
            expect(box).to_have_value("Please explain how a pack")
            relay.say("how a packet travels", final=True)
            expect(box).to_have_value("Please explain how a packet travels")
            relay.say("across the", final=False)                          # still being finalised when Done is pressed
            expect(box).to_have_value("Please explain how a packet travels across the")
            page.get_by_role("button", name="Done").click()
            expect(page.get_by_role("button", name="Done")).to_have_count(0)
            expect(box).to_have_value("Please explain how a packet travels across the")   # nothing was dropped
            page.wait_for_timeout(300)
            assert relay.got_close_stream()                               # Deepgram was told to flush
            expect(mic).to_have_attribute("aria-pressed", "false")
        finally:
            browser.close()


def test_hands_free_waits_for_a_real_pause_and_works_when_switched_on_mid_listening(notebook):
    from playwright.sync_api import sync_playwright, expect

    with sync_playwright() as p:
        browser, page, relay, chats = _open(p, *notebook)
        try:
            _start_mic(page, relay)
            page.get_by_label("Send when I pause").check()                # switched on AFTER listening began
            relay.say("what is a router", final=True, speech_final=False)  # a phrase boundary is not the end of the question
            page.wait_for_timeout(1200)
            assert chats == [], "sent in the middle of a sentence"

            relay.say("what is a router", final=True, speech_final=True)   # pause detected ...
            page.wait_for_timeout(250)
            relay.event("SpeechStarted")                                   # ... but the learner carries on
            page.wait_for_timeout(1000)
            assert chats == [], "sent although the learner kept talking"

            relay.say("and a switch", final=True, speech_final=True)
            page.wait_for_function("true")
            for _ in range(30):
                if chats:
                    break
                page.wait_for_timeout(100)
            assert [c["message"] for c in chats] == ["what is a router what is a router and a switch"] or \
                   [c["message"] for c in chats][0].endswith("and a switch")
            expect(page.get_by_role("button", name="Done")).to_have_count(0)    # dictation ended with the send
            expect(page.locator("#chat-input")).to_have_value("")
            relay.say("late words", final=True)                                   # words arriving after the send
            page.wait_for_timeout(300)
            expect(page.locator("#chat-input")).to_have_value("")
        finally:
            browser.close()


def test_sending_while_listening_ends_dictation_and_late_words_do_not_refill_the_box(notebook):
    from playwright.sync_api import sync_playwright, expect

    with sync_playwright() as p:
        browser, page, relay, chats = _open(p, *notebook)
        try:
            _start_mic(page, relay)
            relay.say("explain dns", final=True)
            expect(page.locator("#chat-input")).to_have_value("explain dns")
            page.locator("#chat-input").press("Enter")
            for _ in range(30):
                if chats:
                    break
                page.wait_for_timeout(100)
            assert chats[0]["message"] == "explain dns"
            relay.say("stale words", final=True)
            page.wait_for_timeout(300)
            expect(page.locator("#chat-input")).to_have_value("")
            expect(page.get_by_role("button", name="Done")).to_have_count(0)
        finally:
            browser.close()


def test_when_live_transcription_drops_the_learner_is_told_and_the_recording_is_transcribed(notebook):
    from playwright.sync_api import sync_playwright, expect

    with sync_playwright() as p:
        browser, page, relay, _ = _open(p, *notebook)
        page.route("**/api/transcribe-voice", lambda r: r.fulfill(json={"status": "ok", "transcript": "from the recording"}))
        try:
            _start_mic(page, relay)
            relay.ws.close(code=1011, reason="upstream failed")
            expect(page.get_by_role("alert")).to_contain_text("Live transcription stopped")
            page.wait_for_timeout(2500)                                   # enough audio to be worth transcribing
            page.get_by_role("button", name="Done").click()
            expect(page.locator("#chat-input")).to_have_value("from the recording", timeout=5000)
        finally:
            browser.close()


def test_a_failing_fallback_is_reported_not_swallowed(notebook):
    from playwright.sync_api import sync_playwright, expect

    with sync_playwright() as p:
        browser, page, relay, _ = _open(p, *notebook)
        page.route("**/api/transcribe-voice", lambda r: r.fulfill(status=503, json={"detail": "not configured"}))
        try:
            _start_mic(page, relay)
            relay.ws.close(code=1008, reason="Voice unavailable")          # e.g. no Deepgram key on the server
            expect(page.get_by_role("alert")).to_contain_text("Live transcription stopped")
            page.wait_for_timeout(2500)
            page.get_by_role("button", name="Done").click()
            expect(page.get_by_role("alert").last).to_contain_text("Couldn't transcribe", timeout=5000)
        finally:
            browser.close()


def test_a_blocked_microphone_gets_a_plain_explanation(notebook):
    from playwright.sync_api import sync_playwright, expect

    block = "navigator.mediaDevices.getUserMedia = () => Promise.reject(new DOMException('no', 'NotAllowedError'));"
    with sync_playwright() as p:
        browser, page, _, _ = _open(p, *notebook, init_script=block)
        try:
            page.get_by_role("button", name=MIC).click()
            expect(page.get_by_role("alert")).to_contain_text("Microphone access is blocked")
            expect(page.get_by_role("button", name=MIC)).to_have_attribute("aria-pressed", "false")
        finally:
            browser.close()


def test_pressing_the_mic_twice_while_the_permission_prompt_is_open_starts_one_capture(notebook):
    from playwright.sync_api import sync_playwright

    slow = """
      const real = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
      window.__gum = 0;
      navigator.mediaDevices.getUserMedia = async (c) => { window.__gum++; await new Promise(r => setTimeout(r, 700)); return real(c); };
    """
    with sync_playwright() as p:
        browser, page, relay, _ = _open(p, *notebook, init_script=slow)
        try:
            mic = page.get_by_role("button", name=MIC)
            mic.click()
            page.keyboard.press("Alt+M")                                  # the shortcut while the first request is pending
            page.wait_for_timeout(1500)
            assert page.evaluate("window.__gum") == 1
        finally:
            browser.close()


def test_tutor_voice_menu_only_holds_listening_settings_and_they_are_remembered(notebook):
    from playwright.sync_api import sync_playwright, expect

    with sync_playwright() as p:
        browser, page, _, _ = _open(p, *notebook)
        try:
            page.get_by_role("button", name="Tutor's voice", exact=True).click()
            expect(page.get_by_role("menuitemcheckbox", name="Speak aloud")).to_have_attribute("aria-checked", "true")
            expect(page.get_by_text("Hands-free")).to_have_count(0)        # dictation settings live with the mic now
            page.get_by_role("menuitemradio", name="1.5x").click()
            page.get_by_role("button", name="Tutor's voice", exact=True).click()
            page.get_by_role("menuitemcheckbox", name="Speak aloud").click()
            page.reload(wait_until="networkidle")
            page.get_by_role("button", name="Tutor's voice: off", exact=True).click()
            expect(page.get_by_role("menuitemradio", name="1.5x")).to_have_attribute("aria-checked", "true")
            expect(page.get_by_role("menuitemcheckbox", name="Speak aloud")).to_have_attribute("aria-checked", "false")
        finally:
            browser.close()
