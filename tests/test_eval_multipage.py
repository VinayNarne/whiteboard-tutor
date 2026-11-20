"""The pure parts of eval M (tests/eval_multipage.py): the judge's verdict mapping, the run-to-run rule and the report on saved runs."""
import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

import eval_multipage as m

REC = {"page1": {"board_text": ["Binary search", "low", "high"], "narrations": ["Here is a sorted array."]},
       "third": {"reply": "Building on the low and high pointers ...", "narrations": [], "board_text": []}}


def _verdict(**fields):
    with patch("eval_judge.call_azure", return_value=json.dumps(fields)):
        return m.judge(REC)["verdict"]


def test_the_judge_verdicts():
    assert _verdict(refers_to_first_page="no", accurate="yes", specific="yes") == "no_reference"
    assert _verdict(refers_to_first_page="yes", accurate="no", specific="yes") == "wrong"
    assert _verdict(refers_to_first_page="yes", accurate="yes", specific="yes") == "correct_and_specific"
    assert _verdict(refers_to_first_page="yes", accurate="unsure", specific="no") == "correct_but_general"


def test_a_judge_failure_is_reported_not_hidden():
    with patch("eval_judge.call_azure", side_effect=RuntimeError("boom")):
        assert m.judge(REC) == {"error": "boom"}


def test_two_ranges_differ_only_when_they_do_not_overlap():
    assert m.outside((0, 0), (3, 3)) and m.outside((1, 2), (3, 4))
    assert not m.outside((1, 3), (3, 4)) and not m.outside((2, 2), (1, 5))


def _saved(folder, label, k, summary_turns, verdicts, secs, cost):
    scen = [{"name": n, "judge": {"verdict": v, "reason": "r"}, "page1": {"board_text": ["x"]}, "third": {"reply": "answer", "narrations": []}} for n, v in zip("abc", verdicts)]
    (folder / f"{label}_run{k}.json").write_text(json.dumps({"label": label, "metrics": {
        "turns_with_prior_page_summary": summary_turns, "third_verdicts": verdicts, "seconds_per_turn": secs, "total_cost_per_turn": cost,
        "forced_page": 0, "iteration_limit_reached": 0, "failed_turns": 0}, "scenarios": scen}), encoding="utf-8")


def test_the_report_applies_the_run_to_run_rule(tmp_path, capsys):
    cs, cg = "correct_and_specific", "correct_but_general"
    _saved(tmp_path, "on15", 1, 3, [cs, cs, cg], 20.0, 0.03)
    _saved(tmp_path, "on15", 2, 3, [cs, cg, cg], 21.0, 0.031)
    _saved(tmp_path, "off15", 1, 0, [cs, cs, cs], 20.5, 0.03)
    _saved(tmp_path, "off15", 2, 0, [cs, cg, cs], 19.5, 0.032)
    m.report(str(tmp_path))
    out = capsys.readouterr().out
    assert "on15 vs off15, turns with a summary in context: OUTSIDE the run-to-run range" in out
    assert "on15 vs off15, correct+specific third answers: inside / overlapping" in out
    assert "on15 vs off15, seconds per turn: inside / overlapping" in out
