"""
One definition of "background frame": a single shape covering FRAME_CANVAS_FRACTION (60%) of the board or more.
It is defined once in engine/validator.py and read by the draw guard, the validator's measurements and the prompt.
Before: the guard said "wider than 800 or taller than 600", the validator said "at least 1100 wide and 700 tall", and
the prompt repeated the first one, so wide title bars were rejected as "full-canvas" frames.
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine import validator
from engine.author import WHITEBOARD_SYSTEM_PROMPT, _handle_draw_new_element
from engine.validator import (CANVAS_HEIGHT, CANVAS_WIDTH, FRAME_CANVAS_FRACTION, FRAME_PERCENT, compute_coverage,
                              extract_element_bboxes, is_background_frame, validate_geometry)


def test_the_constant_is_defined_once_and_is_sixty_percent():
    assert FRAME_CANVAS_FRACTION == 0.6 and FRAME_PERCENT == 60


@pytest.mark.parametrize("w,h,frame", [
    (1200, 800, True),        # the whole board
    (1100, 700, True),        # the old validator's frame, 80%
    (1000, 650, True),        # 68%: the old validator let this through
    (960, 601, True),         # just over the limit (60.1%)
    (960, 600, True),         # exactly at the limit: "60 percent or more"
    (960, 599, False),        # just under (59.9%)
    (1080, 400, False),       # wide panel, 45%
    (1100, 300, False),       # 34%
    (1100, 70, False),        # title bar, 8%
    (1190, 20, False),        # thin line-like strip
])
def test_is_background_frame(w, h, frame):
    assert is_background_frame(w, h) is frame


def _draw(fragment, current=None):
    async def emit(*a, **k):
        pass
    calls = []

    async def persist(**k):
        calls.append(k)
    with patch("engine.author.generate_narration_audio", return_value=(1.0, 5, {"is_synthetic": False})):
        r = asyncio.run(_handle_draw_new_element("nb", "pg", "active", "el", fragment, "Words.", current, emit, persist))
    return r, calls


def _g(w, h, x=50, y=50):
    return f'<g id="el"><rect x="{x}" y="{y}" width="{w}" height="{h}" fill="#eee"/><text x="{x + 20}" y="{y + 40}" font-size="18">Title</text></g>'


def test_a_wide_title_bar_is_accepted():
    r, calls = _draw(_g(1100, 70, x=50, y=30))
    assert r["status"] == "ok" and len(calls) == 1


def test_a_wide_panel_that_used_to_be_rejected_is_accepted():
    r, _ = _draw(_g(1080, 400, x=60, y=120))
    assert r["status"] == "ok"


def test_a_full_board_rectangle_over_existing_elements_is_rejected_and_nothing_is_saved():
    existing = '<g id="first"><rect x="100" y="100" width="300" height="120"/><text x="120" y="160">Existing</text></g>'
    r, calls = _draw(_g(1200, 800, x=0, y=0), current=existing)
    assert r["status"] == "error" and "background frame" in r["detail"] and "60%" in r["detail"]
    assert calls == [], "a rejected frame must not be stored"


def test_just_under_and_just_over_the_limit():
    under, _ = _draw(_g(960, 599, x=100, y=100))
    at, calls_at = _draw(_g(960, 600, x=100, y=100))
    over, calls_over = _draw(_g(960, 601, x=100, y=100))
    assert under["status"] == "ok"
    assert at["status"] == "error" and over["status"] == "error" and not calls_at and not calls_over


def test_the_validator_ignores_frames_but_measures_title_bars():
    frame = '<g id="f"><rect x="0" y="0" width="1200" height="800"/></g>'
    bar = '<g id="b"><rect x="50" y="30" width="1100" height="70"/><text x="70" y="70">T</text></g>'
    assert extract_element_bboxes(frame) == []
    assert len(extract_element_bboxes(bar)) == 1
    assert compute_coverage(frame) == 0 and compute_coverage(bar) > 0.05
    assert validate_geometry(frame)["valid"]                       # frames are skipped by the bounds check, as before


def test_the_prompt_states_the_rule_from_the_constant_and_has_no_stale_numbers():
    assert f"{FRAME_PERCENT}%" in WHITEBOARD_SYSTEM_PROMPT
    assert "{FRAME_PERCENT}" not in WHITEBOARD_SYSTEM_PROMPT
    assert "> 800px" not in WHITEBOARD_SYSTEM_PROMPT and "> 600px" not in WHITEBOARD_SYSTEM_PROMPT


def test_no_hard_coded_frame_sizes_are_left_in_the_engine():
    for name in ("validator.py", "author.py"):
        src = (Path(__file__).parent.parent / "engine" / name).read_text(encoding="utf-8")
        assert ">= 1100" not in src and "> 800 or" not in src, f"{name} still has its own frame size"
