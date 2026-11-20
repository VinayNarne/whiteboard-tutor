"""
The "describes content that is not on the board" check, on fixtures: one bad example it must flag, one good example it
must not flag. The plumbing is tested offline with a fake model; the judgement itself is tested with the real cheap
model (skipped when no Azure key is set).
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

import eval_judge as j

TITLE_ONLY = ["Causes of World War I"]
FULL_BOARD = ["Causes of World War I", "Militarism", "Alliances", "Imperialism", "Nationalism",
              "Assassination of Archduke Franz Ferdinand"]
CLAIM = ("reply", "", "I have drawn the five causes: militarism, alliances, imperialism, nationalism and the assassination "
                      "of Archduke Franz Ferdinand.", [])


# ---- offline: plumbing --------------------------------------------------------------------------------------------------

def _topic(per_element_texts, replies=(), narrations=()):
    events = []
    for i, ts in enumerate(per_element_texts):
        frag = f'<g id="e{i}"><rect x="1" y="1" width="9" height="9"/>' + "".join(f'<text x="1" y="2">{t}</text>' for t in ts) + "</g>"
        events.append({"kind": "draw", "element_id": f"e{i}", "svg_fragment": frag, "narration": narrations[i] if i < len(narrations) else ""})
    return {"turns": [{"ok": True, "text": r} for r in replies], "pages": [{"events": events}]}


def test_board_lines_and_statements_come_from_the_saved_run():
    t = _topic([["Title", "a &lt; b"], []], replies=["[[MARK:x]] I drew it."], narrations=["[[MARK:e0]] Narration one.", ""])
    assert j.board_lines(t) == ["Title", "a < b"]
    assert j.statements(t) == [("reply", "", "I drew it.", []), ("narration", "e0", "Narration one.", ["Title", "a < b"])]


def test_the_prompt_has_the_statement_the_elements_own_text_and_the_board_text():
    user = j.build_messages(("narration", "e1", "Here is the formula.", ["f(x)"]), ["Alpha", "Beta"])[1]["content"]
    assert "STATEMENT (narration of e1): Here is the formula." in user
    assert "TEXT ON THIS ELEMENT: f(x)" in user and "- Alpha" in user and "- Beta" in user
    empty = j.build_messages(("reply", "", "x", []), [])[1]["content"]
    assert "TEXT ON THIS ELEMENT: (none)" in empty and "ALL BOARD TEXT:\n(nothing)" in empty
    assert "visual" in j.INSTRUCTIONS and "JSON" in j.INSTRUCTIONS


@pytest.mark.parametrize("raw,expected", [
    ('{"specifics_claimed": [], "missing_from_board": [], "flag": false}', (False, [])),
    ('{"missing_from_board": ["the formula"], "flag": true}', (True, ["the formula"])),
    ('```json\n{"missing_from_board": ["x"], "flag": true}\n```', (True, ["x"])),
    ('{"missing_from_board": [], "flag": true}', (False, [])),            # a flag with nothing missing is not a flag
    ('{"missing_from_board": ["x"], "flag": false}', (False, ["x"])),
])
def test_parse_verdict(raw, expected):
    assert j.parse_verdict(raw) == expected


@pytest.mark.parametrize("raw", ["", "not json", '{"other": 1}', '[1, 2]', '{"flag": "yes", "missing_from_board": 5}'])
def test_an_unreadable_answer_is_an_error_not_a_clean_result(raw):
    with pytest.raises(ValueError):
        j.parse_verdict(raw)


def test_judge_topic_returns_only_flagged_statements():
    stmts = [("reply", "", "fine", []), ("narration", "e1", "claims the formula", [])]
    fake = lambda msgs: json.dumps({"missing_from_board": ["the formula"], "flag": True} if "claims" in msgs[1]["content"]
                                   else {"missing_from_board": [], "flag": False})
    assert j.judge_topic(["b"], stmts, fake) == [{"kind": "narration", "element": "e1", "text": "claims the formula", "missing": ["the formula"]}]
    assert j.judge_topic(["b"], [], lambda m: pytest.fail("no statements, no call")) == []


def test_judge_run_totals():
    topics = {"a": _topic([["Hi"]], replies=["r1"], narrations=["n1"]), "b": _topic([[]], replies=["r2"])}
    fake = lambda msgs: json.dumps({"missing_from_board": ["x"], "flag": True})
    r = j.judge_run(topics, fake)
    assert r["of"] == 3 and r["flagged"] == 3 and r["per_topic"] == {"a": 2, "b": 1}


# ---- the real cheap model on fixtures ------------------------------------------------------------------------------------

live = pytest.mark.skipif(not j.azure_available(), reason="no Azure OpenAI key: the live judge fixtures need the cheap model")


@live
def test_bad_example_is_flagged():
    assert j.judge_statement(CLAIM, TITLE_ONLY) is not None


@live
def test_bad_example_with_an_empty_board_is_flagged():
    claim = ("narration", "osi", "Each layer is labeled with an example protocol: HTTP, TCP, IP and Ethernet.", [])
    assert j.judge_statement(claim, []) is not None


@live
def test_bad_example_narration_of_a_blank_element_is_flagged():
    claim = ("narration", "formula", "Here is the formula: the derivative is the limit of the difference quotient as h approaches zero.", [])
    assert j.judge_statement(claim, ["Understanding Derivatives"]) is not None


@live
def test_good_example_is_not_flagged():
    assert j.judge_statement(CLAIM, FULL_BOARD) is None                   # the same statement, but the words are on the board


@live
def test_good_example_narration_whose_element_carries_the_text_is_not_flagged():
    claim = ("narration", "formula", "Here is the formula: the derivative is the limit of the difference quotient as h approaches zero.",
             ["f'(x) = lim (h->0) [f(x+h) - f(x)] / h"])
    assert j.judge_statement(claim, ["Understanding Derivatives", "f'(x) = lim (h->0) [f(x+h) - f(x)] / h"]) is None


@live
def test_visual_only_claims_are_not_flagged():
    claim = ("reply", "", "The red curve slopes downward and the blue curve slopes upward, crossing in the middle of the board.", [])
    assert j.judge_statement(claim, ["Supply and demand"]) is None


@live
def test_a_reply_that_teaches_without_claiming_anything_is_on_the_board_is_not_flagged():
    claim = ("reply", "", "Photosynthesis happens in the chloroplasts, where light energy is converted into chemical energy.", [])
    assert j.judge_statement(claim, ["Photosynthesis"]) is None
