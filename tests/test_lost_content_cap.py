"""
The lost-content note is told at most twice per element per turn; the iteration limit has its own event.

The note asks the tutor to redraw an element whose text did not fully reach the board (a control character where a symbol should be, a dropped label). When the
model cannot write the character, the note started a loop: L2 run 1 redrew one maths element 19 times (70 model calls, an 80 s turn, the canned "I've drawn quite
a bit" reply, the placeholder still on the board). Now: the first two notes for an element in a turn are told, after that the tutor hears nothing more, the
placeholder stays on the board and `lost_content_cap_reached` (element, count) is logged. A normal repairable element still gets its note and can be fixed. The turn
that uses all 20 model calls logs `iteration_limit_reached` (the eval counts it as a failure); the product keeps the canned reply and offers no Retry.
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlmodel import Session, select

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.models import ChatTurn, Page
from core.events import EngineEvent

NUL = chr(0)
PLACEHOLDER = "�"


def _fake_tts(narration, audio_path, alignment_path, element_id=None):
    Path(audio_path).parent.mkdir(parents=True, exist_ok=True)
    Path(audio_path).write_bytes(b"mp3")
    Path(alignment_path).write_text("{}", encoding="utf-8")
    return 1.0, 5, {"is_synthetic": False}


def _tc(i, name, args):
    return SimpleNamespace(id=f"c{i}", function=SimpleNamespace(name=name, arguments=json.dumps(args)))


def model(rounds, final="Done."):
    """A fake model; also keeps the tool results it was sent, in order, so a test can see which results carried the lost-content note."""
    out = [SimpleNamespace(choices=[SimpleNamespace(finish_reason="tool_calls", message=SimpleNamespace(
        content=None, tool_calls=[_tc(i, n, a) for i, (n, a) in enumerate(r)]))], usage=None, model="fake") for r in rounds]
    out.append(SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=final, tool_calls=None))], usage=None, model="fake"))
    it, seen = iter(out), {"tool_results": []}

    def create(**kw):
        seen["tool_results"] = [json.loads(m["content"]) for m in kw["messages"] if isinstance(m, dict) and m.get("role") == "tool"]
        return next(it)
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))), seen


def card(eid, text, x=60, y=100):
    return f'<g id="{eid}"><rect x="{x}" y="{y}" width="400" height="120"/><text x="{x + 15}" y="{y + 50}" font-size="18">{text}</text></g>'


def draw(eid, text, **kw):
    return ("draw_new_element", {"element_id": eid, "svg_fragment": card(eid, text, **kw), "narration": f"[[MARK:{eid}]] Here."})


def modify(eid, text, **kw):
    return ("modify_existing_element", {"element_id": eid, "new_svg_fragment": card(eid, text, **kw)})


def turn(api, rounds, final="Done.", nb=None, message="teach me"):
    client, eng = api
    nb = nb or client.post("/api/notebooks", json={"topic": "Cap"}).json()["id"]
    m, seen = model(rounds, final)
    with patch("engine.author.get_azure_client", lambda: m), patch("engine.author.generate_narration_audio", side_effect=_fake_tts), patch("engine.author.logger") as log:
        r = client.post(f"/api/notebooks/{nb}/chat", json={"message": message})
    caps = [c.kwargs["data"] for c in log.warn.call_args_list if c.args and c.args[0] == EngineEvent.LOST_CONTENT_CAP_REACHED]
    told = [c.kwargs["data"]["told_tutor"] for c in log.info.call_args_list if c.args and c.args[0] == EngineEvent.CONTENT_LOST and c.kwargs["data"].get("kind")]
    iteration = [c for c in log.warn.call_args_list if c.args and c.args[0] == EngineEvent.ITERATION_LIMIT_REACHED]
    return r, seen, caps, told, iteration, nb


def notes(seen):
    return ["lost_content" in r for r in seen["tool_results"]]


def stored_svg(api, nb):
    client, eng = api
    with Session(eng) as db:
        return db.exec(select(Page).where(Page.notebook_id == nb)).one().current_svg or ""


# ---- an element the model keeps writing a control character into --------------------------------------------------------------------

def test_a_persistent_control_character_gets_two_notes_then_none_and_the_placeholder_stays(api):
    bad = f"f(x) = x{NUL}2"
    rounds = [[draw("a", bad)], [modify("a", bad)], [modify("a", bad)], [modify("a", bad)], [modify("a", bad)]]
    r, seen, caps, told, _, nb = turn(api, rounds)
    assert r.status_code == 200
    assert notes(seen) == [True, True, False, False, False], "the draw and the first redraw are told; the next three are not"
    assert told == [True, True, False, False, False]
    assert [(c["element_id"], c["count"]) for c in caps] == [("a", 3), ("a", 4), ("a", 5)] and all(c["cap"] == 2 for c in caps)
    svg = stored_svg(api, nb)
    assert PLACEHOLDER in svg and NUL not in svg, "the placeholder stays on the board"


def test_each_element_has_its_own_two_notes_and_a_new_turn_starts_again(api):
    bad = f"x{NUL}2"
    rounds = [[draw("a", bad, x=60), draw("b", bad, x=560)], [modify("a", bad, x=60), modify("b", bad, x=560)], [modify("a", bad, x=60), modify("b", bad, x=560)]]
    r, seen, caps, told, _, nb = turn(api, rounds)
    assert notes(seen) == [True, True, True, True, False, False]
    assert sorted(c["element_id"] for c in caps) == ["a", "b"]
    r2, seen2, caps2, _, _, _ = turn(api, [[modify("a", bad, x=60)]], nb=nb, message="again")
    assert notes(seen2) == [True] and caps2 == [], "a new turn: the element is told about again"


# ---- an element that can be repaired ------------------------------------------------------------------------------------------------------

def test_a_normally_repairable_element_still_gets_its_note_and_can_be_fixed(api):
    r, seen, caps, told, _, nb = turn(api, [[draw("a", f"f(x) = x{NUL}2")], [modify("a", "f(x) = x&#178;")]])
    assert r.status_code == 200
    assert notes(seen) == [True, False], "the draw is told; the clean redraw has nothing lost"
    assert "cannot be drawn" in seen["tool_results"][0]["lost_content"] and caps == []
    svg = stored_svg(api, nb)
    assert "x²" in svg and PLACEHOLDER not in svg and NUL not in svg, "fixed on the board"


# ---- the iteration limit -----------------------------------------------------------------------------------------------------------------

def test_a_turn_that_uses_all_20_model_calls_logs_the_event_keeps_the_canned_reply_and_is_not_a_failed_turn(api):
    client, eng = api
    rounds = [[("get_current_page_state", {})] for _ in range(20)]
    r, _, _, _, iteration, nb = turn(api, rounds)
    assert r.status_code == 200 and r.json()["response"].startswith("I've drawn quite a bit on this page")
    assert len(iteration) == 1 and iteration[0].kwargs["data"]["iterations"] == 20
    with Session(eng) as db:
        rows = [(t.role, t.status) for t in db.exec(select(ChatTurn).where(ChatTurn.notebook_id == nb).order_by(ChatTurn.seq)).all()]
    assert rows == [("user", "ok"), ("assistant", "ok")], "the canned reply is a normal tutor turn: no Retry, no failed turn"


def test_a_normal_turn_logs_no_iteration_limit(api):
    r, _, _, _, iteration, _ = turn(api, [[draw("a", "Hello")]])
    assert r.status_code == 200 and iteration == []
