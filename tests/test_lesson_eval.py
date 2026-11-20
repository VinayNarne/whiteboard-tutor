"""The lesson check's automatic checks (scripts/lesson_eval.py) on hand-written replies, and its lesson set."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("lesson_eval", ROOT / "scripts" / "lesson_eval.py")
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)
WRONG = [{"tool": "record_step", "element_id": "1", "event": "answered_wrong", "status": "ok"}]


def test_each_check_fires_on_the_behaviour_it_names_and_not_otherwise():
    good = "Not quite: blue isn't the strongest light. Why would short waves scatter more?"
    assert ev.check_turn("wrong", good, WRONG, "What colour scatters most?", 200, True) == []
    assert ev.check_turn("wrong", "Great thinking! Why?", [], "", 200, True) == ["praised_wrong", "wrong_not_recorded", "wrong_not_corrected"]
    assert ev.check_turn("vague", "Close. What does the air do?", [], "", 200, False) == []          # no plan yet: nothing to record
    assert ev.check_turn("ok", "Exactly! Why?", WRONG, "", 200, True) == ["praised_skip", "skip_graded"]
    assert ev.check_turn("continue", "Light scatters off air.", [], "", 200, True) == ["no_question"]
    assert ev.check_turn("right", "Shorter waves scatter. What about violet?", [], "Shorter waves scatter. What about violet light?", 200, True) == ["repeated_question"]
    assert ev.check_turn("right", "Use $x^2$ here. Why?", [], "", 200, True) == ["markup_in_chat"]
    assert ev.check_turn("right", "It costs $5 and $10. Why?", [], "", 200, True) == []               # money is not markup
    assert ev.check_turn("ok", "", [], "", 503, True) == ["turn_failed"]


def test_the_lesson_set_is_complete():
    data = json.loads((ROOT / "tests" / "lesson_eval" / "lessons.json").read_text(encoding="utf-8"))
    kinds = set(data["script"]) - {"question", "ok", "continue"}
    assert len(data["lessons"]) == 10 and len({l["id"] for l in data["lessons"]}) == 10
    assert all(set(l) >= kinds | {"id", "question"} for l in data["lessons"])


def test_the_report_counts_failures():
    results = [{"id": "sky", "turns": [{"kind": "question", "seconds": 7.0, "fails": [], "blocks": ["write_notes"], "refused": [], "judge": ""},
                                       {"kind": "ok", "seconds": 5.0, "fails": ["praised_skip"], "blocks": [], "refused": ["draw_scene"], "judge": ""}],
                "path": [{"level": "taught"}], "final": {}}]
    md = ev.report(results, "unit", False)
    assert "| praised_skip | 1 |" in md and "refused attempts: 1" in md and "| sky | praised_skip x1 | taught | 1 |" in md
