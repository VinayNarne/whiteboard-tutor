"""
tests/test_e2e_smoke.py
Deterministic browser smoke test of the core learner flow. No LLM calls: the notebook is seeded through
the API (two tiny TTS calls at most), then a real Chromium drives the UI:

  drawing renders -> density counter -> dialog keyboard handling -> save & lock -> reload keeps drawing
  -> replay runs -> new page

Needs the backend (127.0.0.1:8001) and frontend (localhost:5173 or 5174) running; skips itself otherwise.
Run alone:  python -m pytest tests/test_e2e_smoke.py -q
"""
import sys
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


# `npm run dev` serves on 5173 by default; our launch config pins 5174. Use whichever is running.
UI = next((u for u in ("http://localhost:5173", "http://localhost:5174") if _up(u)), "http://localhost:5173")


pytestmark = pytest.mark.skipif(
    not (_up(f"{BACKEND}/health") and _up(UI)),
    reason="a backend (LP_BACKEND, default :8001) and the Vite frontend (:5173 or :5174) must be running",
)


def _box(i):
    x = 80 + i * 380
    return (f'<g id="smoke_{i}"><rect x="{x}" y="200" width="300" height="140" rx="10" fill="#E3F1EF" stroke="#0F766E"/>'
            f'<text x="{x + 150}" y="280" text-anchor="middle" font-size="18">Smoke box {i}</text></g>')


@pytest.fixture()
def notebook():
    nb = requests.post(f"{API}/notebooks", json={"topic": "Smoke test"}).json()["id"]
    page = requests.get(f"{API}/notebooks/{nb}").json()["pages"][0]["id"]
    for i in range(2):
        seed.draw_live(page, f"smoke_{i}", _box(i), f"Box {i}.")
    yield nb, page
    requests.delete(f"{API}/notebooks/{nb}")


def test_core_learner_flow(notebook):
    from playwright.sync_api import sync_playwright, expect

    nb, page_id = notebook
    url = f"{UI}/?notebook_id={nb}&page_id={page_id}"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        try:
            # 1. both seeded elements render on the whiteboard and the counter is right
            page.goto(url, wait_until="networkidle")
            expect(page.locator("svg[role='img']")).to_be_visible()
            expect(page.locator("#whiteboard-elements #smoke_0")).to_have_count(1)
            expect(page.locator("#whiteboard-elements #smoke_1")).to_have_count(1)
            expect(page.get_by_text("2 / 15 elements")).to_be_visible()
            expect(page.get_by_role("log")).to_be_attached()

            # 2. keyboard: dialog traps focus, Escape closes it and returns focus to the opener
            page.get_by_role("button", name="Notebook", exact=True).click()
            page.get_by_role("menuitem", name="Keyboard shortcuts").click()
            dialog = page.get_by_role("dialog")
            expect(dialog).to_be_visible()
            for _ in range(6):
                page.keyboard.press("Tab")
                assert page.evaluate("document.querySelector('[role=dialog]').contains(document.activeElement)")
            page.keyboard.press("Escape")
            expect(dialog).to_have_count(0)
            assert page.evaluate("document.activeElement.textContent.trim()") == "Notebook"  # focus back on the menu

            # 2b. menus are keyboard-operable: Enter opens, arrows move, Escape closes and returns focus
            view = page.get_by_role("button", name="View", exact=True)
            view.focus()
            page.keyboard.press("Enter")
            expect(page.get_by_role("menu", name="View")).to_be_visible()
            first = page.evaluate("document.activeElement.textContent.trim()")
            page.keyboard.press("ArrowDown")
            assert page.evaluate("document.activeElement.textContent.trim()") != first
            page.keyboard.press("Escape")
            expect(page.get_by_role("menu")).to_have_count(0)
            assert page.evaluate("document.activeElement.textContent.trim()") == "View"

            # 3. save & lock, then the API agrees and the lock control disappears
            page.get_by_role("button", name="Save and lock").click()
            expect(page.get_by_role("button", name="Save and lock")).to_have_count(0)
            status = requests.get(f"{API}/notebooks/{nb}").json()["pages"][0]["status"]
            assert status == "saved"

            # 4. reload: silent view keeps the drawing; replay runs
            page.reload(wait_until="networkidle")
            expect(page.locator("#whiteboard-elements #smoke_1")).to_have_count(1)
            page.get_by_title("Replay this page").click()
            expect(page.get_by_text("Replaying")).to_be_visible(timeout=5000)

            # 5. new page from the sidebar
            page.get_by_role("button", name="New page", exact=True).click()
            expect(page.locator(".page-row")).to_have_count(2, timeout=5000)

            assert not errors, f"uncaught page errors: {errors}"
        finally:
            browser.close()


