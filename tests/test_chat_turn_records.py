"""
What a chat turn records. The learner's turn keeps WHICH DRAWINGS the question was about ("ask about a drawing": validated element ids) next to the question
as typed; the tutor's turn keeps WHAT THE TUTOR DID (tool_calls_made: one record per tool call, [] for a reply that drew nothing). Both ways: pointing at
something, pointing at nothing, drawing, being rejected, failing.
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, text
from sqlmodel import Session, select

sys.path.insert(0, str(Path(__file__).parent.parent))

from alembic import command
from fastapi.testclient import TestClient

import backend.main as bm
from backend.database import engine, init_db
import seed
from test_scene import NOTES
from backend.migrate import alembic_config
from backend.models import ChatTurn

init_db()
client = TestClient(bm.app)
CARD = '<g id="{e}"><rect x="{x}" y="{y}" width="300" height="120"/><text x="{tx}" y="{ty}" font-size="16">{e}</text></g>'


def _fake_tts(narration, audio_path, alignment_path, element_id=None):
    Path(audio_path).parent.mkdir(parents=True, exist_ok=True)
    Path(audio_path).write_bytes(b"mp3")
    Path(alignment_path).write_text("{}", encoding="utf-8")
    return 1.0, 5, {"is_synthetic": False}


def _scripted(*calls, reply="Done."):
    """A fake model: one assistant message with all `calls` (name, args), then `reply`. Returns (client, messages sent on every call)."""
    sent = []

    def tc(i, name, args):
        return SimpleNamespace(id=f"c{i}", function=SimpleNamespace(name=name, arguments=json.dumps(args)))
    replies = []
    if calls:
        replies.append(SimpleNamespace(choices=[SimpleNamespace(finish_reason="tool_calls", message=SimpleNamespace(
            content=None, tool_calls=[tc(i, n, a) for i, (n, a) in enumerate(calls)]))], usage=None, model="fake"))
    replies.append(SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=reply, tool_calls=None))],
                                   usage=None, model="fake"))
    it = iter(replies)

    def create(**kw):
        sent.append(kw["messages"])
        return next(it)
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))), sent


@pytest.fixture()
def board():
    nb = client.post("/api/notebooks", json={"topic": "Records"}).json()["id"]
    pg = client.get(f"/api/notebooks/{nb}").json()["pages"][0]["id"]
    seed.draw(engine, pg, "law1", CARD.format(e="law1", x=60, y=120, tx=80, ty=180), "[[MARK:law1]] First law.")
    yield nb, pg
    client.delete(f"/api/notebooks/{nb}")


def _chat(nb, pg, message, model, **extra):
    with patch("engine.author.get_azure_client", lambda: model), patch("engine.author.generate_narration_audio", side_effect=_fake_tts):
        r = client.post(f"/api/notebooks/{nb}/chat", json={"message": message, "page_id": pg, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def _turns(nb):
    with Session(engine) as db:
        return [(t.role, t.content, t.about_element_ids, t.tool_calls_made)
                for t in db.exec(select(ChatTurn).where(ChatTurn.notebook_id == nb).order_by(ChatTurn.seq)).all()]


# ---- ask about a drawing ----------------------------------------------------------------------------------------------------------

def test_a_question_about_a_drawing_stores_the_element_id_and_the_question_as_typed(board):
    nb, pg = board
    model, sent = _scripted(reply="That is the first law.")
    _chat(nb, pg, "What is this?", model, selected_element_ids=["law1", "ghost"], gesture_type="circle")
    (role1, content1, about1, tools1), (role2, content2, about2, tools2) = _turns(nb)
    assert (role1, content1, about1) == ("user", "What is this?", ["law1"])           # the question as typed; only an element that exists on the page
    assert (role2, about2) == ("assistant", None)
    assert "Learner Question: What is this?" in sent[0][-1]["content"] and "'law1'" in sent[0][-1]["content"]      # the model still gets the pointer context


def test_a_question_about_nothing_stores_no_element_ids(board):
    nb, pg = board
    _chat(nb, pg, "Why is the sky blue?", _scripted(reply="Scattering.")[0])
    assert [t[2] for t in _turns(nb)] == [None, None]


def test_pointing_at_two_drawings_stores_both(board):
    nb, pg = board
    seed.draw(engine, pg, "law2", CARD.format(e="law2", x=460, y=120, tx=480, ty=180), "[[MARK:law2]] Second.")
    _chat(nb, pg, "How do these relate?", _scripted(reply="They are linked.")[0], selected_element_ids=["law1", "law2"])
    assert _turns(nb)[0][2] == ["law1", "law2"]


# ---- what the tutor did -------------------------------------------------------------------------------------------------------------

def test_a_text_only_reply_records_an_empty_list_of_tool_calls(board):
    nb, pg = board
    _chat(nb, pg, "Thanks!", _scripted(reply="You are welcome.")[0])
    assert _turns(nb)[1][3] == []


def test_every_tool_call_of_the_turn_is_recorded_in_order_with_its_status(board):
    nb, pg = board
    model, _ = _scripted(
        ("write_notes", NOTES),
        ("write_notes", {"lines": []}),   # nothing to write: an error the tutor is told about
        ("annotate_element", {"annotation_id": "ring", "style": "circle", "target_element_id": "b1_s1", "narration": "[[MARK:ring]] Look."}),
        ("no_such_tool", {}))
    _chat(nb, pg, "Show the second law", model)
    records = _turns(nb)[1][3]
    assert [(r["tool"], r["element_id"], r["status"]) for r in records] == [
        ("write_notes", records[0]["element_id"], "ok"), ("write_notes", records[1]["element_id"], "error"), ("annotate_element", "ring", "ok"), ("no_such_tool", None, "error")]
    assert all(r["iteration"] == 0 for r in records)


def test_a_turn_whose_model_call_failed_records_the_notice_and_no_tool_calls(board):
    nb, pg = board

    class Broken:
        chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: (_ for _ in ()).throw(TimeoutError("Request timed out."))))
    with patch("engine.author.get_azure_client", lambda: Broken()):
        assert client.post(f"/api/notebooks/{nb}/chat", json={"message": "Explain it", "page_id": pg}).status_code == 503     # typed: tests/test_failed_turns.py
    role, content, about, tools = _turns(nb)[1]
    assert role == "assistant" and content.startswith("I couldn't reach the tutor model") and tools == []


def test_the_notebook_endpoint_shows_both_records(board):
    nb, pg = board
    _chat(nb, pg, "What is this?", _scripted(("write_notes", NOTES), reply="Done.")[0], selected_element_ids=["law1"])
    turns = client.get(f"/api/notebooks/{nb}").json()["chat_turns"]
    assert turns[0]["about_element_ids"] == ["law1"] and turns[1]["tool_calls_made"][0]["tool"] == "write_notes"


# ---- the migration ----------------------------------------------------------------------------------------------------------------------

def test_old_chat_turns_survive_the_migration_with_null_records(db_url):
    cfg = alembic_config(db_url)
    command.upgrade(cfg, "0004")
    eng = create_engine(db_url)
    now = "2026-01-01 00:00:00"
    with eng.begin() as c:
        c.execute(text("insert into notebooks (id,title,topic,created_at,updated_at) values ('n','T','t',:t,:t)"), {"t": now})
        c.execute(text("insert into chat_turns (id,notebook_id,seq,role,content,timestamp) values ('c1','n',1,'user','hi',:t)"), {"t": now})
    command.upgrade(cfg, "head")
    with eng.connect() as c:
        assert c.execute(text("select content, about_element_ids, tool_calls_made from chat_turns")).fetchall() == [("hi", None, None)]
    command.downgrade(cfg, "0004")
    with eng.connect() as c:
        assert c.execute(text("select content from chat_turns")).fetchall() == [("hi",)]
