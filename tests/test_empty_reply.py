"""
An empty final reply from the model.

Before: the endpoint answered 200, stored a tutor turn with empty text, sent it to the chat panel (an empty bubble with a Copy button) and put it in the next
turn's history (docs/PHASE2_FOUNDATIONS.md, step 6 of the K round). Now:
- empty or whitespace-only final text (or only a [[MARK]] marker) and no successful draw, modify or annotation in the turn -> EmptyReply: a failed turn, a typed 503
  {"error": "empty_reply", "retryable": true}, the same error bubble and Try again as for a model that cannot be reached;
- empty final text but at least one successful draw or annotation -> the board is the answer: 200, no tutor turn stored, no extra model call, no error;
- an `empty_reply` event is logged either way, with whether a tool call succeeded;
- the history never contains an assistant turn with empty text (old notebooks too). Both ways, on SQLite and on Postgres.
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlmodel import Session, select

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.models import ChatTurn, Page
from core.events import EngineEvent
from engine.author import EMPTY_REPLY_MESSAGE


def _fake_tts(narration, audio_path, alignment_path, element_id=None):
    Path(audio_path).parent.mkdir(parents=True, exist_ok=True)
    Path(audio_path).write_bytes(b"mp3")
    Path(alignment_path).write_text("{}", encoding="utf-8")
    return 1.0, 5, {"is_synthetic": False}


def _tc(i, name, args):
    return SimpleNamespace(id=f"c{i}", function=SimpleNamespace(name=name, arguments=json.dumps(args)))


def model(rounds, final):
    """A fake model: each round is a list of (tool, args) called together, then a final stop with `final` as its text. Returns (client, messages sent per call)."""
    out = [SimpleNamespace(choices=[SimpleNamespace(finish_reason="tool_calls", message=SimpleNamespace(
        content=None, tool_calls=[_tc(i, n, a) for i, (n, a) in enumerate(r)]))], usage=None, model="fake") for r in rounds]
    out.append(SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=final, tool_calls=None))], usage=None, model="fake"))
    it, sent = iter(out), []

    def create(**kw):
        sent.append(kw["messages"])
        return next(it)
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))), sent


CARD = '<g id="{e}"><rect x="60" y="120" width="300" height="120"/><text x="80" y="180" font-size="16">{e}</text></g>'
DRAW = ("draw_new_element", {"element_id": "a", "svg_fragment": CARD.format(e="a"), "narration": "[[MARK:a]] Here."})
BAD_DRAW = ("draw_new_element", {"element_id": "b", "svg_fragment": '<g id="b"><rect x="5000" y="120" width="300" height="120"/><text x="5010" y="180">b</text></g>',
                                 "narration": "[[MARK:b]] Off the board."})
ANNOTATE = ("annotate_element", {"annotation_id": "ring", "style": "circle", "target_element_id": "a", "narration": "[[MARK:ring]] Look."})


@pytest.fixture()
def nb(api):
    client, eng = api
    nb_id = client.post("/api/notebooks", json={"topic": "Empty"}).json()["id"]
    return client, eng, nb_id


def chat(client, nb_id, message, m, **extra):
    with patch("engine.author.get_azure_client", lambda: m), patch("engine.author.generate_narration_audio", side_effect=_fake_tts), patch("engine.author.logger") as log:
        r = client.post(f"/api/notebooks/{nb_id}/chat", json={"message": message, **extra})
    events = [c for c in log.warn.call_args_list if c.args and c.args[0] == EngineEvent.EMPTY_REPLY]
    return r, events


def rows(eng, nb_id):
    with Session(eng) as db:
        return [(t.role, t.content, t.status) for t in db.exec(select(ChatTurn).where(ChatTurn.notebook_id == nb_id).order_by(ChatTurn.seq)).all()]


# ---- nothing drawn: a failed turn --------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("final", [None, "", "   \n ", "[[MARK:a]]"])
def test_an_empty_final_reply_with_nothing_drawn_is_a_failed_turn_and_a_typed_503(nb, final):
    client, eng, nb_id = nb
    r, events = chat(client, nb_id, "Explain it", model([], final)[0])
    assert r.status_code == 503
    assert r.json()["error"] == "empty_reply" and r.json()["retryable"] is True and r.json()["detail"] == EMPTY_REPLY_MESSAGE
    assert rows(eng, nb_id) == [("user", "Explain it", "ok"), ("assistant", EMPTY_REPLY_MESSAGE, "failed")]
    assert len(events) == 1 and events[0].kwargs["data"]["tool_call_succeeded"] is False


def test_try_again_after_an_empty_reply_gives_a_normal_answer_and_one_learner_turn(nb):
    client, eng, nb_id = nb
    r, _ = chat(client, nb_id, "Explain it", model([], "")[0])
    r2, events = chat(client, nb_id, "ignored", model([], "Here is the explanation.")[0], retry_turn_id=r.json()["turn_id"])
    assert r2.status_code == 200 and r2.json()["response"] == "Here is the explanation." and events == []
    assert rows(eng, nb_id) == [("user", "Explain it", "ok"), ("assistant", "Here is the explanation.", "ok")]


def test_a_rejected_drawing_is_not_a_successful_tool_call(nb):
    client, eng, nb_id = nb
    r, events = chat(client, nb_id, "Draw it", model([[BAD_DRAW]], "")[0])
    assert r.status_code == 503 and r.json()["error"] == "empty_reply"
    assert events[0].kwargs["data"]["tool_call_succeeded"] is False and events[0].kwargs["data"]["tool_calls"] == {"draw_new_element": 1}


# ---- something was drawn or annotated: the board is the answer ----------------------------------------------------------------------------

@pytest.mark.parametrize("final", [None, "", "  ", "[[MARK:a]]"])
def test_an_empty_final_reply_after_a_successful_draw_stores_no_empty_turn_and_is_not_an_error(nb, final):
    client, eng, nb_id = nb
    m, sent = model([[DRAW]], final)
    r, events = chat(client, nb_id, "Draw a", m)
    assert r.status_code == 200 and r.json()["response"] == ""
    assert rows(eng, nb_id) == [("user", "Draw a", "ok")], "no tutor turn, empty or failed"
    assert len(sent) == 2, "no extra model call: the draw round and the final reply, nothing more"
    assert len(events) == 1 and events[0].kwargs["data"]["tool_call_succeeded"] is True
    with Session(eng) as db:
        assert "a" in (db.exec(select(Page).where(Page.notebook_id == nb_id)).one().current_svg or "")


def test_an_empty_final_reply_after_a_successful_annotation_is_not_an_error_either(nb):
    client, eng, nb_id = nb
    chat(client, nb_id, "Draw a", model([[DRAW]], "Done.")[0])
    r, events = chat(client, nb_id, "Circle it", model([[ANNOTATE]], "")[0])
    assert r.status_code == 200 and r.json()["response"] == ""
    assert [row[2] for row in rows(eng, nb_id)] == ["ok", "ok", "ok"] and len(rows(eng, nb_id)) == 3
    assert events[0].kwargs["data"]["tool_call_succeeded"] is True


def test_a_normal_reply_is_unchanged_and_logs_no_empty_reply(nb):
    client, eng, nb_id = nb
    r, events = chat(client, nb_id, "Hello", model([[DRAW]], "Here you go.")[0])
    assert r.status_code == 200 and r.json()["response"] == "Here you go." and events == []
    assert rows(eng, nb_id) == [("user", "Hello", "ok"), ("assistant", "Here you go.", "ok")]


# ---- old empty tutor turns -------------------------------------------------------------------------------------------------------------

def test_an_old_empty_tutor_turn_is_never_sent_to_the_model_and_takes_no_history_slot(nb):
    client, eng, nb_id = nb
    kept = []
    with Session(eng) as db:
        seq = 0
        for i in range(12):                                   # 12 question/answer pairs, the tutor's answer empty after every second question
            for role, content in (("user", f"q{i}"), ("assistant", "" if i % 2 else f"a{i}")):
                seq += 1
                db.add(ChatTurn(notebook_id=nb_id, seq=seq, role=role, content=content))
                if content:
                    kept.append((role, content))
        db.commit()
    m, sent = model([], "Fine.")
    r, _ = chat(client, nb_id, "next", m)
    assert r.status_code == 200
    history = [(x["role"], x["content"]) for x in sent[0][2:] if isinstance(x, dict)][:-1]
    assert history == kept[-15:], "the last 15 turns with text: the empty ones are neither sent nor counted"


def test_the_export_leaves_an_old_empty_tutor_turn_out(nb):
    client, eng, nb_id = nb
    with Session(eng) as db:
        db.add(ChatTurn(notebook_id=nb_id, seq=1, role="user", content="A QUESTION"))
        db.add(ChatTurn(notebook_id=nb_id, seq=2, role="assistant", content=""))
        db.commit()
    html = client.get(f"/api/notebooks/{nb_id}/export").text
    assert html.count("A QUESTION") == 1 and "<span class='who'>Tutor</span>" not in html
