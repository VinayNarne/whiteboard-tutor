"""
Each eval check, on fixtures, both ways: one bad example it must flag and one good example it must not flag.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from eval_checks import (elements_without_text, median_text_lines, mentions_rejection, narration_stats, opener,
                         retries_by_topic, retries_per_turn, run_checks, text_lines, top_opener_share)

WITH_TEXT = '<g id="a"><rect x="1" y="1" width="200" height="90"/><text x="5" y="9">Label</text></g>'
TWO_LINES = '<g id="b"><rect x="1" y="1" width="200" height="90"/><text x="5" y="9">One</text><text x="5" y="30">Two</text></g>'
NO_TEXT = '<g id="c"><rect x="1" y="1" width="200" height="90"/></g>'
EMPTY_TEXT = '<g id="d"><rect x="1" y="1" width="200" height="90"/><text x="5" y="9">   </text></g>'
TSPANS = '<g id="e"><text x="5" y="9"><tspan>A</tspan><tspan>B</tspan></text></g>'


# ---- elements with no text, median text lines -----------------------------------------------------------------------

def test_text_lines():
    assert text_lines(WITH_TEXT) == 1 and text_lines(TWO_LINES) == 2 and text_lines(TSPANS) == 1
    assert text_lines(NO_TEXT) == 0 and text_lines(EMPTY_TEXT) == 0          # blank text is not text


def test_elements_without_text_flags_the_bad_and_not_the_good():
    assert elements_without_text([NO_TEXT]) == (1, 1, 100)                   # bad example: flagged
    assert elements_without_text([WITH_TEXT, TWO_LINES]) == (0, 2, 0)        # good examples: not flagged
    assert elements_without_text([WITH_TEXT, NO_TEXT, EMPTY_TEXT, TWO_LINES]) == (2, 4, 50)
    assert elements_without_text([]) == (0, 0, 0)


def test_median_text_lines():
    assert median_text_lines([WITH_TEXT, TWO_LINES, NO_TEXT]) == 1
    assert median_text_lines([TWO_LINES, TWO_LINES, WITH_TEXT]) == 2
    assert median_text_lines([NO_TEXT, NO_TEXT, WITH_TEXT]) == 0
    assert median_text_lines([]) == 0


# ---- mentions a rejection --------------------------------------------------------------------------------------------

BAD = [
    "I see the system still rejects the detailed process card because it expects text inside a diagram card.",
    "I see that my previous attempts to draw the boxes with text failed due to technical issues with the SVG formatting.",
    "The validator rejected my first drawing.",
    "That layout is not allowed by the whiteboard tool.",
    "The card expects text, so I will add labels.",
    "The system rejected the element, so I split it.",
    "My first attempt failed, so here is a simpler version.",
    "The sanitiser removed part of the label.",
]

GOOD = [
    # "system" in ordinary science and everyday explanations
    "The circulatory system carries blood to every organ in the body.",
    "In a closed system, energy is conserved, and the system exchanges no matter with its surroundings.",
    "The solar system formed about 4.6 billion years ago.",
    "The nervous system sends signals along neurons.",
    "A system of two equations can have one solution, none, or infinitely many.",
    "The operating system schedules which program runs next.",
    # other words from the flagged list, used normally
    "The null hypothesis is rejected when the p-value is below 0.05.",
    "Heat transfer is not allowed across an adiabatic wall.",
    "Economists expect prices to rise when demand rises.",
    "A diagram of the water cycle shows evaporation, condensation and rain.",
    "This drawing shows how the tangent touches the curve at one point.",
    "Here is a card that lists the three causes.",
    "The first attempt at a proof used induction, and it worked.",
]


@pytest.mark.parametrize("sentence", BAD)
def test_mentions_rejection_flags_talk_about_the_system(sentence):
    assert mentions_rejection(sentence) == [sentence]


@pytest.mark.parametrize("sentence", GOOD)
def test_mentions_rejection_leaves_normal_explanations_alone(sentence):
    assert mentions_rejection(sentence) == []


def test_mentions_rejection_returns_only_the_matching_sentences_and_ignores_marker_tokens():
    text = ("[[MARK:x]] Here is the water cycle. The circulatory system is a different example. "
            "I see the system still rejects the card because it expects text. Now let us continue.")
    assert mentions_rejection(text) == ["I see the system still rejects the card because it expects text."]


# ---- narration length and repeated openings ----------------------------------------------------------------------------

def test_narration_stats():
    s = narration_stats(["one two three", "[[MARK:a]] four five six seven", ""], turns=2)
    assert s == {"count": 2, "median_words": 3.5, "total_words_per_turn": 4}
    assert narration_stats([], 4) == {"count": 0, "median_words": 0, "total_words_per_turn": 0}


def test_same_first_two_words_flags_a_template_and_not_variety():
    template = ["Here is the cause of the war.", "Here is how plants make food.", "Here is a stack.", "Here is the demand curve.",
                "A derivative measures change."]
    s = top_opener_share(template)
    assert (s["opener"], s["count"], s["total"], s["percent"]) == ("here is", 4, 5, 80)       # bad: flagged
    varied = ["Newton described three laws.", "Plants take in carbon dioxide.", "A stack is last in, first out.",
              "Demand rises when price falls.", "The derivative measures change."]
    assert top_opener_share(varied)["percent"] == 20                                          # good: no repeated opening
    assert top_opener_share([])["percent"] == 0
    assert opener("[[MARK:x]] Here, we see.") == "here we"


# ---- retries ---------------------------------------------------------------------------------------------------------------

def test_retries_per_turn():
    assert retries_per_turn(8, 16) == 0.5 and retries_per_turn(0, 16) == 0.0 and retries_per_turn(5, 0) == 0.0


def test_retries_by_topic_from_the_log_only_counts_the_window_and_known_topics():
    prompts = {"Explain supply and demand": "economics", "Explain how binary search works": "code"}
    rows = [
        {"ts": "2026-10-07T18:00:00.1Z", "event": "notebook_created", "message": "Notebook created: nb1", "data": {"topic": "Explain supply and demand"}},
        {"ts": "2026-10-07T18:00:01.1Z", "event": "notebook_created", "message": "Notebook created: nb2", "data": {"topic": "Explain how binary search works"}},
        {"ts": "2026-10-07T18:00:01.1Z", "event": "notebook_created", "message": "Notebook created: nb3", "data": {"topic": "Something else"}},
        {"ts": "2026-10-07T18:01:00.1Z", "event": "draw_failed", "session_id": "nb1"},
        {"ts": "2026-10-07T18:01:01.1Z", "event": "draw_failed", "session_id": "nb1"},
        {"ts": "2026-10-07T18:01:02.1Z", "event": "draw_failed", "session_id": "nb2"},
        {"ts": "2026-10-07T18:01:03.1Z", "event": "draw_failed", "session_id": "nb3"},      # unknown topic: skipped
        {"ts": "2026-10-07T19:30:00.1Z", "event": "draw_failed", "session_id": "nb1"},      # outside the window
    ]
    assert retries_by_topic(rows, "2026-10-07T18:00:00", "2026-10-07T19:00:00", prompts) == {"economics": 2, "code": 1}


# ---- all together ----------------------------------------------------------------------------------------------------------------

def test_run_checks_on_a_good_run_and_a_bad_run():
    def topic(frags, reply, narr):
        return {"turns": [{"ok": True, "text": reply}, {"ok": True, "text": reply}],
                "pages": [{"events": [{"kind": "draw", "svg_fragment": f, "narration": narr} for f in frags]}]}
    good = {"history": topic([WITH_TEXT, TWO_LINES], "Causes included alliances.", "Alliances tied the great powers together.")}
    bad = {"history": topic([NO_TEXT, NO_TEXT], "I see the system still rejects the card.", "Here is a box.")}
    g = run_checks(good, turns=2, retries_total=0)
    b = run_checks(bad, turns=2, retries_total=6, retries_by_domain={"history": 6})
    assert g["elements_without_text"]["count"] == 0 and g["mentions_rejection"]["count"] == 0
    assert b["elements_without_text"]["percent"] == 100 and b["mentions_rejection"]["count"] == 2
    assert b["retries_per_turn"] == {"total": 3.0, "per_topic": {"history": 3.0}}
    assert b["median_text_lines_per_element"] == 0 and g["median_text_lines_per_element"] == 1.5


# ---- narrations with no valid marker, as produced ----------------------------------------------------------------------

def _marker_topic(*pairs):
    return {"t": {"turns": [], "pages": [{"events": [{"kind": "draw", "element_id": eid, "narration": n, "svg_fragment": ""} for eid, n in pairs]}]}}


def test_narrations_without_a_valid_marker_flags_the_bad_and_not_the_good():
    from eval_checks import narrations_without_valid_marker as nm
    good = _marker_topic(("a", "[[MARK:a]] Hello there."), ("b", "Some words [[MARK:b]] and more."))
    assert nm(good) == (0, 2, 0)                                             # good examples: not flagged
    for bad in ("Hello there.", "[MARK:a] Hello there.", "[[mark:a]] Hello there.", "[[MARK:other]] Hello there.", "[[ MARK : a ]] Hello"):
        assert nm(_marker_topic(("a", bad)))[0] == 1, bad                    # bad examples: each flagged
    assert nm(_marker_topic(("a", "[[MARK:a]] ok"), ("b", "no marker"))) == (1, 2, 50)
    assert nm(_marker_topic(("a", ""))) == (0, 0, 0)                          # a silent element has no narration to check