def test_landing_page_create_with_depth_and_reopen_from_recent():
    from playwright.sync_api import sync_playwright, expect

    topic = "Smoke landing topic"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
            try:
                page.goto(UI, wait_until="networkidle")
                expect(page.get_by_role("heading", name="Learning Platform")).to_be_visible()
                expect(page.locator("#create-notebook-btn")).to_be_disabled()  # nothing typed yet

                # depth is a radio group; choosing Deep dive and pressing Enter starts the notebook
                # the radio group is one Tab stop; arrow keys move the choice
                page.get_by_role("radio", name="Standard").focus()
                page.keyboard.press("ArrowRight")
                expect(page.get_by_role("radio", name="Deep dive")).to_have_attribute("aria-checked", "true")
                assert page.evaluate("document.activeElement.textContent.trim()") == "Deep dive"
                page.locator("#topic-input").fill(topic)
                page.keyboard.press("Enter")
                expect(page.get_by_role("heading", level=1, name=topic)).to_be_visible(timeout=8000)  # no "[Deep-dive]" prefix shown

                # back to the landing page: it is listed with a depth tag and reopens from the keyboard
                page.get_by_role("button", name="Notebooks", exact=True).click()
                row = page.locator("[id^=recent-notebook-]", has_text=topic)
                expect(row).to_have_count(1)
                expect(row).to_contain_text("Deep dive")
                row.focus()
                page.keyboard.press("Enter")
                expect(page.get_by_role("heading", level=1, name=topic)).to_be_visible(timeout=8000)
            finally:
                browser.close()
    finally:
        for nb in requests.get(f"{API}/notebooks").json():
            if topic in nb["topic"]:
                requests.delete(f"{API}/notebooks/{nb['id']}")


def test_refused_message_shows_friendly_error_and_keeps_the_text():
    from playwright.sync_api import sync_playwright, expect

    nb = requests.post(f"{API}/notebooks", json={"topic": "Refusal check"}).json()["id"]
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
            try:
                page.goto(f"{UI}/?notebook_id={nb}", wait_until="networkidle")
                box = page.locator("#chat-input")
                assert box.get_attribute("maxlength") == "4000"      # the browser stops overlong input up front

                page.route("**/chat", lambda r: r.fulfill(status=429, content_type="application/json",
                                                           json={"detail": "You're sending requests quickly. Please wait a few seconds and try again."}))
                box.fill("Explain gravity")
                page.locator("#chat-send-btn").click()
                expect(page.get_by_role("alert")).to_contain_text("sending requests quickly")
                expect(box).to_have_value("Explain gravity")          # nothing the learner typed is lost

                page.unroute("**/chat")
                page.route("**/chat", lambda r: r.fulfill(status=422, content_type="application/json",
                                                           json={"detail": [{"loc": ["body", "message"], "msg": "too long"}]}))
                page.locator("#chat-send-btn").click()
                expect(page.get_by_role("alert")).to_contain_text("under 4,000 characters")
                assert "msg" not in page.get_by_role("alert").inner_text()   # no raw validation JSON shown
                expect(page.locator("#chat-input")).to_have_value("Explain gravity")
                page.get_by_role("button", name="Dismiss").click()
                expect(page.get_by_role("alert")).to_have_count(0)
            finally:
                browser.close()
    finally:
        requests.delete(f"{API}/notebooks/{nb}")


def test_unreachable_server_is_reported_not_swallowed():
    from playwright.sync_api import sync_playwright, expect

    nb = requests.post(f"{API}/notebooks", json={"topic": "Offline check"}).json()["id"]
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
            try:
                page.goto(f"{UI}/?notebook_id={nb}", wait_until="networkidle")
                page.route("**/chat", lambda r: r.abort())             # the request never reaches the server
                page.locator("#chat-input").fill("Are you there?")
                page.locator("#chat-send-btn").click()
                expect(page.get_by_role("alert")).to_contain_text("Could not reach the server")
                expect(page.locator("#chat-input")).to_have_value("Are you there?")
                expect(page.get_by_text("Working…")).to_have_count(0)   # no spinner stuck forever
            finally:
                browser.close()
    finally:
        requests.delete(f"{API}/notebooks/{nb}")


