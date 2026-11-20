"""
Text width is a LOG-ONLY note, never shown to the tutor and never a rejection: a label whose estimated width (characters x font size x 0.55) runs off the
canvas, past the right edge of the card it starts in, or into another element on the page is written to the log as `text_width_note`, so overflow can still
be measured offline. (Baseline K showed the same estimate as a hint to the tutor costs 15-22 redraws a run and does not improve the boards: docs/BASELINE.md.)
Both ways: the draw result carries nothing about it and the note is logged; labels that fit log nothing. The blocking checks keep their own, older, cruder text box.
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.events import EngineEvent
from engine import voice
from engine.author import _handle_draw_new_element
from engine.validator import (TEXT_WIDTH_FACTOR, estimate_text_width, find_layout_issues, find_text_width_hints,
                              find_text_width_issues)

ALIGN = {"characters": list("x"), "character_start_times_seconds": [0.0], "character_end_times_seconds": [1.0]}
CARD = '<rect x="60" y="120" width="300" height="100"/>'


def test_the_estimate_is_characters_times_font_size_times_055():
    assert TEXT_WIDTH_FACTOR == 0.55 and estimate_text_width("0123456789", 20) == pytest.approx(110.0)


# ---- fires ---------------------------------------------------------------------------------------------------------------------

def test_a_label_that_runs_past_the_right_edge_of_its_card():
    label = "Calculate mid = (low + high) // 2 = 3"                      # 37 chars x 16 x 0.55 = 326 px from x=75: ends at 401, card ends at 360
    [issue] = find_text_width_issues(f'<g id="a">{CARD}<text x="75" y="160" font-size="16">{label}</text></g>')
    assert issue["kind"] == "card" and issue["width"] == 326 and issue["over"] == 41
    [hint] = find_text_width_hints(f'<g id="a">{CARD}<text x="75" y="160" font-size="16">{label}</text></g>')
    assert hint == f'The label "{label}" is about 326 px wide at font size 16 and runs past the right edge of its card by about 41 px.'


def test_a_label_that_runs_off_the_canvas():
    [issue] = find_text_width_issues('<text x="1000" y="50" font-size="20">A long label near the edge of the board</text>')
    assert issue["kind"] == "canvas" and issue["over"] > 200
    assert "runs off the edge of the canvas" in find_text_width_hints('<text x="1000" y="50" font-size="20">A long label near the edge of the board</text>')[0]


def test_a_label_that_runs_into_an_element_already_on_the_page():
    existing = '<g id="other"><rect x="100" y="120" width="260" height="60"/></g>'
    [issue] = find_text_width_issues('<text x="400" y="150" font-size="16" text-anchor="middle">Centered label that is wide enough</text>', existing)
    assert issue["kind"] == "neighbour" and issue["over"] == "other"
    assert find_text_width_hints('<text x="400" y="150" font-size="16" text-anchor="middle">Centered label that is wide enough</text>',
                                 existing)[0].endswith("runs into 'other'.")


def test_text_anchor_end_and_the_default_font_size_are_handled():
    assert find_text_width_issues('<text x="20" y="50" text-anchor="end">0123456789</text>')[0]["kind"] == "canvas"     # ends at x=20, starts left of 0
    assert find_text_width_issues('<text x="1150" y="50">0123456789</text>')[0]["size"] == 16                            # no font-size: 16


# ---- silent --------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("fragment", [
    f'<g id="b">{CARD}<text x="75" y="160" font-size="16">Fits easily</text></g>',
    f'<g id="b">{CARD}<text x="75" y="160" font-size="16">Exactly about as wide as</text></g>',     # 25 x 8.8 = 220, ends at 295 < 360
    '<text x="100" y="50" font-size="20">Short title</text>',
    '<g id="b"><rect x="60" y="120" width="600" height="100"/><text x="75" y="160" font-size="16">A long label that has all the room it needs here</text></g>',
    '<rect x="60" y="120" width="300" height="100"/>',
    '<text x="75" y="160" font-size="16">   </text>',
])
def test_labels_that_fit_say_nothing(fragment):
    assert find_text_width_hints(fragment) == []


def test_ten_pixels_of_slack_before_a_card_is_said_to_be_overrun():
    # 20 chars x 20 x 0.55 = 220 px: from x=75 ends at 295; the card ends at 360 -> fits; shrink the card to end at 300 -> within the 10 px slack
    assert find_text_width_hints('<g id="b"><rect x="60" y="120" width="240" height="100"/><text x="75" y="160" font-size="20">01234567890123456789</text></g>') == []
    assert find_text_width_hints('<g id="b"><rect x="60" y="120" width="220" height="100"/><text x="75" y="160" font-size="20">01234567890123456789</text></g>')


def test_at_most_three_hints_and_the_blocking_hints_are_unchanged():
    many = "".join(f'<text x="1100" y="{40 + 30 * i}" font-size="16">Label number {i} that is long</text>' for i in range(6))
    assert len(find_text_width_hints(many)) == 3
    assert find_layout_issues('<rect x="60" y="120" width="300" height="100"/>')[0].startswith("The card at x=60")


# ---- never blocks, never reaches the tutor; written to the log -------------------------------------------------------------------

def _draw(fragment, current_svg=None):
    async def emit(kind, payload):
        pass

    async def persist(**k):
        persist.saved.append(k)
    persist.saved = []
    with patch.object(voice, "_call_elevenlabs_tts", lambda t: (b"MP3", ALIGN, 1.0, False)), patch("engine.author.logger") as log:
        r = asyncio.run(_handle_draw_new_element("nb", "pg", "active", "el", fragment, "[[MARK:el]] Hello.", current_svg, emit, persist))
    return r, persist.saved, [c.kwargs["data"] for c in log.info.call_args_list if c.args[0] == EngineEvent.TEXT_WIDTH_NOTE]


def test_a_drawing_with_an_overrunning_label_is_stored_and_the_tutor_is_told_nothing_but_the_log_has_the_note():
    r, saved, events = _draw(f'{CARD}<text x="75" y="160" font-size="16">Calculate mid = (low + high) // 2 = 3</text>')
    assert r["status"] == "ok" and saved, "the drawing is stored"
    assert "layout_hint" not in r and "px" not in str(r) and "wide" not in str(r), "the tutor result carries no width hint"
    assert len(events) == 1 and events[0]["element_id"] == "el"
    [issue] = events[0]["issues"]
    assert issue["kind"] == "card" and issue["width"] == 326 and issue["over"] == 41


def test_the_old_label_hints_still_reach_the_tutor_without_the_width_note_in_them():
    r, saved, events = _draw(f'{CARD}<text x="75" y="160" font-size="16">Calculate mid = (low + high) // 2 = 3</text><rect x="500" y="120" width="300" height="100"/>')
    assert r["status"] == "ok" and saved
    assert "The card at x=500" in r["layout_hint"] and "wide at font size" not in r["layout_hint"]
    assert len(events) == 1


def test_a_drawing_whose_labels_fit_logs_no_note():
    r, saved, events = _draw(f'{CARD}<text x="75" y="160" font-size="16">Fits easily</text>')
    assert r["status"] == "ok" and "layout_hint" not in r and events == []
