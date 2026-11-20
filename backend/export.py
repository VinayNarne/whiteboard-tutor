"""
backend/export.py
Self-contained, print-ready HTML for a notebook: every page's drawing (clean vector), what the tutor said
about each element, and the conversation. Open it in a browser and use Print -> Save as PDF.
"""
from html import escape
from typing import List

from engine.fonts import inject_trusted_font
from engine.markers import strip_markers
from engine.sanitiser import sanitize_svg

CANVAS_VIEWBOX = "0 0 1200 800"

_CSS = """
:root { --ink:#1F2A37; --ink-2:#5B6472; --accent:#0F766E; --border:#E2DDD2; --paper:#FFFDF7; }
* { box-sizing: border-box; }
body { font-family: Inter, system-ui, sans-serif; color: var(--ink); max-width: 880px; margin: 0 auto; padding: 32px 20px; line-height: 1.6; }
h1 { font-size: 28px; margin: 0 0 4px; } h2 { font-size: 20px; margin: 0 0 12px; color: var(--accent); }
.meta { color: var(--ink-2); font-size: 14px; margin-bottom: 28px; }
section.page { margin-bottom: 40px; }
.board { border: 1px solid var(--border); border-radius: 10px; background: var(--paper); overflow: hidden; }
.board svg { display: block; width: 100%; height: auto; }
ol.said { padding-left: 20px; } ol.said li { margin-bottom: 10px; }
.el { font-size: 12px; color: var(--ink-2); display: block; }
.turn { margin: 8px 0; } .who { font-weight: 600; font-size: 13px; color: var(--ink-2); }
.note { color: var(--ink-2); font-style: italic; }
@media print {
  body { padding: 0; } section.page { break-before: page; } section.page:first-of-type { break-before: auto; }
  .board, .turn, ol.said li { break-inside: avoid; } * { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
}
"""


def _board_svg(current_svg: str) -> str:
    """Page drawing as one sanitised <svg>; falls back to a note rather than failing the export."""
    if not current_svg or not current_svg.strip():
        return '<p class="note">Nothing was drawn on this page.</p>'
    try:
        wrapped = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{CANVAS_VIEWBOX}">{current_svg}</svg>'
        return inject_trusted_font(sanitize_svg(wrapped))
    except Exception:
        return '<p class="note">This page\'s drawing could not be rendered in the export.</p>'


def build_notebook_html(notebook, pages: List[dict], turns: List[dict], print_on_load: bool = False) -> str:
    """
    notebook: object with .title, .topic, .created_at
    pages: [{page_number, title, summary, status, current_svg, narrations: [(element_id, text)]}]
    turns: [{role, content}]
    """
    out = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
           f"<meta name='viewport' content='width=device-width, initial-scale=1'>"
           f"<title>{escape(notebook.title or notebook.topic)}</title><style>{_CSS}</style></head><body>",
           f"<h1>{escape(notebook.title or notebook.topic)}</h1>",
           f"<p class='meta'>{escape(notebook.topic)} &middot; {len(pages)} page(s) &middot; "
           f"created {notebook.created_at:%d %b %Y}</p>"]
    for p in pages:
        title = p["title"] or f"Page {p['page_number']}"
        out.append(f"<section class='page'><h2>{p['page_number']}. {escape(title)}</h2>")
        if p["summary"]:
            out.append(f"<p class='meta'>{escape(p['summary'])}</p>")
        out.append(f"<div class='board'>{_board_svg(p['current_svg'])}</div>")
        if p["narrations"]:
            out.append("<h3>What the tutor said</h3><ol class='said'>")
            for eid, text in p["narrations"]:
                label = escape(eid.replace("_", " "))
                spoken = strip_markers(text)
                out.append(f"<li><span class='el'>{label}</span>{escape(spoken)}</li>")
            out.append("</ol>")
        out.append("</section>")
    if turns:
        out.append("<section class='page'><h2>Conversation</h2>")
        for t in turns:
            who = "You" if t["role"] == "user" else "Tutor"
            out.append(f"<div class='turn'><span class='who'>{who}</span><div>{escape(t['content'])}</div></div>")
        out.append("</section>")
    if print_on_load:
        out.append("<script>window.addEventListener('load', function () { setTimeout(function () { window.print(); }, 400); });</script>")
    out.append("</body></html>")
    return "".join(out)