def test_whiteboard_exports_zoom_and_replay_bar_work(notebook):
    """Covers the pieces that live in the extracted whiteboard modules: export, zoom, replay bar."""
    from playwright.sync_api import sync_playwright, expect

    nb, page_id = notebook
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, accept_downloads=True)
        ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin=UI)
        page = ctx.new_page()
        try:
            page.goto(f"{UI}/?notebook_id={nb}&page_id={page_id}", wait_until="networkidle")
            expect(page.locator("#whiteboard-elements #smoke_1")).to_have_count(1)

            # zoom controls
            page.locator("#zoom-in-btn").click()
            expect(page.locator("#zoom-reset-btn")).to_have_text("115%")
            page.locator("#zoom-reset-btn").click()
            expect(page.locator("#zoom-reset-btn")).to_have_text("100%")

            # SVG export: a real download of the full 1200x800 board with the drawn elements in it
            page.get_by_role("button", name="Export", exact=True).click()
            with page.expect_download() as dl:
                page.get_by_role("menuitem", name="Export SVG").click()
            svg_file = dl.value
            assert svg_file.suggested_filename == f"whiteboard-{page_id}.svg"
            svg_text = Path(svg_file.path()).read_text(encoding="utf-8")
            assert "<svg" in svg_text and 'width="1200"' in svg_text and 'height="800"' in svg_text and "smoke_0" in svg_text

            # PNG export: a real PNG
            page.get_by_role("button", name="Export", exact=True).click()
            with page.expect_download() as dl:
                page.get_by_role("menuitem", name="Export PNG").click()
            png_file = dl.value
            assert png_file.suggested_filename == f"whiteboard-{page_id}.png"
            assert Path(png_file.path()).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"

            # copy markup: toast + clipboard
            page.get_by_role("button", name="Export", exact=True).click()
            page.get_by_role("menuitem", name="Copy SVG markup").click()
            expect(page.get_by_text("SVG copied")).to_be_visible()
            assert page.evaluate("navigator.clipboard.readText()").startswith("<svg")

            # replay bar appears while replaying and shows progress
            page.get_by_title("Replay this page").click()
            expect(page.get_by_text("Replaying")).to_be_visible(timeout=5000)
            expect(page.get_by_role("button", name="1.25x")).to_be_visible()
        finally:
            browser.close()


def test_undo_last_drawing_from_menu_and_keyboard(notebook):
    from playwright.sync_api import sync_playwright, expect

    nb, page_id = notebook                      # fixture draws smoke_0 and smoke_1
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
        try:
            page.goto(f"{UI}/?notebook_id={nb}&page_id={page_id}", wait_until="networkidle")
            els = page.locator("#whiteboard-elements")
            expect(els.locator("#smoke_1")).to_have_count(1)
            expect(page.get_by_text("2 / 15 elements")).to_be_visible()

            # menu: removes the newest drawing live, counter follows, server agrees
            page.get_by_role("button", name="Edit", exact=True).click()
            page.get_by_role("menuitem", name="Undo last drawing").click()
            expect(els.locator("#smoke_1")).to_have_count(0)
            expect(els.locator("#smoke_0")).to_have_count(1)
            expect(page.get_by_text("1 / 15 elements")).to_be_visible()
            assert [e["element_id"] for e in requests.get(f"{API}/notebooks/{nb}/pages/{page_id}/events").json()["events"]] == ["smoke_0"]

            # Ctrl+Z while typing in the chat box must NOT undo (it undoes the typing)
            page.locator("#chat-input").fill("draft message")
            page.keyboard.press("Control+z")
            page.wait_for_timeout(600)
            expect(els.locator("#smoke_0")).to_have_count(1)

            # Ctrl+Z on the board removes the last remaining drawing, and the Edit menu goes away (nothing to undo)
            page.locator("body").click(position={"x": 700, "y": 880})   # focus leaves the chat box
            page.keyboard.press("Control+z")
            expect(els.locator("#smoke_0")).to_have_count(0)
            expect(page.get_by_text("0 / 15 elements")).to_be_visible()
            expect(page.get_by_role("button", name="Edit", exact=True)).to_have_count(0)
        finally:
            browser.close()


def test_locked_page_offers_no_undo(notebook):
    from playwright.sync_api import sync_playwright, expect

    nb, page_id = notebook
    requests.post(f"{API}/notebooks/{nb}/pages/{page_id}/save")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
        try:
            page.goto(f"{UI}/?notebook_id={nb}&page_id={page_id}", wait_until="networkidle")
            expect(page.locator("#whiteboard-elements #smoke_1")).to_have_count(1)
            expect(page.get_by_role("button", name="Edit", exact=True)).to_have_count(0)
            page.locator("body").click(position={"x": 700, "y": 880})
            page.keyboard.press("Control+z")
            page.wait_for_timeout(600)
            expect(page.locator("#whiteboard-elements #smoke_1")).to_have_count(1)   # nothing happened
            assert requests.get(f"{API}/notebooks/{nb}").json()["pages"][0]["element_count"] == 2
        finally:
            browser.close()
