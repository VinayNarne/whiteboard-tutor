"""
Light and dark themes: text contrast (WCAG AA) on every screen and open menu, persistence across reload,
no flash of the wrong theme. Needs a backend (LP_BACKEND, default :8001) and Vite (:5173/:5174) running; skips itself otherwise.
"""
import json
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


UI = next((u for u in ("http://localhost:5173", "http://localhost:5174") if _up(u)), "http://localhost:5173")
pytestmark = pytest.mark.skipif(not (_up(f"{BACKEND}/health") and _up(UI)),
                                reason="a backend (LP_BACKEND, default :8001) and the Vite frontend (:5173 or :5174) must be running")

# Scans visible text for contrast. Backgrounds are composited from the element up to the page, so translucent
# panels (color-mix with transparent) are measured correctly. SVG content (the paper whiteboard) is excluded.
SCAN_JS = r"""
() => {
  const parse = c => {
    let m = c.match(/^color\(srgb ([\d.e-]+) ([\d.e-]+) ([\d.e-]+)(?: \/ ([\d.e-]+))?\)$/);
    if (m) return [m[1] * 255, m[2] * 255, m[3] * 255, m[4] === undefined ? 1 : +m[4]];
    m = c.match(/^rgba?\(([\d.]+)[, ]+([\d.]+)[, ]+([\d.]+)(?:[,/ ]+([\d.]+))?\)$/);
    if (m) return [+m[1], +m[2], +m[3], m[4] === undefined ? 1 : +m[4]];
    return [0, 0, 0, 0];
  };
  const over = (top, bottom) => {
    const a = top[3] + bottom[3] * (1 - top[3]);
    if (a === 0) return [0, 0, 0, 0];
    return [0, 1, 2].map(i => (top[i] * top[3] + bottom[i] * bottom[3] * (1 - top[3])) / a).concat([a]);
  };
  const bgOf = el => {
    const stack = [];
    for (let e = el; e; e = e.parentElement) stack.push(parse(getComputedStyle(e).backgroundColor));
    let out = [255, 255, 255, 1];
    for (let i = stack.length - 1; i >= 0; i--) out = over(stack[i], out);
    return out;
  };
  const lum = ([r, g, b]) => {
    const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  };
  const ratio = (fg, bg) => {
    const [a, b] = [lum(fg), lum(bg)].sort((x, y) => y - x);
    return (a + 0.05) / (b + 0.05);
  };
  const fails = []; let checked = 0;
  document.querySelectorAll('body *').forEach(el => {
    if (el.closest('svg') || el.closest('button:disabled') || el.classList.contains('sr-only')) return;
    const own = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
    if (!own) return;
    const cs = getComputedStyle(el), r = el.getBoundingClientRect();
    if (cs.visibility === 'hidden' || cs.display === 'none' || r.width === 0 || r.height === 0 || +cs.opacity === 0) return;
    const bg = bgOf(el), fg = over(parse(cs.color), bg);
    const size = parseFloat(cs.fontSize), large = size >= 24 || (size >= 18.66 && +cs.fontWeight >= 700);
    const need = large ? 3 : 4.5, got = ratio(fg, bg);
    checked++;
    if (got < need) fails.push(`${el.textContent.trim().slice(0, 30)} | ${got.toFixed(2)} < ${need} | ${cs.color} on rgb(${bg.slice(0, 3).map(Math.round)})`);
  });
  return { checked, fails };
}
"""

CHAT_TURNS = [
    {"role": "user", "content": "Explain what a packet is", "timestamp": "2026-10-04T10:00:00"},
    {"role": "assistant", "timestamp": "2026-10-04T10:00:05",
     "content": "A **packet** is a small unit of data.\n- The **header** carries addresses.\n- The payload is the data itself.\n\nFor example `ping` sends tiny packets.\n```python\npacket = {'src': '10.0.0.5'}\n```"},
]


@pytest.fixture()
def notebook():
    nb = requests.post(f"{API}/notebooks", json={"topic": "Theme check"}).json()["id"]
    pg = requests.get(f"{API}/notebooks/{nb}").json()["pages"][0]["id"]
    frag = '<g id="t1"><rect x="80" y="200" width="300" height="120"/><text x="100" y="260" font-size="16">Hello</text></g>'
    seed.draw_live(pg, "t1", frag, "Hello.")
    yield nb, pg
    requests.delete(f"{API}/notebooks/{nb}")


