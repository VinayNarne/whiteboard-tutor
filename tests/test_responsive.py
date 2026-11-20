"""
Responsive layout: laptop (rail + narrower chat), tablet and phone (one pane at a time with tabs).
Needs a backend (LP_BACKEND, default :8001) and Vite (:5173/:5174) running; skips itself otherwise.
"""
import sys
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).parent.parent))

from lp_env import API, BACKEND


def _up(url):
    try:
        return requests.get(url, timeout=2).status_code < 500
    except requests.RequestException:
        return False


UI = next((u for u in ("http://localhost:5173", "http://localhost:5174") if _up(u)), "http://localhost:5173")
pytestmark = pytest.mark.skipif(not (_up(f"{BACKEND}/health") and _up(UI)),
                                reason="a backend (LP_BACKEND, default :8001) and the Vite frontend (:5173 or :5174) must be running")

BOX = ('<g id="{eid}"><rect x="{x}" y="220" width="300" height="140" rx="10" fill="#CDE8E4" stroke="#0F766E"/>'
       '<text x="{tx}" y="290" text-anchor="middle" font-size="20">{eid}</text></g>')


def _draw(nb, pg, eid, x):
    r = requests.post(f"{API}/notebooks/{nb}/pages/{pg}/draw",
                      json={"element_id": eid, "svg_fragment": BOX.format(eid=eid, x=x, tx=x + 150), "narration": f"{eid}."})
    assert r.status_code == 200, r.text


@pytest.fixture()
def notebook():
    nb = requests.post(f"{API}/notebooks", json={"topic": "Responsive"}).json()["id"]
    pg = requests.get(f"{API}/notebooks/{nb}").json()["pages"][0]["id"]
    _draw(nb, pg, "first", 80)
    yield nb, pg
    requests.delete(f"{API}/notebooks/{nb}")


MEASURE = """() => {
  const w = s => { const e = document.querySelector(s); if (!e) return 0; const b = e.getBoundingClientRect(); return Math.round(b.width); };
  return { overflowX: document.documentElement.scrollWidth > innerWidth, board: w('svg[role=img]'),
           sidebar: w('[role=navigation]'), chat: w('[role=complementary]'), tabs: !!document.querySelector('[role=tablist]') };
}"""


def _open(p, nb, pg, width, height):
    browser = p.chromium.launch(headless=True)
    page = browser.new_context(viewport={"width": width, "height": height}).new_page()
    page.goto(f"{UI}/?notebook_id={nb}&page_id={pg}", wait_until="networkidle")
    page.wait_for_selector("#whiteboard-elements #first")
    return browser, page


@pytest.mark.parametrize("width,height,min_board,sidebar,chat,tabs", [
    (1280, 800, 560, 240, 380, False),     # desktop: unchanged
    (1024, 768, 560, 52, 320, False),      # laptop: page list becomes a rail, chat narrows, the board keeps its room
    (768, 1024, 700, 0, 0, True),          # tablet portrait: tabs, the board gets the full width
    (390, 800, 340, 0, 0, True),           # phone
])
def test_board_always_has_room_and_nothing_overflows(width, height, min_board, sidebar, chat, tabs, notebook):
    from playwright.sync_api import sync_playwright

    nb, pg = notebook
    with sync_playwright() as p:
        browser, page = _open(p, nb, pg, width, height)
        try:
            m = page.evaluate(MEASURE)
            assert not m["overflowX"], m
            assert m["board"] >= min_board, f"board only {m['board']}px wide at {width}px"
            assert m["tabs"] is tabs
            if not tabs:
                assert m["sidebar"] == sidebar and m["chat"] == chat, m
            # every toolbar control must be reachable on screen
            for name in ("Pan", "Pen", "Highlight", "Eraser", "View", "Export", "Notebook"):
                box = page.get_by_role("button", name=name, exact=True).first.bounding_box()
                assert box and box["x"] >= 0 and box["x"] + box["width"] <= width + 1, f"{name} off-screen at {width}px: {box}"
        finally:
            browser.close()


