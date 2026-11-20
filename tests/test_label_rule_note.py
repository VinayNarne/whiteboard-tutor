"""
A card-sized rectangle with no <text> in the same drawing used to be REJECTED ("every card must include text labels").
It is now a log note only. Why: it was a content rule, and in baseline C it caused 243 of 259 retries once the prompt no
longer demanded labels: the tutor draws a shape and its label as separate elements, and legitimate drawings (bars, cells,
plot areas) have no text of their own.

Still rejected (unchanged): anything physically wrong with a drawing.
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.events import EngineEvent
from engine.author import _handle_draw_new_element
from engine.validator import find_layout_issues, has_text_less_card, validate_geometry

CARD_NO_TEXT = '<g id="el"><rect x="100" y="100" width="300" height="140" fill="#cde"/></g>'
CARD_WITH_TEXT = '<g id="el"><rect x="100" y="100" width="300" height="140"/><text x="120" y="170" font-size="18">Label</text></g>'


def _draw(fragment, element_id="el", current=None, existing_ids=None):
    async def emit(*a, **k):
        pass
    saved = []

    async def persist(**k):
        saved.append(k)
    with patch("engine.author.generate_narration_audio", return_value=(1.0, 5, {"is_synthetic": False})), \
            patch("engine.author.logger") as log:
        r = asyncio.run(_handle_draw_new_element("nb", "pg", "active", element_id, fragment, "Words.", current, emit, persist))
    events = [c.args[0] for c in log.info.call_args_list]
    return r, saved, events


def test_a_large_rectangle_with_no_text_passes_the_geometry_check():
    assert validate_geometry(CARD_NO_TEXT)["valid"]
    assert validate_geometry(CARD_WITH_TEXT)["valid"]


def test_a_large_rectangle_with_no_text_is_drawn_stored_and_logged():
    r, saved, events = _draw(CARD_NO_TEXT)
    assert r["status"] == "ok" and len(saved) == 1
    assert EngineEvent.UNLABELED_CARD_NOTE in events


def test_a_card_with_text_is_not_noted():
    r, saved, events = _draw(CARD_WITH_TEXT)
    assert r["status"] == "ok" and len(saved) == 1
    assert EngineEvent.UNLABELED_CARD_NOTE not in events


@pytest.mark.parametrize("fragment,expected", [
    (CARD_NO_TEXT, True),
    (CARD_WITH_TEXT, False),
    ('<g id="b"><rect x="10" y="10" width="40" height="20"/></g>', False),                         # small shape: not a card
    ('<g id="f"><rect x="0" y="0" width="1200" height="800"/></g>', False),                          # a frame is the frame guard's job
    ('<g id="l"><line x1="0" y1="0" x2="9" y2="9"/></g>', False),
])
def test_has_text_less_card(fragment, expected):
    assert has_text_less_card(fragment) is expected


def test_the_two_advisory_hints_are_unchanged_and_still_shown_to_the_tutor():
    assert any("has no label inside it" in h for h in find_layout_issues(CARD_NO_TEXT))
    tall_empty = ('<g id="c"><rect x="100" y="100" width="400" height="400"/><rect x="120" y="120" width="100" height="40"/>'
                  '<text x="125" y="145">a</text></g>')
    assert any("empty at the bottom" in h for h in find_layout_issues(tall_empty))
    r, _, events = _draw(CARD_NO_TEXT)
    assert "no label" in r["layout_hint"] and EngineEvent.LAYOUT_HINT in events


# ---- drawings that are broken in another way are still rejected, text or no text ---------------------------------

BROKEN = [
    ("outside the canvas, no text", '<g id="el"><rect x="1000" y="700" width="400" height="300"/></g>', "bleeds canvas"),
    ("outside the canvas, with text", '<g id="el"><rect x="1000" y="700" width="400" height="300"/><text x="1010" y="720">T</text></g>', "bleeds canvas"),
    ("overlapping labels", '<g id="el"><text x="100" y="100" font-size="20">First long label</text><text x="110" y="104" font-size="20">Second long label</text></g>', "overlap"),
    ("transform", '<g id="el"><rect x="100" y="100" width="300" height="140"/><text x="1" y="2" transform="rotate(90)">T</text></g>', "transform"),
    ("background frame, no text", '<g id="el"><rect x="0" y="0" width="1200" height="800"/></g>', "background frame"),
]


@pytest.mark.parametrize("name,fragment,needle", BROKEN, ids=[b[0] for b in BROKEN])
def test_other_broken_drawings_are_still_rejected(name, fragment, needle):
    r, saved, _ = _draw(fragment)
    assert r["status"] == "error" and needle in r["detail"], r
    assert saved == []


def test_overlapping_an_existing_element_is_still_rejected():
    existing = '<g id="first"><rect x="100" y="100" width="300" height="140"/><text x="120" y="170">One</text></g>'
    r, saved, _ = _draw('<g id="el"><rect x="120" y="120" width="300" height="140"/></g>', current=existing)
    assert r["status"] == "error" and "overlaps existing" in r["detail"] and saved == []


def test_a_duplicate_id_is_still_rejected():
    existing = '<g id="el"><rect x="100" y="100" width="300" height="140"/><text x="120" y="170">One</text></g>'
    r, saved, _ = _draw('<g id="el"><rect x="600" y="100" width="300" height="140"/></g>', current=existing)
    assert r["status"] == "error" and saved == []
