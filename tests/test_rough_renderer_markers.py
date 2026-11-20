"""
Regression: the hand-drawn board renderer (frontend/src/services/roughRenderer.ts) must not drop what the drawing agent asked for on a line.
Rough.js rebuilds a <line> from its end points and stroke, so a `marker-end` arrowhead and a `stroke-dasharray` pattern used to vanish
(found in docs/BENCHMARK_CONTROLLED.md: about half of all requested arrowheads never reached the screen).

The real roughifySvgFragment runs in headless Chromium against a Vite dev server: a running one on :5173/:5174 is reused, otherwise the test starts its
own on a free port and stops it afterwards. No backend, no model, no network beyond localhost. Skips when node, Vite, Playwright or Pillow are missing.
"""
import io
import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest
import requests

pytest.importorskip("PIL")
sync_api = pytest.importorskip("playwright.sync_api")
from PIL import Image  # noqa: E402

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
MODULE = "/src/services/roughRenderer.ts"

MARKER = ('<defs><marker id="arrow_blue" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
          '<path d="M 0 1 L 9 5 L 0 9 z" fill="#2563eb"/></marker></defs>')

SUMMARY_JS = """(out) => {
  const d = new DOMParser().parseFromString('<svg xmlns="http://www.w3.org/2000/svg">' + out + '</svg>', 'image/svg+xml');
  const res = {markers: d.querySelectorAll('marker').length, ids: {}};
  d.querySelectorAll('[id]').forEach(e => {
    const all = [e, ...e.querySelectorAll('*')];
    const attr = name => all.map(x => x.getAttribute(name)).filter(Boolean);
    res.ids[e.id] = {tags: all.map(x => x.tagName), marker_end: attr('marker-end'), marker_start: attr('marker-start'), dash: attr('stroke-dasharray')};
  });
  return res;
}"""


def _up(url):
    try:
        return requests.get(url + MODULE, timeout=2).status_code == 200
    except requests.RequestException:
        return False