def test_phone_tabs_switch_panes_keep_the_drawing_and_are_keyboard_operable(notebook):
    from playwright.sync_api import sync_playwright, expect

    nb, pg = notebook
    with sync_playwright() as p:
        browser, page = _open(p, nb, pg, 390, 800)
        try:
            tabs = page.get_by_role("tab")
            expect(tabs).to_have_count(3)
            expect(page.get_by_role("tab", name="Board")).to_have_attribute("aria-selected", "true")
            expect(page.locator("#chat-input")).to_be_hidden()

            # Chat tab: the input and Send are on screen and usable
            page.get_by_role("tab", name="Chat").click()
            expect(page.locator("#chat-input")).to_be_visible()
            page.locator("#chat-input").fill("Hello")
            for sel in ("#chat-input", "#chat-send-btn"):
                b = page.locator(sel).bounding_box()
                assert b["x"] >= 0 and b["x"] + b["width"] <= 390 and b["y"] + b["height"] <= 800, (sel, b)
            expect(page.locator("#chat-input")).to_have_value("Hello")            # text survives tab switches

            # Pages tab: list and actions on screen; choosing a page returns to the board
            page.get_by_role("tab", name="Pages").click()
            expect(page.locator(".page-row")).to_have_count(1)
            expect(page.get_by_role("button", name="New page", exact=True)).to_be_visible()
            page.locator(".page-row").first.click()
            expect(page.get_by_role("tab", name="Board")).to_have_attribute("aria-selected", "true")
            expect(page.locator("#whiteboard-elements #first")).to_have_count(1)   # the drawing was never lost

            # keyboard: arrow keys move between tabs (roving tabindex)
            page.get_by_role("tab", name="Board").focus()
            page.keyboard.press("ArrowRight")
            expect(page.get_by_role("tab", name="Chat")).to_have_attribute("aria-selected", "true")
            assert page.evaluate("document.activeElement.id") == "tab-chat"
            page.keyboard.press("ArrowLeft")
            expect(page.get_by_role("tab", name="Board")).to_have_attribute("aria-selected", "true")
        finally:
            browser.close()


def test_phone_shows_a_dot_on_the_board_tab_when_the_tutor_draws_while_you_read_chat(notebook):
    from playwright.sync_api import sync_playwright, expect

    nb, pg = notebook
    with sync_playwright() as p:
        browser, page = _open(p, nb, pg, 390, 800)
        try:
            page.get_by_role("tab", name="Chat").click()
            expect(page.get_by_role("tab", name="Board")).not_to_contain_text("(new)")
            _draw(nb, pg, "second", 420)                                            # the tutor draws elsewhere
            expect(page.get_by_role("tab", name="Board")).to_contain_text("(new)", timeout=5000)
            page.get_by_role("tab", name="Board").click()
            expect(page.get_by_role("tab", name="Board")).not_to_contain_text("(new)")
            expect(page.locator("#whiteboard-elements #second")).to_have_count(1)    # and it is on the board
        finally:
            browser.close()


def test_laptop_rail_expands_and_wide_screens_stay_expanded(notebook):
    from playwright.sync_api import sync_playwright, expect

    nb, pg = notebook
    with sync_playwright() as p:
        browser, page = _open(p, nb, pg, 1024, 768)
        try:
            assert page.evaluate(MEASURE)["sidebar"] == 52
            page.get_by_role("button", name="Expand page list").click()              # the rail can still be opened
            expect(page.get_by_role("button", name="New page", exact=True)).to_be_visible()
            page.set_viewport_size({"width": 1400, "height": 800})                  # growing the window re-expands it
            page.wait_for_function("document.querySelector('[role=navigation]').getBoundingClientRect().width === 240")
        finally:
            browser.close()