def _launch(p, theme):
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    ctx.add_init_script(f"try {{ localStorage.setItem('theme', '{theme}'); }} catch (e) {{}}")
    return browser, ctx.new_page()


def _with_chat(page, nb):
    """Show a realistic conversation without calling the model: answer the notebook fetch with chat turns added."""
    def handler(route):
        resp = route.fetch()
        data = resp.json()
        data["chat_turns"] = CHAT_TURNS
        route.fulfill(response=resp, body=json.dumps(data))
    page.route(f"**/api/notebooks/{nb}", handler)


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_text_contrast_meets_aa_on_every_screen_and_menu(theme, notebook):
    from playwright.sync_api import sync_playwright, expect

    nb, pg = notebook
    problems = []

    def scan(label, page):
        result = page.evaluate(SCAN_JS)
        assert result["checked"] > 5, f"{label}: scanner found almost no text ({result['checked']})"
        problems.extend(f"[{theme}] {label}: {f}" for f in result["fails"])

    with sync_playwright() as p:
        browser, page = _launch(p, theme)
        try:
            page.goto(UI, wait_until="networkidle")
            assert page.evaluate("document.documentElement.dataset.theme") == theme
            expect(page.locator("[id^=recent-notebook-]").first).to_be_visible()
            scan("landing", page)
            page.get_by_role("button", name="Appearance", exact=True).click()
            scan("landing / appearance menu", page)
            page.keyboard.press("Escape")

            _with_chat(page, nb)
            page.goto(f"{UI}/?notebook_id={nb}&page_id={pg}", wait_until="networkidle")
            expect(page.get_by_role("log")).to_contain_text("packet")
            scan("tutor screen", page)
            for menu in ("View", "Export", "Edit", "Notebook", "Tutor's voice", "More"):
                page.get_by_role("button", name=menu, exact=True).click()
                scan(f"menu {menu}", page)
                page.keyboard.press("Escape")
            page.get_by_role("button", name="Notebook", exact=True).click()
            page.get_by_role("menuitem", name="Keyboard shortcuts").click()
            expect(page.get_by_role("dialog")).to_be_visible()
            scan("shortcuts dialog", page)
            page.keyboard.press("Escape")
            page.get_by_role("button", name="Notebook", exact=True).click()
            page.get_by_role("menuitem", name="Overview and export").click()
            scan("overview dialog", page)
        finally:
            browser.close()
    assert not problems, "contrast failures:\n" + "\n".join(problems[:25])


def test_choice_is_made_in_the_ui_persists_across_reload_and_applies_before_first_paint():
    from playwright.sync_api import sync_playwright, expect

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
        try:
            page.goto(UI, wait_until="networkidle")
            assert page.evaluate("document.documentElement.dataset.theme") == "light"      # default
            page.get_by_role("button", name="Appearance", exact=True).click()
            assert page.get_by_role("menuitemradio", name="Light").get_attribute("aria-checked") == "true"
            page.get_by_role("menuitemradio", name="Dark").click()
            assert page.evaluate("document.documentElement.dataset.theme") == "dark"
            bg = page.evaluate("getComputedStyle(document.body).backgroundColor")
            assert bg == "rgb(20, 23, 28)", bg                                              # the dark --bg token

            page.reload(wait_until="commit")
            # the inline script in index.html sets the attribute before any app code runs (no light flash)
            page.wait_for_function("document.documentElement.dataset.theme === 'dark'", timeout=3000)
            page.wait_for_load_state("networkidle")
            page.get_by_role("button", name="Appearance", exact=True).click()
            assert page.get_by_role("menuitemradio", name="Dark").get_attribute("aria-checked") == "true"
            page.get_by_role("menuitemradio", name="Light").click()
            assert page.evaluate("document.documentElement.dataset.theme") == "light"
            assert page.evaluate("localStorage.getItem('theme')") == "light"
        finally:
            browser.close()


def test_match_system_follows_the_operating_system_setting():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, color_scheme="dark")
        ctx.add_init_script("try { localStorage.setItem('theme', 'system'); } catch (e) {}")
        page = ctx.new_page()
        try:
            page.goto(UI, wait_until="networkidle")
            assert page.evaluate("document.documentElement.dataset.theme") == "dark"
            page.emulate_media(color_scheme="light")                                       # OS switches live
            page.wait_for_function("document.documentElement.dataset.theme === 'light'", timeout=3000)
        finally:
            browser.close()
