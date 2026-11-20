"""
The lossless check: what the model wrote against what is stored (engine/lossless.py). Both ways: a drawing that loses something
is flagged, with what was lost, and a clean drawing passes, whatever repair it needed on the way.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.fonts import inject_trusted_font
from engine.grouping import ensure_group
from engine.lossless import compare
from engine.sanitiser import sanitize_svg

CARD = ('<rect x="60" y="120" width="330" height="180" fill="#cce5ff"/>'
        '<text x="75" y="160" font-size="20">Law 1: First Law</text>'
        '<text x="75" y="190" font-size="16">An object at rest stays at rest</text>'
        '<line x1="75" y1="200" x2="300" y2="200" stroke="#000"/>')
MALFORMED = ('<rect x="60" y="120" width="330" height="180" fill="#cce5ff"/>'
             '<text x="75" y="160" font-size="20">Title stays</text>'
             '<text x="75" y="190" font-size="16" fill"#000">Second line is cut</text>'
             '<text x="75" y="210" font-size="16">Third line is cut too</text>')


def _stored(raw, element_id="el", font=False):
    """What the real pipeline keeps of `raw` (repair, then sanitiser, then optionally the page font)."""
    sanitized = sanitize_svg(ensure_group(raw, element_id)[0])
    return inject_trusted_font(sanitized) if font else sanitized


# ---- a clean drawing passes ----------------------------------------------------------------------------------------------------

def test_a_clean_drawing_of_four_sibling_tags_loses_nothing():
    loss = compare(CARD, _stored(CARD))
    assert not loss.lost() and not loss.any() and loss.as_dict() == {"tags": {}, "text_lines": 0, "chars": 0, "control": 0, "formatting": {}}


def test_the_font_the_page_adds_and_the_group_wrapper_are_not_losses():
    assert not compare(CARD, _stored(CARD, font=True)).lost()
    assert not compare('<g id="el">' + CARD + "</g>", _stored('<g id="el">' + CARD + "</g>", font=True)).lost()


def test_entities_line_breaks_and_stray_symbols_the_repair_keeps_are_not_losses():
    raw = '<rect x="1" y="1" width="100" height="50"/><text x="5" y="30">low <= high &amp; a &rarr; b<br/>next line</text>'
    assert not compare(raw, _stored(raw)).lost()


# ---- a drawing that loses something is flagged, and says what ----------------------------------------------------------------------

def test_four_sibling_tags_with_a_malformed_attribute_are_flagged_with_what_was_lost():
    stored = _stored(MALFORMED)
    assert "Title stays</text>" in stored and "Third line" not in stored            # the recovery parser cut the drawing at the bad tag
    loss = compare(MALFORMED, stored)
    assert loss.lost()
    assert loss.text_lines == ["Second line is cut", "Third line is cut too"]       # the second survives only as stray text, not as a label
    assert loss.tags["text"] >= 1 and loss.chars == len("Secondlineiscut") + len("Thirdlineiscuttoo")


def test_the_old_sanitiser_bug_is_caught_sibling_tags_sent_straight_to_the_sanitiser():
    loss = compare(CARD, sanitize_svg(CARD))                      # without the group repair only the first tag survives
    assert loss.tags == {"text": 2, "line": 1} and loss.text_lines == ["Law 1: First Law", "An object at rest stays at rest"]


def test_tags_the_allowlist_removes_are_reported_by_name():
    raw = ('<g id="el"><rect x="1" y="1" width="100" height="50"/><script>alert(1)</script>'
           '<foreignObject><div>hi</div></foreignObject><text x="5" y="30">kept</text></g>')
    loss = compare(raw, _stored(raw))
    assert loss.tags["script"] == 1 and loss.tags["foreignobject"] == 1 and loss.text_lines == []


def test_a_text_label_that_comes_back_shorter_is_a_loss_of_that_line():
    loss = compare('<text x="1" y="1">The whole sentence</text>', '<g id="el"><text x="1" y="1">The whole</text></g>')
    assert loss.text_lines == ["The whole sentence"] and loss.chars == len("sentence")


def test_formatting_tags_removed_on_purpose_with_their_text_kept_are_counted_apart_and_are_not_a_loss():
    raw = '<rect x="1" y="1" width="100" height="50"/><text x="5" y="30">a <b>bold</b> word<br/>next</text>'
    loss = compare(raw, _stored(raw))
    assert not loss.lost() and loss.formatting == {"b": 1, "br": 1}


def test_an_empty_or_missing_drawing_has_no_loss():
    assert not compare("", "").any() and not compare(CARD, CARD).any()
