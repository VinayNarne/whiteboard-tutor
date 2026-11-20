"""
Render-time text fitting (frontend/src/services/textFit.ts): an overflowing <text> inside ONE rect / circle / ellipse is drawn smaller;
every other label is left exactly as written, and nothing is ever enlarged or moved.

The real module runs in headless Chromium against a Vite dev server with the real Inter font (same fixtures as test_rough_renderer_markers.py).
Cases are ported from the proof of concept (12 synthetic labels). No backend, no model, no network beyond localhost.
"""
import pytest

pytest.importorskip("PIL")
pytest.importorskip("playwright.sync_api")
from test_rough_renderer_markers import frontend_url, page  # noqa: E402,F401  (fixtures)

from engine.fonts import get_trusted_font_css  # noqa: E402

MODULE = "/src/services/textFit.ts"
FONT = 'font-family="Inter, sans-serif"'
MIN_PX = 11


def cell(i):
    return 20 + (i % 3) * 390, 20 + (i // 3) * 190


def _case(i, body):
    ox, oy = cell(i)
    return body(ox, oy)


CASES = {  # name -> (fragment builder, expected: "shrunk" | "unchanged")
    "long label, middle anchor, rect": (lambda x, y: f'<rect x="{x+10}" y="{y+30}" width="200" height="60" fill="#e0f2fe" stroke="#111"/><text x="{x+110}" y="{y+66}" text-anchor="middle" font-size="18" {FONT}>Authentication Service Gateway</text>', "shrunk"),
    "short label, rect": (lambda x, y: f'<rect x="{x+10}" y="{y+30}" width="200" height="60" fill="#e0f2fe" stroke="#111"/><text x="{x+110}" y="{y+66}" text-anchor="middle" font-size="18" {FONT}>API</text>', "unchanged"),
    "long, start anchor, no room to the left": (lambda x, y: f'<rect x="{x+10}" y="{y+30}" width="200" height="60" fill="#dcfce7" stroke="#111"/><text x="{x+20}" y="{y+66}" font-size="16" {FONT}>Compare the results with the prediction</text>', "unchanged"),
    "long, end anchor, no room to the right": (lambda x, y: f'<rect x="{x+10}" y="{y+30}" width="200" height="60" fill="#fef9c3" stroke="#111"/><text x="{x+200}" y="{y+66}" text-anchor="end" font-size="16" {FONT}>Compare the results with the prediction</text>', "unchanged"),
    "multiline, long second line": (lambda x, y: f'<rect x="{x+10}" y="{y+20}" width="180" height="80" fill="#fce7f3" stroke="#111"/><text x="{x+100}" y="{y+52}" text-anchor="middle" font-size="16" {FONT}><tspan x="{x+100}">Server checks</tspan><tspan x="{x+100}" dy="22">credentials against the database</tspan></text>', "shrunk"),
    "long label in a circle, below the floor": (lambda x, y: f'<circle cx="{x+90}" cy="{y+80}" r="55" fill="#e0f2fe" stroke="#111"/><text x="{x+90}" y="{y+85}" text-anchor="middle" font-size="18" {FONT}>External Microphone</text>', "unchanged"),
    "long label in an ellipse": (lambda x, y: f'<ellipse cx="{x+110}" cy="{y+80}" rx="90" ry="40" fill="#ede9fe" stroke="#111"/><text x="{x+110}" y="{y+85}" text-anchor="middle" font-size="16" {FONT}>Persistent Storage Layer</text>', "shrunk"),
    "label in the overlap of two rects": (lambda x, y: f'<rect x="{x+10}" y="{y+30}" width="160" height="70" fill="#e0f2fe" stroke="#111"/><rect x="{x+120}" y="{y+50}" width="160" height="70" fill="#fef9c3" stroke="#111"/><text x="{x+145}" y="{y+85}" text-anchor="middle" font-size="14" {FONT}>Shared cache between both</text>', "unchanged"),
    "card nested in a panel, label wider than the card": (lambda x, y: f'<rect x="{x+10}" y="{y+20}" width="360" height="130" fill="#f1f5f9" stroke="#111"/><rect x="{x+110}" y="{y+60}" width="140" height="50" fill="#e0f2fe" stroke="#111"/><text x="{x+180}" y="{y+90}" text-anchor="middle" font-size="16" {FONT}>Load Balancer Primary Node</text>', "unchanged"),
    "title above its card (outside)": (lambda x, y: f'<rect x="{x+60}" y="{y+60}" width="200" height="50" fill="#e0f2fe" stroke="#111"/><text x="{x+160}" y="{y+40}" text-anchor="middle" font-size="16" {FONT}>Component overview diagram</text>', "unchanged"),
    "header spanning two cards": (lambda x, y: f'<rect x="{x+10}" y="{y+50}" width="170" height="60" fill="#e0f2fe" stroke="#111"/><rect x="{x+190}" y="{y+50}" width="170" height="60" fill="#dcfce7" stroke="#111"/><text x="{x+170}" y="{y+85}" text-anchor="middle" font-size="16" {FONT}>Both services share one gateway</text>', "unchanged"),
    "one long word": (lambda x, y: f'<rect x="{x+10}" y="{y+40}" width="120" height="40" fill="#e0f2fe" stroke="#111"/><text x="{x+70}" y="{y+66}" text-anchor="middle" font-size="18" {FONT}>Internationalization</text>', "shrunk"),
}

# per text: computed font size, tspan font-sizes, and whether its glyph band sits inside its unique container
MEASURE_JS = """async (frags) => {
  const NS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('width', 1200); svg.setAttribute('height', 800); svg.setAttribute('viewBox', '0 0 1200 800');
  svg.style.cssText = 'position:fixed;left:0;top:0';
  svg.innerHTML = frags.join('\\n');
  document.body.appendChild(svg);
  await document.fonts.ready;
  const out = [...svg.querySelectorAll('text')].map(t => {
    const b = t.getBBox();
    return { size: parseFloat(getComputedStyle(t).fontSize), tspans: [...t.querySelectorAll('tspan')].map(x => x.getAttribute('font-size')), l: b.x, r: b.x + b.width, t: b.y, b: b.y + b.height, x: t.getAttribute('x'), y: t.getAttribute('y') };
  });
  svg.remove();
  return out;
}"""


@pytest.fixture(scope="module")
def fitted(page, frontend_url):  # noqa: F811
    page.add_style_tag(content=get_trusted_font_css())
    names = list(CASES)
    frags = [_case(i, CASES[n][0]) for i, n in enumerate(names)]
    entries = page.evaluate("async ([mod, f]) => [...(await (await import(mod)).fitTextInFragments(f)).entries()]", [MODULE, frags])
    fit_map = dict(entries)
    after = [fit_map.get(f, f) for f in frags]
    return {"names": names, "before": page.evaluate(MEASURE_JS, frags), "after": page.evaluate(MEASURE_JS, after), "frags": frags, "map": fit_map}


@pytest.mark.parametrize("name", list(CASES))
def test_case(fitted, name):
    i = fitted["names"].index(name)
    b, a = fitted["before"][i], fitted["after"][i]
    if CASES[name][1] == "unchanged":
        assert fitted["frags"][i] not in fitted["map"], f"{name}: the fragment must be returned untouched"
        assert a == b
        return
    assert fitted["frags"][i] in fitted["map"]
    assert MIN_PX <= a["size"] < b["size"], f"{name}: {b['size']} -> {a['size']}"
    assert a["size"] >= 0.7 * b["size"] - 0.05, "never below 70 % of the written size"
    assert (a["x"], a["y"]) == (b["x"], b["y"]), "a label is made smaller in place, never moved"
    assert a["l"] >= b["l"] - 0.6 and a["r"] <= b["r"] + 0.6 and a["t"] >= b["t"] - 0.6 and a["b"] <= b["b"] + 0.6, "the smaller label must sit inside its old footprint"


def test_multiline_scales_every_line(fitted):
    i = fitted["names"].index("multiline, long second line")
    b, a = fitted["before"][i], fitted["after"][i]
    ratio = a["size"] / b["size"]
    assert all(abs(float(new) - float(old) * ratio) < 0.05 for old, new in zip(b["tspans"], a["tspans"]) if old)


def test_nothing_is_ever_enlarged(fitted):
    assert all(a["size"] <= b["size"] + 1e-6 for a, b in zip(fitted["after"], fitted["before"]))


def test_a_board_with_no_overflow_returns_an_empty_map(page, frontend_url):  # noqa: F811
    r = page.evaluate("async ([mod, f]) => (await (await import(mod)).fitTextInFragments(f)).size",
                      [MODULE, ['<rect x="20" y="20" width="200" height="60" fill="#eee" stroke="#111"/><text x="120" y="56" text-anchor="middle" font-size="16">OK</text>']])
    assert r == 0
