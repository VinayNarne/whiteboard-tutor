"""
tests/eval_judge.py
Eval check: replies and narrations that describe content which is NOT on the board.

A cheap model call (the Azure deployment already used by the tutor) gets ONE statement at a time (a chat reply, or the
narration spoken while an element was drawn), the text written on that element, and all the text written on the board
in the lesson. It flags the statement if it presents specific written content (names, labels, formulas, numbers, steps,
example sentences) as being on the board when that content is not in the board text. Purely visual claims (shapes,
colours, arrows, curves, graphs, positions) are not flagged: the judge sees text, not shapes.

Calibration against the Opus reviewer (docs/baseline_D reviews: 36 / 37 / 28 = 101 statements): this judge flags
26 / 41 / 34 = 101 on the same three runs, so the total agrees and single runs differ by up to 10. On the well-labelled
runs it still flags 5-13 per run (A: 10 / 13 / 12, B: 8 / 12 / 5) and on C 27 / 28 / 30. So it separates D and C from A and B,
but it is a regression signal, not an exact count. Two earlier versions were dropped: one call per topic (4 / 9 / 4, far
too lenient) and a per-statement version that also flagged plain teaching replies (fixture failure).

A narration is treated as presenting the content of its element; a chat reply counts only if it says something was
drawn, added or shown.

The model call is injected (`call_model`), so the logic is tested offline with a fake model and, separately, on fixtures
with the real cheap model (tests/test_eval_judge.py, skipped when no Azure key is set).
"""
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
from eval_checks import clean  # noqa: E402

INSTRUCTIONS = """You check a tutor's spoken statement against what is written on its whiteboard. You see text only, not shapes.

You get: the STATEMENT (a chat reply, or a narration spoken while one element is drawn), the TEXT ON THIS ELEMENT (empty if it has none), and ALL BOARD TEXT of the lesson.

Work in this order.
1. Does the statement present specific WRITTEN content as being on the board? "Specific written content" means names, labels, terms, formulas, numbers, steps, protocol or layer names, or example sentences.
   - A NARRATION accompanies the drawing of its element, so it presents what it tells about that element as the content of that element ("here is the formula ...", "this card explains X", "the layers are A, B, C").
   - A chat REPLY counts only if it says or implies that something was drawn, added, written, labelled or shown ("I have drawn ...", "the diagram shows ...", "I added labels for ..."). A reply that only teaches or explains does not.
2. If yes: is that specific content missing from ALL BOARD TEXT (and from TEXT ON THIS ELEMENT)? A paraphrase of text that is there is fine.
3. Never count purely visual claims: shapes, colours, arrows, curves, circles, lines, graphs, pictures, objects, positions, or anything that would be drawn as a picture rather than written, such as "the demand curve", "the axes", "the arrow from the leaf to the stem", "a box on the left", even if its name is not written.

Answer JSON only: {"presents_written_content_as_on_board": true|false, "specifics_claimed": ["..."], "missing_from_board": ["..."], "flag": true|false}. flag is true only if step 1 is yes and missing_from_board is not empty."""


def element_lines(fragment):
    """Non-empty text lines written in one drawn fragment, unescaped."""
    try:
        root = ET.fromstring(fragment)
    except ET.ParseError:
        return []
    out = []
    for el in root.iter():
        if el.tag.split("}")[-1] == "text":
            t = " ".join("".join(el.itertext()).split())
            if t:
                out.append(t)
    return out


def board_lines(topic):
    """Every text line written on the board in a topic (all pages)."""
    return [t for pg in topic["pages"] for e in pg["events"] if e["kind"] == "draw" for t in element_lines(e["svg_fragment"])]


def statements(topic):
    """[(kind, element_id, text, text_lines_on_that_element)] in the order they were said."""
    out = [("reply", "", clean(t["text"]), []) for t in topic["turns"] if t.get("ok") and clean(t["text"])]
    for pg in topic["pages"]:
        for e in pg["events"]:
            if e["kind"] == "draw" and clean(e.get("narration")):
                out.append(("narration", e["element_id"], clean(e["narration"]), element_lines(e["svg_fragment"])))
    return out


def build_messages(stmt, board):
    kind, eid, text, own = stmt
    board_text = "\n".join(f"- {b}" for b in board) if board else "(nothing)"
    user = (f"STATEMENT ({kind}{' of ' + eid if eid else ''}): {text}\n\n"
            f"TEXT ON THIS ELEMENT: {'; '.join(own) if own else '(none)'}\n\nALL BOARD TEXT:\n{board_text}")
    return [{"role": "system", "content": INSTRUCTIONS}, {"role": "user", "content": user}]


def parse_verdict(raw):
    """(flag, [missing items]) from the model's answer; raises ValueError if it is not the expected JSON."""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", (raw or "").strip())
    try:
        data = json.loads(text)
        missing = [str(m) for m in (data.get("missing_from_board") or [])]
        return (bool(data["flag"]) and bool(missing)), missing
    except (ValueError, KeyError, TypeError, AttributeError) as e:
        raise ValueError(f"judge answer is not the expected JSON: {raw!r}") from e


def call_azure(messages):
    """The cheap model: the Azure deployment the tutor uses, temperature 0, JSON answer."""
    from engine.author import AZURE_OPENAI_DEPLOYMENT, get_azure_client
    resp = get_azure_client().chat.completions.create(
        model=AZURE_OPENAI_DEPLOYMENT, messages=messages, temperature=0, max_tokens=600,
        response_format={"type": "json_object"})
    return resp.choices[0].message.content


def azure_available():
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
    return bool(os.getenv("AZURE_OPENAI_API_KEY") and os.getenv("AZURE_OPENAI_ENDPOINT"))


def judge_statement(stmt, board, call_model=call_azure):
    """None if the statement is fine, else {'kind', 'element', 'text', 'missing'}."""
    flag, missing = parse_verdict(call_model(build_messages(stmt, board)))
    kind, eid, text, _ = stmt
    return {"kind": kind, "element": eid, "text": text, "missing": missing} if flag else None


def judge_topic(board, stmts, call_model=call_azure, workers=8):
    """The flagged statements of one topic."""
    if not stmts:
        return []
    with ThreadPoolExecutor(workers) as pool:
        results = list(pool.map(lambda s: judge_statement(s, board, call_model), stmts))
    return [r for r in results if r]


def judge_run(topics, call_model=call_azure):
    """{'flagged': n, 'of': statements, 'per_topic': {domain: n}, 'items': [...]} for one saved run."""
    items, per_topic, total = [], {}, 0
    for domain, topic in topics.items():
        stmts = statements(topic)
        total += len(stmts)
        hits = judge_topic(board_lines(topic), stmts, call_model)
        per_topic[domain] = len(hits)
        items += [{"topic": domain, **h} for h in hits]
    return {"flagged": len(items), "of": total, "per_topic": per_topic, "items": items}
