"""
One model slip is repaired, exactly: `font-size"20"` inside a tag, the equals sign missing (baselines H and J: it cut a handshake drawing to
its first line and a worked example to its title). Nothing else is repaired; each repair is logged. Both ways.
"""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.events import EngineEvent
from engine.grouping import ensure_group
from engine.lossless import compare
from engine.sanitiser import repair_font_size_typo, sanitize_svg

RECT = '<rect x="60" y="120" width="330" height="180" fill="#cce5ff"/>'


# ---- repaired -----------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("raw,fixed", [
    ('<text x="1" y="2" font-size"20" fill="#000">Hi</text>', '<text x="1" y="2" font-size="20" fill="#000">Hi</text>'),
    ('<text font-size"16" x="1">a</text>', '<text font-size="16" x="1">a</text>'),
    ('<text x="1" font-size"13.5">a</text>', '<text x="1" font-size="13.5">a</text>'),
    ('<tspan font-size"18px">a</tspan>', '<tspan font-size="18px">a</tspan>'),
])
def test_font_size_without_its_equals_sign_is_repaired(raw, fixed):
    assert repair_font_size_typo(raw)[0] == fixed


def test_two_of_them_in_one_tag_and_in_many_tags_are_all_repaired_and_counted_one_by_one():
    text, snippets = repair_font_size_typo('<text font-size"16" x="1" font-size"18">a</text><text font-size"20">b</text>')
    assert 'font-size"' not in text and sorted(snippets) == ['font-size"16"', 'font-size"18"', 'font-size"20"']


# ---- not touched --------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("raw", [
    '<text x="1" font-size="20">fine</text>',
    '<text x="1" y="2">use font-size"20" in your CSS</text>',        # the same characters in the text, not in a tag
    '<text x"75" y="1">x</text>',                                    # other attributes with the same slip
    '<text fill"#000" x="1">x</text>',
    '<text x="1" font-size"big">x</text>',                           # not a size
    '<text x="1" font-size = "20">x</text>',
])
def test_everything_else_is_left_exactly_as_it_was(raw):
    assert repair_font_size_typo(raw) == (raw, [])


# ---- the pipeline -------------------------------------------------------------------------------------------------------

def test_a_drawing_with_the_typo_keeps_every_label_and_loses_nothing():
    raw = (RECT + '<text x="75" y="160" font-size"20">Title</text><text x="75" y="190" font-size"16">Second line</text>'
           '<text x="75" y="210" font-size"16">Third line</text><text x="75" y="230" font-size="16">Fourth line</text>')
    stored = sanitize_svg(ensure_group(raw, "el")[0])
    for label in ("Title", "Second line", "Third line", "Fourth line"):
        assert f">{label}</text>" in stored
    assert 'font-size="20"' in stored and not compare(raw, stored).any()


def test_every_repair_is_logged_with_what_was_repaired():
    raw = '<g id="el"><text x="1" y="2" font-size"20">a</text><text x="1" y="9" font-size"16">b</text></g>'
    with patch("engine.sanitiser.logger") as log:
        sanitize_svg(raw)
    calls = [c for c in log.info.call_args_list if c.args[0] == EngineEvent.ATTRIBUTE_REPAIRED]
    assert [c.kwargs["data"]["snippet"] for c in calls] == ['font-size"20"', 'font-size"16"']
    assert all(c.kwargs["data"]["reason"] == "missing_equals" and c.kwargs["data"]["attribute"] == "font-size" for c in calls)


def test_a_clean_drawing_logs_no_repair():
    with patch("engine.sanitiser.logger") as log:
        sanitize_svg('<g id="el"><text x="1" y="2" font-size="20">a</text></g>')
    assert not [c for c in log.info.call_args_list if c.args[0] == EngineEvent.ATTRIBUTE_REPAIRED]


def test_another_missing_equals_is_still_a_reported_loss_not_a_repair():
    raw = RECT + '<text x="75" y="160" font-size="20">Title stays</text><text x="75" y="190" fill"#000">Cut here</text>'
    stored = sanitize_svg(ensure_group(raw, "el")[0])
    assert compare(raw, stored).text_lines == ["Cut here"]
