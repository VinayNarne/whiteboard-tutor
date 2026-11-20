"""
A turn the model never answered is a FAILED turn, not a tutor reply.

Before: the chat endpoint stored the apology ("I couldn't reach the tutor model ...") as an ordinary tutor turn and answered 200. It then used two of the 15
history slots, went into the page summary and the export as if the tutor had said it, and the learner saw a normal bubble with no way to ask again
(docs/PHASE2_FOUNDATIONS.md, step 6). Now: `chat_turns.status` is "ok" or "failed"; the endpoint answers a typed 503 (or 500 for a turn that broke some other way)
and keeps the failed turn for the learner's screen; the history, the page summary and the export leave failed turns out; "Try again" sends the learner's same
turn again (`retry_turn_id`) and creates no second learner turn. The model client has an explicit 60 s timeout and one retry.
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlmodel import Session, select

sys.path.insert(0, str(Path(__file__).parent.parent))

import backend.main as bm
from backend.database import engine, init_db
from backend.migrate import alembic_config
from backend.models import ChatTurn, Page
from backend.page_summary import _transcript
from engine.author import MODEL_UNREACHABLE_MESSAGE, get_azure_client
from engine.summary import build_messages

init_db()
client = TestClient(bm.app)
CARD = '<g id="{e}"><rect x="{x}" y="{y}" width="300" height="120"/><text x="{tx}" y="{ty}" font-size="16">{e}</text></g>'


def _fake_tts(narration, audio_path, alignment_path, element_id=None):
    Path(audio_path).parent.mkdir(parents=True, exist_ok=True)
    Path(audio_path).write_bytes(b"mp3")
    Path(alignment_path).write_text("{}", encoding="utf-8")
    return 1.0, 5, {"is_synthetic": False}


def _model(reply="Done."):
    """A fake model that answers every call with `reply`. Returns (client, messages sent on every call)."""
    sent = []

    def create(**kw):
        sent.append(kw["messages"])
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=reply, tool_calls=None))], usage=None, model="fake")
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))), sent


class _Broken:
    chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: (_ for _ in ()).throw(TimeoutError("Request timed out."))))


@pytest.fixture()
def board():
    nb = client.post("/api/notebooks", json={"topic": "Failures"}).json()["id"]
    pg = client.get(f"/api/notebooks/{nb}").json()["pages"][0]["id"]
    with patch("engine.author.generate_narration_audio", side_effect=_fake_tts):
        r = client.post(f"/api/notebooks/{nb}/pages/{pg}/draw", json={"element_id": "law1", "svg_fragment": CARD.format(e="law1", x=60, y=120, tx=80, ty=180),
                                                                    "narration": "[[MARK:law1]] First law."})
        assert r.status_code == 200, r.text
    yield nb, pg
    client.delete(f"/api/notebooks/{nb}")


def _post(nb, pg, message, model, **extra):
    with patch("engine.author.get_azure_client", lambda: model), patch("engine.author.generate_narration_audio", side_effect=_fake_tts):
        return client.post(f"/api/notebooks/{nb}/chat", json={"message": message, "page_id": pg, **extra})


def _rows(nb):
    with Session(engine) as db:
        return [(t.role, t.content, t.status) for t in db.exec(select(ChatTurn).where(ChatTurn.notebook_id == nb).order_by(ChatTurn.seq)).all()]


def _history_sent(messages):
    """The conversation part of the prompt: everything after the two system messages."""
    return [(m["role"], m["content"]) for m in messages[2:] if isinstance(m, dict)]


# ---- the typed error and the stored failed turn ------------------------------------------------------------------------------------

def test_a_model_that_cannot_be_reached_gives_a_typed_503_and_a_failed_turn(board):
    nb, pg = board
    r = _post(nb, pg, "Explain it", _Broken())
    body = r.json()
    assert r.status_code == 503
    assert body["error"] == "model_unreachable" and body["retryable"] is True and body["detail"] == MODEL_UNREACHABLE_MESSAGE
    assert _rows(nb) == [("user", "Explain it", "ok"), ("assistant", MODEL_UNREACHABLE_MESSAGE, "failed")]
    with Session(engine) as db:
        assert db.exec(select(ChatTurn).where(ChatTurn.notebook_id == nb, ChatTurn.role == "user")).one().id == body["turn_id"]


def test_a_turn_that_breaks_some_other_way_is_a_typed_500_and_also_a_failed_turn(board):
    nb, pg = board
    with patch("backend.main.run_whiteboard_author", new=AsyncMock(side_effect=RuntimeError("boom"))):
        r = client.post(f"/api/notebooks/{nb}/chat", json={"message": "Explain it", "page_id": pg})
    assert r.status_code == 500 and r.json()["error"] == "turn_failed" and r.json()["retryable"] is True
    assert [row[2] for row in _rows(nb)] == ["ok", "failed"]


def test_a_normal_turn_is_a_200_with_an_ok_tutor_turn(board):
    nb, pg = board
    r = _post(nb, pg, "Hello", _model("Hi there.")[0])
    assert r.status_code == 200 and r.json()["response"] == "Hi there."
    assert _rows(nb) == [("user", "Hello", "ok"), ("assistant", "Hi there.", "ok")]


# ---- what the tutor reads: both ways -----------------------------------------------------------------------------------------------

def test_a_failed_turn_is_not_in_the_next_prompt_and_a_normal_turn_is(board):
    nb, pg = board
    assert _post(nb, pg, "Explain binary search", _Broken()).status_code == 503
    model, sent = _model("It halves the range each step.")
    assert _post(nb, pg, "Show the steps", model).status_code == 200
    first = _history_sent(sent[0])
    assert first == [("user", "Explain binary search"), ("user", "Show the steps")], first      # the unanswered question stays; the notice does not
    assert all(MODEL_UNREACHABLE_MESSAGE not in content for _, content in first)
    model2, sent2 = _model("Third.")
    assert _post(nb, pg, "And the cost?", model2).status_code == 200
    third = _history_sent(sent2[0])
    assert ("assistant", "It halves the range each step.") in third, "a normal tutor turn IS read"
    assert all(MODEL_UNREACHABLE_MESSAGE not in content for _, content in third)


def test_the_fifteen_turn_window_counts_only_ok_turns(board):
    nb, pg = board
    with Session(engine) as db:
        seq = 0
        for i in range(12):                                    # 12 learner + 12 tutor ok turns, a failed notice after every learner turn
            for role, status, content in (("user", "ok", f"q{i}"), ("assistant", "failed", MODEL_UNREACHABLE_MESSAGE), ("assistant", "ok", f"a{i}")):
                seq += 1
                db.add(ChatTurn(notebook_id=nb, page_id=pg, seq=seq, role=role, content=content, status=status))
        db.commit()
    model, sent = _model()
    assert _post(nb, pg, "next", model).status_code == 200
    history = _history_sent(sent[0])[:-1]
    assert len(history) == 15 and history[-1] == ("assistant", "a11") and history[0] == ("assistant", "a4"), history
    assert all(MODEL_UNREACHABLE_MESSAGE not in content for _, content in history)


def test_the_page_summary_input_leaves_out_failed_turns_and_keeps_normal_ones(board):
    nb, pg = board
    with Session(engine) as db:
        for seq, (role, status, content) in enumerate([("user", "ok", "What is a limit?"), ("assistant", "failed", MODEL_UNREACHABLE_MESSAGE),
                                                       ("user", "ok", "Try again please"), ("assistant", "ok", "A limit is the value a function approaches.")], 1):
            db.add(ChatTurn(notebook_id=nb, page_id=pg, seq=seq, role=role, content=content, status=status))
        db.commit()
        items, _ = _transcript(db, db.get(Page, pg))
    said = [(who, text_) for who, _, text_ in items if who in ("learner", "tutor")]
    assert said == [("learner", "What is a limit?"), ("learner", "Try again please"), ("tutor", "A limit is the value a function approaches.")]
    prompt = build_messages("", items)[1]["content"]
    assert "A limit is the value" in prompt and "couldn't reach" not in prompt


def test_the_export_leaves_out_failed_turns(board):
    nb, pg = board
    assert _post(nb, pg, "Explain it", _Broken()).status_code == 503
    html = client.get(f"/api/notebooks/{nb}/export").text
    assert "Explain it" in html and "couldn&#x27;t reach the tutor model" not in html and "couldn't reach the tutor model" not in html


def test_the_notebook_shows_each_turns_status_and_which_question_to_retry(board):
    nb, pg = board
    body = _post(nb, pg, "Explain it", _Broken()).json()
    turns = client.get(f"/api/notebooks/{nb}").json()["chat_turns"]
    assert [t["status"] for t in turns] == ["ok", "failed"]
    assert turns[1]["retry_turn_id"] == turns[0]["id"] == body["turn_id"] and "retry_turn_id" not in turns[0]


# ---- try again ----------------------------------------------------------------------------------------------------------------------

def test_try_again_sends_the_same_learner_turn_again_and_creates_no_second_one(board):
    nb, pg = board
    turn_id = _post(nb, pg, "Explain it", _Broken()).json()["turn_id"]
    model, sent = _model("Here is the explanation.")
    r = _post(nb, pg, "ignored text", model, retry_turn_id=turn_id)
    assert r.status_code == 200 and r.json()["response"] == "Here is the explanation."
    assert _rows(nb) == [("user", "Explain it", "ok"), ("assistant", "Here is the explanation.", "ok")]       # one learner turn; the old notice is replaced
    history = _history_sent(sent[0])
    assert history == [("user", "Explain it")], history                                                          # sent once, as the new message; not "ignored text"


def test_try_again_keeps_the_drawings_the_question_was_about(board):
    nb, pg = board
    turn_id = _post(nb, pg, "What is this?", _Broken(), selected_element_ids=["law1"]).json()["turn_id"]
    model, sent = _model()
    assert _post(nb, pg, "x", model, retry_turn_id=turn_id).status_code == 200
    assert "'law1'" in sent[0][-1]["content"] and "Learner Question: What is this?" in sent[0][-1]["content"]
    with Session(engine) as db:
        assert db.get(ChatTurn, turn_id).about_element_ids == ["law1"]


def test_a_second_failure_leaves_one_failed_turn_not_two(board):
    nb, pg = board
    turn_id = _post(nb, pg, "Explain it", _Broken()).json()["turn_id"]
    assert _post(nb, pg, "x", _Broken(), retry_turn_id=turn_id).status_code == 503
    assert [row[2] for row in _rows(nb)] == ["ok", "failed"]


def test_try_again_is_refused_for_an_answered_question_a_newer_question_or_someone_elses_turn(board):
    nb, pg = board
    first = _post(nb, pg, "First", _Broken()).json()["turn_id"]
    assert _post(nb, pg, "Second", _model("ok")[0]).status_code == 200            # a newer question was asked and answered
    assert _post(nb, pg, "x", _model()[0], retry_turn_id=first).status_code == 409
    answered = client.get(f"/api/notebooks/{nb}").json()["chat_turns"][-2]["id"]
    assert _post(nb, pg, "x", _model()[0], retry_turn_id=answered).status_code == 409        # already answered
    assert _post(nb, pg, "x", _model()[0], retry_turn_id="no-such-turn").status_code == 404
    other = client.post("/api/notebooks", json={"topic": "Other"}).json()["id"]
    try:
        assert _post(other, None, "x", _model()[0], retry_turn_id=first).status_code == 404         # a turn of another notebook
    finally:
        client.delete(f"/api/notebooks/{other}")
    assert [row[2] for row in _rows(nb)] == ["ok", "failed", "ok", "ok"]            # nothing was added by the refused attempts


# ---- the model client ---------------------------------------------------------------------------------------------------------------

def test_the_model_client_has_an_explicit_timeout_and_one_retry():
    c = get_azure_client()
    assert c.max_retries == 1 and c.timeout.read == 60.0 and c.timeout.connect == 5.0


# ---- the migration, on SQLite and on Postgres ---------------------------------------------------------------------------------------

def test_the_status_column_is_added_with_ok_for_every_existing_turn_and_can_be_undone(db_url):
    cfg = alembic_config(db_url)
    command.upgrade(cfg, "0005")
    eng = create_engine(db_url)
    now = "2026-01-01 00:00:00"
    with eng.begin() as c:
        c.execute(text("insert into notebooks (id,title,topic,created_at,updated_at) values ('n','T','t',:t,:t)"), {"t": now})
        c.execute(text("insert into chat_turns (id,notebook_id,seq,role,content,timestamp) values ('c1','n',1,'user','hi',:t)"), {"t": now})
    command.upgrade(cfg, "head")
    with eng.begin() as c:
        assert c.execute(text("select content, status from chat_turns")).fetchall() == [("hi", "ok")]
        c.execute(text("insert into chat_turns (id,notebook_id,seq,role,content,timestamp) values ('c2','n',2,'assistant','x',:t)"), {"t": now})      # the default applies to new rows too
        assert c.execute(text("select status from chat_turns where id='c2'")).fetchall() == [("ok",)]
    command.downgrade(cfg, "0005")
    with eng.connect() as c:
        assert c.execute(text("select content from chat_turns order by id")).fetchall() == [("hi",), ("x",)]
    command.upgrade(cfg, "head")                                                        # and again: the migration is repeatable
