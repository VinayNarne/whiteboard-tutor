"""
engine/recap.py
The clean lesson recap of one page, built only from stored records (no database, no model): the plan's goal, the checklist with the levels
earned, what is on the board as plain text, the learner's answers with how they went, and the beliefs the grader found. Pure functions so the
frontend contract is tested with hand-built inputs.
"""
import re

from engine.author import is_skip, last_question
from engine.markers import strip_markers

_KINDS = {"draw_scene": "diagram", "draw_graph": "graph", "draw_table": "table", "draw_bar_chart": "chart", "draw_venn": "venn"}
_TUTOR_RESULT = {"answered_right": "right", "answered_wrong": "wrong"}
MAX_NOTE_LINES, MAX_NODES = 8, 6


def plain(text) -> str:
    """Display markup out: **bold**, ==highlight==, $formula$ keep their inner text; [[MARK:...]] goes."""
    t = strip_markers(str(text or ""))
    t = re.sub(r"\*\*(.+?)\*\*|==(.+?)==|\$(.+?)\$", lambda m: m.group(1) or m.group(2) or m.group(3), t)
    return t.strip()


def _board_item(block: dict):
    tool, args = block.get("tool"), block.get("args") or {}
    title = plain(args.get("title") or args.get("heading")) or None
    if tool == "write_notes":
        style = args.get("style") if args.get("style") in ("recap", "code") else "notes"
        if style == "code":
            return {"kind": "code", "title": title or "Code example", "lines": []}      # code is not text to read back
        lines = [plain(l.get("text")) for l in args.get("lines") or [] if isinstance(l, dict)]
        return {"kind": style, "title": title, "lines": [l for l in lines if l][: None if style == "recap" else MAX_NOTE_LINES]}
    if tool in _KINDS:
        labels = [plain(n.get("label")) for n in args.get("nodes") or [] if isinstance(n, dict)] if tool == "draw_scene" else []
        return {"kind": _KINDS[tool], "title": title, "lines": [l for l in labels if l][:MAX_NODES]}
    return None


def _tutor_record(turns, i):
    """(event, step) of the answer record the tutor made in its reply to learner turn i, or (None, None)."""
    for t in turns[i + 1:]:
        if t.role == "user" and t.status == "ok":
            break                                      # the next learner turn: the reply is over
        if t.role == "assistant" and t.status in ("ok", "silent"):
            for r in reversed(t.tool_calls_made or []):
                if isinstance(r, dict) and r.get("tool") == "record_step" and r.get("status") == "ok" and r.get("event") in _TUTOR_RESULT:
                    step = str(r.get("element_id") or "")
                    return r["event"], int(step) if step.isdigit() else None
    return None, None


def build_recap(plan, page_title, lesson_path, blocks, turns) -> dict:
    """turns: this page's chat turns (objects with role, content, status, tool_calls_made, grade, belief), oldest first."""
    goal = next((l.split(":", 1)[1].strip() for l in (plan or "").splitlines() if l.startswith("GOAL:")), "") or None
    board = [b for b in (_board_item(x) for x in sorted(blocks, key=lambda b: b.get("n", 0))) if b]
    answers, steps, history = [], [], []              # steps[k]: the step answers[k] was about (None unknown), for "cleared"
    for i, t in enumerate(turns):
        if t.status not in ("ok", "silent") or (t.role == "user" and t.status != "ok"):
            continue
        if t.role == "assistant":
            if t.status == "ok" and t.content:
                history.append({"role": "assistant", "content": t.content})
            continue
        if t.role != "user" or is_skip(t.content):
            continue
        event, step = _tutor_record(turns, i)
        grade = getattr(t, "grade", None)
        if grade or event:
            answers.append({"question": last_question(history) or None, "answer": t.content, "result": grade or _TUTOR_RESULT[event],
                            "source": "grader" if grade else "tutor", "belief": getattr(t, "belief", None)})
            steps.append(step)
    # A belief is cleared by a LATER right answer on the same step; when either step is unknown, by any later right answer.
    corrected = [{"belief": a["belief"], "cleared": any(b["result"] == "right" and (steps[k] is None or steps[j] is None or steps[k] == steps[j])
                                                          for k, b in enumerate(answers) if k > j)}
                 for j, a in enumerate(answers) if a["belief"]]
    return {"title": page_title or "", "goal": goal,
            "steps": [{"title": s["title"], "level": s.get("level") or "not started"} for s in lesson_path or []],
            "board": board, "answers": [{k: v for k, v in a.items() if k != "belief"} for a in answers], "corrected": corrected}
