"""
What the tutor's instructions may and may not contain (docs/PROMPT_RULES.md).

Principle: constrain how the agent RECORDS its work (ids, coordinates, safety, timing markers), never WHAT it chooses
to draw or say. A rule belongs in the prompt only if it is true for every topic; a copied example gets copied forever.
These tests pin the decision: every recording rule stays, and no content rule or topic example comes back.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.author import TOOLS, WHITEBOARD_SYSTEM_PROMPT as PROMPT
from engine.validator import FRAME_PERCENT

TOOL_TEXT = json.dumps(TOOLS)
EVERYTHING = PROMPT + "\n" + TOOL_TEXT


@pytest.mark.parametrize("needle", [
    '<g id="element_id">',                 # ids: annotations, edits and undo rely on them
    "1200 x 800",                          # bounds
    "absolute x/y",                        # coordinates
    "`transform` attributes",              # no transform (rotation included)
    "[[MARK:element_id]]",                 # timing marker
    "VERY FIRST SENTENCE",
    "NEVER put [[MARK:...]] in your final chat reply",
    "occupied_regions",                    # the state the tutor is given
    "30px",                                # gap around elements
    "TEXT FIT (rendering fact)",           # a measurable fact
    "annotate_element", "remove_annotation", "start_new_page", "get_current_page_state",
    "PROPOSE a new page",                  # page flow decided in the original plan
    "url(#arrow)",                         # markers that exist in the page's defs
    f"{FRAME_PERCENT}% or more of the canvas",
])
def test_recording_rules_are_still_there(needle):
    assert needle in PROMPT, needle


@pytest.mark.parametrize("needle", [
    # the copied example and the topics it came from
    "Here we can see", "Here you can see", "three-way", "SYN packet", "TCP", "tcp_handshake", "cpu_diagram", "CPU",
    # software-flavoured examples and instructions
    "REST", "gRPC", "WebSocket", "pub/sub", "cache", "O(1)", "Bottleneck", "gateway_node", "queue_node", "Api Gateway",
    # forced drawing, forced recipe, persona
    "MANDATORY", "Never reply with plain text alone", "NEVER draw a bare", "meaningless", "elite", "office hours",
    "master professor", "rich, expressive",
    # layout template with meanings, style numbers, creative list
    "LEFT COLUMN", "CENTER COLUMN", "RIGHT COLUMN", "HEADER / TITLE ZONE", "2-ROW", "CARD BREATHING ROOM",
    "stack of plates", "robot", "Venn", "Connected pipeline",
    # narration floor
    "80-200", "80 words", "in-depth", "full, in-depth",
    # old frame numbers
    "800px", "600px",
])
def test_content_rules_and_examples_are_gone(needle):
    assert needle not in EVERYTHING, f"{needle!r} is back in the tutor's instructions"


def test_drawing_is_the_default_but_not_forced():
    assert "default way to explain" in PROMPT
    assert "does not always need a new drawing" in PROMPT


def test_narration_has_a_ceiling_and_no_floor():
    draw = next(t for t in TOOLS if t["function"]["name"] == "draw_new_element")["function"]
    text = draw["parameters"]["properties"]["narration"]["description"]
    assert "At most 200 words" in text
    assert "at least" not in text.lower() and "minimum" not in text.lower()
    assert "[[MARK:element_id]] MUST be the very first thing" in text


def test_no_tool_text_requires_a_recipe_for_what_an_element_contains():
    draw = next(t for t in TOOLS if t["function"]["name"] == "draw_new_element")["function"]
    all_text = json.dumps(draw)
    for needle in ("container", "labeled sub", "flow arrows", "title <text>", "card"):
        assert needle not in all_text, needle


# ---- the element definition (docs/BASELINE.md, baseline E): a recording fact, nothing about what to draw ------------------

def _draw_text():
    draw = next(t for t in TOOLS if t["function"]["name"] == "draw_new_element")["function"]
    return draw["description"], draw["parameters"]["properties"]["svg_fragment"]["description"]


# Experiment G (a stronger system-prompt line) and F (a sentence in the tool text) were removed again: neither was needed. Both sentences must
# stay out, the prompt and the tool text are the E wording, and from here on they are frozen (docs/BASELINE.md).
REMOVED_SENTENCES = [
    "Saved pages are opened without audio",           # F and G both start like this
    "must be understandable from what is drawn on it alone",
    "Narration adds to what is drawn",
    "the board itself must carry each concept",
]
E_LINE = "- Whatever the learner needs to identify should be identifiable on the board."


def test_the_f_and_g_sentences_are_gone_and_the_e_line_is_back_as_the_third_bullet_of_harness_rule_1():
    for sentence in REMOVED_SENTENCES:
        assert sentence not in EVERYTHING, sentence
    rule1 = PROMPT.split("HARNESS RULE 1: ELEMENTS")[1].split("HARNESS RULE 2")[0]
    assert [b for b in rule1.splitlines() if b.startswith("- ")][2] == E_LINE


def test_the_tool_text_is_the_e_wording():
    desc, frag = _draw_text()
    assert desc == ("Adds one named element to the whiteboard. An element is one <g id='element_id'> group, and the group may contain "
                    "any number of shapes and text. The narration is tied to the element through its id, so whatever the narration "
                    "refers to must be inside the same group.")
    assert frag == ("One <g id='...'> group containing everything this element consists of, any number of shapes and text. "
                    "Must use absolute x/y coordinates. No transform attributes (rotation included). Fits within 1200x800 canvas.")


# FROZEN: the system prompt and the tool text are not tuned any more. Changing either is the owner's decision; if you must, update these
# two digests in the same commit and say why in docs/BASELINE.md.
FROZEN_PROMPT_SHA256 = "c4244d24d66e7304a06a4e2de9726fae08a8c377b71863bcf420b819f548a510"
FROZEN_TOOLS_SHA256 = "1a343e3cef706a3ae9a78c895cb175df670d84cac9b598c38aee92b198e12994"


def test_the_system_prompt_and_the_tool_text_are_frozen():
    import hashlib
    assert hashlib.sha256(PROMPT.encode("utf-8")).hexdigest() == FROZEN_PROMPT_SHA256, "the system prompt changed: it is frozen"
    assert hashlib.sha256(json.dumps(TOOLS, sort_keys=True).encode("utf-8")).hexdigest() == FROZEN_TOOLS_SHA256, "the tool text changed: it is frozen"


def test_an_element_is_defined_as_one_named_group_that_may_hold_any_shapes_and_text():
    desc, frag = _draw_text()
    assert "An element is one <g id='element_id'> group" in desc
    assert "any number of shapes and text" in desc and "any number of shapes and text" in frag


def test_the_narration_is_tied_to_the_element_through_its_id():
    desc, _ = _draw_text()
    assert "tied to the element through its id" in desc
    assert "whatever the narration refers to must be inside the same group" in desc


@pytest.mark.parametrize("needle", ["e.g.", "for example", "such as", "must include", "must contain", "at least", "minimum",
                                    "label", "title", "caption", "legend", "layout", "arrow", "diagram"])
def test_the_element_definition_gives_no_example_and_requires_nothing_about_content(needle):
    desc, frag = _draw_text()
    assert needle not in desc.lower() and needle not in frag.lower(), needle


def test_the_recording_facts_next_to_the_definition_are_unchanged():
    _, frag = _draw_text()
    for fact in ("absolute x/y coordinates", "No transform attributes (rotation included)", "Fits within 1200x800 canvas"):
        assert fact in frag
