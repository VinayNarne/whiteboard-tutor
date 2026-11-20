"""
Layout and overlap measured on every shape and text label, wherever it sits (tests/eval_layout.py), because the guards' own
extraction reads only <g id> groups and shapes with an id and so cannot see bare tags (docs/BASELINE.md).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.validator import extract_element_bboxes
import eval_layout as L

BARE_RECT = '<rect x="60" y="120" width="330" height="180" fill="#cce5ff"/>'
BARE_TEXT = '<text x="100" y="50" font-size="20">Hello world</text>'
GROUP = '<g id="g1"><rect x="500" y="100" width="200" height="100"/><text x="520" y="150" font-size="20">Card</text></g>'


def test_the_guards_extraction_cannot_see_a_bare_rect_but_the_layout_measure_can():
    assert extract_element_bboxes(BARE_RECT) == []
    assert L.shape_boxes(BARE_RECT) == [(60.0, 120.0, 390.0, 300.0)]


def test_a_bare_text_a_group_and_several_sibling_tags_are_all_measured():
    assert L.element_box(BARE_TEXT) == (100.0, 32.4, 210.0, 54.4)
    assert L.element_box(GROUP) == (500.0, 100.0, 700.0, 200.0)
    assert L.element_box(BARE_RECT + BARE_TEXT) == (60.0, 32.4, 390.0, 300.0)


def test_defs_and_a_background_frame_are_not_geometry():
    assert L.shape_boxes('<defs><style>x</style></defs><rect x="0" y="0" width="1200" height="800"/>') == []


def test_two_boards_on_the_same_cells_are_one_layout_and_different_cells_are_two():
    same = {"a": [BARE_RECT], "b": [BARE_RECT]}
    assert L.layout_clusters(same)[0] == 1
    other = {"a": [BARE_RECT], "b": ['<rect x="800" y="500" width="300" height="200"/>']}
    assert L.layout_clusters(other)[0] == 2


def test_overlap_pairs_follow_the_guards_rule_over_all_elements_and_ignore_thin_ones():
    inside = '<text x="100" y="150" font-size="20">Law</text>'                 # a label lying on the bare rect
    assert L.overlap_pairs([BARE_RECT, inside]) == 1
    assert L.overlap_pairs([BARE_RECT, GROUP]) == 0                           # far apart
    assert L.overlap_pairs([BARE_RECT, '<line x1="60" y1="150" x2="390" y2="150"/>']) == 0   # thin connector, ignored
    cross = '<rect x="200" y="200" width="300" height="200"/>'                 # covers about a third of the smaller box
    assert L.overlap_pairs([BARE_RECT, cross]) == 1
    nudge = '<rect x="300" y="200" width="300" height="200"/>'                 # covers about 15%: under the guard's 20%
    assert L.overlap_pairs([BARE_RECT, nudge]) == 0


def test_board_layout_reads_a_stored_run_topics_dict():
    topics = {"t": {"pages": [{"events": [{"kind": "draw", "svg_fragment": BARE_RECT},
                                         {"kind": "draw", "svg_fragment": '<text x="100" y="150" font-size="20">Law</text>'}]}]}}
    assert L.board_layout(topics) == (1, None, 1)
