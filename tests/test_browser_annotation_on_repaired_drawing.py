"""
An annotation (circle) on a drawing the model wrote as bare tags must draw, in a real browser.

Why: until the group repair (engine/grouping.py) a bare <rect> had no id, so the page could not find it: the engine answered "created
successfully" and the browser logged `Could not find target bounds` and drew nothing (docs/BASELINE.md, "Check before experiment H").
Needs a backend (LP_BACKEND) and Vite running; skips itself otherwise. Uses the real ElevenLabs voice for two short narrations.
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
                                reason="a backend (LP_BACKEND) and the Vite frontend must be running")

# What the tutor actually sends: a card as sibling tags with no <g>, and a single bare rectangle.
SIBLING_CARD = ('<rect x="60" y="120" width="330" height="180" fill="#cce5ff" stroke="#004085" stroke-width="3" rx="15"/>'
                '<text x="75" y="160" font-size="20">Law 1: First Law</text><text x="75" y="190" font-size="16">Rest stays at rest</text>')
BARE_RECT = '<rect x="460" y="120" width="330" height="180" fill="#d4edda" stroke="#155724" stroke-width="3" rx="15"/>'


@pytest.fixture()
def notebook():
    nb = requests.post(f"{API}/notebooks", json={"topic": "Annotation on a repaired drawing"}).json()["id"]
    pg = requests.get(f"{API}/notebooks/{nb}").json()["pages"][0]["id"]
    yield nb, pg
    requests.delete(f"{API}/notebooks/{nb}")


@pytest.mark.parametrize("eid,fragment", [("sibling_card", SIBLING_CARD), ("bare_rect", BARE_RECT)])
def test_a_circle_on_a_drawing_written_as_bare_tags_is_drawn(notebook, eid, fragment):
    from playwright.sync_api import sync_playwright

    nb, pg = notebook
    r = requests.post(f"{API}/notebooks/{nb}/pages/{pg}/draw", json={"element_id": eid, "svg_fragment": fragment, "narration": f"[[MARK:{eid}]] Here."})
    assert r.status_code == 200, r.text
    r = requests.post(f"{API}/notebooks/{nb}/pages/{pg}/annotate", json={
        "annotation_id": f"ring_{eid}", "style": "circle", "target_element_id": eid, "lifetime": "permanent", "narration": f"[[MARK:ring_{eid}]] Look."})
    assert r.status_code == 200, r.text

    stored = next(e for e in requests.get(f"{API}/notebooks/{nb}/pages/{pg}/events").json()["events"] if e["element_id"] == eid)
    assert f'id="{eid}"' in stored["svg_fragment"], "the stored drawing must carry the element id the annotation looks for"

    warnings = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
            page.on("console", lambda m: warnings.append(m.text) if m.type in ("warning", "error") else None)
            page.goto(f"{UI}/?notebook_id={nb}&page_id={pg}", wait_until="networkidle")
            page.wait_for_selector(f'#whiteboard-elements [id="{eid}"]', timeout=15000)     # the drawing can be found by its id
            page.wait_for_selector(f'#ring_{eid}.rough-annotation-mark', state="attached", timeout=10000)   # and the circle was drawn on it
            bbox = page.locator(f"#ring_{eid}").bounding_box()
            target = page.locator(f'#whiteboard-elements [id="{eid}"]').bounding_box()
            assert bbox and target and bbox["width"] > 20 and bbox["height"] > 20
            assert bbox["x"] <= target["x"] + target["width"] and bbox["x"] + bbox["width"] >= target["x"], "the circle is not around the drawing"
        finally:
            browser.close()
    assert not [w for w in warnings if "Could not find target bounds" in w], warnings