@pytest.fixture(scope="module")
def frontend_url():
    running = next((u for u in ("http://localhost:5173", "http://localhost:5174") if _up(u)), None)
    if running:
        yield running
        return
    node, vite = shutil.which("node"), FRONTEND_DIR / "node_modules" / "vite" / "bin" / "vite.js"
    if not node or not vite.exists():
        pytest.skip("needs node and frontend/node_modules (npm install in frontend/)")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    proc = subprocess.Popen([node, str(vite), "--port", str(port), "--strictPort", "--host", "127.0.0.1"], cwd=FRONTEND_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(60):
            if _up(url):
                break
            time.sleep(0.5)
        else:
            pytest.skip("the Vite dev server did not start in 30 s")
        yield url
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture(scope="module")
def page(frontend_url):
    with sync_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:  # noqa: BLE001 - browser binaries not installed
            pytest.skip(f"Chromium not available: {e}")
        pg = browser.new_page(viewport={"width": 400, "height": 300})
        pg.goto(frontend_url, wait_until="domcontentloaded")
        yield pg
        browser.close()


def roughify(pg, fragment):
    """(the renderer's output string, a summary of it: marker definitions kept, and per element id its tags, markers and dash patterns)"""
    out = pg.evaluate("async ([mod, frag]) => (await import(mod)).roughifySvgFragment(frag, { roughness: 1.1 })", [MODULE, fragment])
    return out, pg.evaluate(SUMMARY_JS, out)


def test_a_line_keeps_its_arrowhead_and_the_marker_definition(page):
    _, s = roughify(page, MARKER + '<line id="end" x1="50" y1="50" x2="250" y2="50" stroke="#111" stroke-width="3" marker-end="url(#arrow_blue)"/>'
                                   '<line id="start" x1="250" y1="90" x2="50" y2="90" stroke="#111" stroke-width="3" marker-start="url(#arrow_blue)"/>')
    assert s["markers"] == 1, "the <marker> definition must survive"
    assert s["ids"]["end"]["marker_end"] == ["url(#arrow_blue)"], "marker-end was dropped from the <line>"
    assert s["ids"]["start"]["marker_start"] == ["url(#arrow_blue)"], "marker-start was dropped from the <line>"


def test_a_line_inside_a_group_keeps_its_arrowhead(page):
    """real fragments wrap their shapes in <g id=element>: the renderer recurses into the group"""
    _, s = roughify(page, '<g id="el">' + MARKER + '<line id="inner" x1="50" y1="50" x2="250" y2="50" stroke="#111" marker-end="url(#arrow_blue)"/>'
                                                   '<rect id="box" x="60" y="120" width="100" height="40" fill="#eee" stroke="#111"/></g>')
    assert s["ids"]["inner"]["marker_end"] == ["url(#arrow_blue)"]
    assert "path" in s["ids"]["box"]["tags"] and "rect" not in s["ids"]["box"]["tags"], "other shapes are still redrawn by hand"


def test_the_arrowhead_is_visible_on_screen(page):
    """red line, blue head: after the fix blue pixels sit at the line's end; before it the head was never drawn"""
    out, _ = roughify(page, MARKER + '<line id="l" x1="50" y1="100" x2="250" y2="100" stroke="#e11d48" stroke-width="3" marker-end="url(#arrow_blue)"/>')
    page.evaluate("""(svg) => { document.body.innerHTML = '<svg id="t" xmlns="http://www.w3.org/2000/svg" width="400" height="300" style="position:fixed;left:0;top:0;background:#fff">' + svg + '</svg>'; }""", out)
    img = Image.open(io.BytesIO(page.screenshot(clip={"x": 0, "y": 0, "width": 400, "height": 300}))).convert("RGB")
    blue = sum(1 for x in range(225, 265) for y in range(80, 120) if (lambda p: p[2] > 180 and p[0] < 90 and p[1] < 130)(img.getpixel((x, y))))
    assert blue > 40, f"no arrowhead drawn at the end of the line (blue pixels: {blue})"


def test_a_line_with_marker_none_or_without_a_marker_is_still_drawn_by_hand(page):
    _, s = roughify(page, '<line id="plain" x1="50" y1="50" x2="250" y2="50" stroke="#111"/><line id="none" x1="50" y1="90" x2="250" y2="90" stroke="#111" marker-end="none"/>')
    for name in ("plain", "none"):
        assert "line" not in s["ids"][name]["tags"] and "path" in s["ids"][name]["tags"], f"{name}: expected a Rough.js path, got {s['ids'][name]['tags']}"
        assert not s["ids"][name]["marker_end"]


def test_a_path_arrow_is_unchanged(page):
    _, s = roughify(page, MARKER + '<path id="p" d="M 50 50 L 250 50" stroke="#111" fill="none" marker-end="url(#arrow_blue)"/>')
    assert s["ids"]["p"]["tags"] == ["path"] and s["ids"]["p"]["marker_end"] == ["url(#arrow_blue)"]


def test_a_dash_pattern_survives_on_lines_and_shapes(page):
    _, s = roughify(page, '<line id="dl" x1="50" y1="50" x2="250" y2="50" stroke="#111" stroke-width="3" stroke-dasharray="8,5"/>'
                          '<rect id="dr" x="50" y="90" width="120" height="60" fill="none" stroke="#111" stroke-dasharray="6 4"/>'
                          '<line id="solid" x1="50" y1="200" x2="250" y2="200" stroke="#111"/>')
    assert s["ids"]["dl"]["dash"] and s["ids"]["dl"]["dash"][0].replace(",", " ").split() == ["8", "5"], "stroke-dasharray was dropped from the <line>"
    assert s["ids"]["dr"]["dash"] and s["ids"]["dr"]["dash"][0].split() == ["6", "4"], "stroke-dasharray was dropped from the <rect>"
    assert not s["ids"]["solid"]["dash"], "a solid line must stay solid"


def test_a_dashed_line_with_an_arrowhead_keeps_both(page):
    _, s = roughify(page, MARKER + '<line id="both" x1="50" y1="50" x2="250" y2="50" stroke="#111" stroke-width="3" stroke-dasharray="8,5" marker-end="url(#arrow_blue)"/>')
    assert s["ids"]["both"]["marker_end"] == ["url(#arrow_blue)"] and s["ids"]["both"]["dash"]


def test_texture_proof_hatching_wash_and_a_stable_wobble(page):
    """LP_PAINT=svg: chart shading marked hatch becomes pencil lines (no solid fill), a shape marked wash carries the class on its
    fill path only (the watercolour filter must not blur the outline), and the same shape is drawn the same way every time."""
    hatch = '<polygon points="10,90 90,90 90,10" fill="#0F766E" fill-opacity="0.18" stroke="none" class="hatch"/>'
    out, _ = roughify(page, hatch)
    assert "fill-opacity" not in out and 'fill="none"' in out and out.count("M") >= 8   # many pencil lines at full strength, no solid fill
    wash = '<rect x="10" y="10" width="80" height="40" fill="#E3F1EF" stroke="#0F766E" class="wash"/>'
    out, _ = roughify(page, wash)
    tags = page.evaluate("""(s) => { const d = new DOMParser().parseFromString('<svg xmlns="http://www.w3.org/2000/svg">' + s + '</svg>', 'image/svg+xml');
        return [...d.querySelectorAll('.wash')].map(e => [e.tagName, e.getAttribute('stroke')]); }""", out)
    assert tags == [["path", "none"]]                                                        # only the fill path
    assert roughify(page, wash)[0] == out and roughify(page, hatch)[0] == roughify(page, hatch)[0]   # seeded: identical on replay
