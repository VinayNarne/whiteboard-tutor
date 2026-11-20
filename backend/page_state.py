"""
backend/page_state.py
A page's drawing is defined by its event log. These helpers derive the cached values from it, so any change to the
log (such as undo) can recompute them instead of patching them.
"""
import json
import os
from typing import Iterable, Optional, Tuple


def is_drawing(event) -> bool:
    """Draw events that carry SVG (annotation events reuse the table but store JSON)."""
    return event.kind == "draw" and event.svg_fragment.lstrip().startswith("<")


def rebuild_page_svg(events: Iterable) -> Tuple[str, int]:
    """(composite SVG, drawn-element count) from events in seq order: draws append, modifies replace."""
    svg, count = "", 0
    for e in sorted(events, key=lambda ev: ev.seq):
        if is_drawing(e):
            svg += "\n" + e.svg_fragment
            count += 1
        elif e.kind == "modify" and e.old_svg_fragment:
            svg = svg.replace(e.old_svg_fragment, e.svg_fragment, 1)
    return svg, count


def annotation_target_ids(event) -> Tuple[Optional[str], Optional[str]]:
    """(target_element_id, from_element_id) of an annotate event, else (None, None)."""
    if event.kind != "annotate":
        return None, None
    try:
        data = json.loads(event.svg_fragment)
    except (ValueError, TypeError):
        return None, None
    return data.get("target_element_id"), data.get("from_element_id")


RECENT_PAGES_WITH_SUMMARY = 20   # older pages are listed by title only, so the prompt does not grow with the notebook
SUMMARY_CHARS = 300
TITLE_CHARS = 80


def _summary_text(page) -> str:
    """The summary line text the tutor may read for an earlier page ("" = none). TEST ONLY: LP_TEST_SUMMARIES_OFF=1 hides every summary (titles stay), the "off" setting of
    eval M (docs/BASELINE.md); unset, the default, summaries are shown."""
    if os.getenv("LP_TEST_SUMMARIES_OFF") == "1":
        return ""
    return (page.summary or "").strip()


def prior_pages_summary(pages) -> str:
    """One line per earlier page for the tutor's context. Bounded: ~20 short summaries + one short line per older page."""
    pages = list(pages)
    older, recent = pages[:-RECENT_PAGES_WITH_SUMMARY], pages[-RECENT_PAGES_WITH_SUMMARY:]
    lines = [f"Page {p.page_number}: {(p.title or 'Untitled')[:TITLE_CHARS]} (earlier page)" for p in older]
    lines += [f"Page {p.page_number}: {(p.title or 'Untitled')[:TITLE_CHARS]} — {(_summary_text(p) or 'No summary.')[:SUMMARY_CHARS]}"
              for p in recent]
    return "\n".join(lines)


def summaries_in_context(pages) -> int:
    """How many earlier pages show a summary (not just a title) in the tutor's context."""
    return sum(1 for p in list(pages)[-RECENT_PAGES_WITH_SUMMARY:] if _summary_text(p))
