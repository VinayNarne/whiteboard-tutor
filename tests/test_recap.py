"""Lesson recap: the pure builder (hand-built inputs), the stored grade, the migration and the endpoint/export."""
import sys
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).parent.parent))

from alembic import command
from sqlalchemy import create_engine, text
from fastapi.testclient import TestClient
from sqlmodel import Session

from backend.database import engine, init_db
from backend.main import app
from backend.migrate import alembic_config
from backend.models import ChatTurn
from engine.recap import build_recap, plain

init_db()
client = TestClient(app)


def t(seq, role, content, calls=None, grade=None, belief=None, status="ok"):
    return NS(seq=seq, role=role, content=content, status=status, tool_calls_made=calls, grade=grade, belief=belief)


def rec(step, event):
    return [{"tool": "record_step", "status": "ok", "element_id": str(step), "event": event}]


def test_markup_is_stripped():
    assert plain("A **packet** is ==small== [[MARK:b1_s1]] and $x^2$") == "A packet is small and x^2"


def test_board_goal_and_steps():
    blocks = [
        {"n": 2, "tool": "draw_scene", "args": {"title": "Flow", "nodes": [{"label": f"N{i}"} for i in range(9)]}},
        {"n": 1, "tool": "write_notes", "args": {"lines": [{"text": f"**L{i}**"} for i in range(10)]}},
        {"n": 3, "tool": "write_notes", "args": {"style": "recap", "lines": [{"text": f"R{i}"} for i in range(10)]}},
        {"n": 4, "tool": "write_notes", "args": {"style": "code", "lines": [{"text": "x = 1"}]}},
        {"n": 5, "tool": "draw_table", "args": {"title": "Costs"}},
    ]
    r = build_recap("GOAL: Know packets\nSTEPS:", "Packets", [{"title": "A", "level": ""}, {"title": "B", "level": "taught"}], blocks, [])
    assert r["goal"] == "Know packets" and r["steps"] == [{"title": "A", "level": "not started"}, {"title": "B", "level": "taught"}]
    kinds = [b["kind"] for b in r["board"]]
    assert kinds == ["notes", "diagram", "recap", "code", "table"]
    assert len(r["board"][0]["lines"]) == 8 and r["board"][0]["lines"][0] == "L0"
    assert r["board"][1]["lines"] == ["N0", "N1", "N2", "N3", "N4", "N5"]
    assert len(r["board"][2]["lines"]) == 10
    assert r["board"][3] == {"kind": "code", "title": "Code example", "lines": []}


def test_answers_skip_excluded_and_grader_beats_tutor():
    turns = [t(1, "assistant", "Intro. What is a packet?"), t(2, "user", "a unit of data"),
             t(3, "assistant", "Yes. Why headers?", rec(1, "answered_right")),
             t(4, "user", "ok"), t(5, "assistant", "Headers say where it goes. Got it?", rec(2, "answered_wrong")),
             t(6, "user", "idk", grade="partial"), t(7, "assistant", "Fine.", rec(2, "answered_wrong")),
             t(8, "user", "random chatter"), t(9, "assistant", "ok")]
    a = build_recap("", "P", [], [], turns)["answers"]
    assert a == [{"question": "What is a packet?", "answer": "a unit of data", "result": "right", "source": "tutor"},
                 {"question": "Got it?", "answer": "idk", "result": "partial", "source": "grader"}]   # the skip and the unrecorded chatter are out


def test_corrected_and_cleared():
    turns = [t(1, "assistant", "Q1?"), t(2, "user", "dns routes data", grade="wrong", belief="DNS carries data"),
             t(3, "assistant", "No.", rec(1, "answered_wrong")),
             t(4, "user", "a router?", grade="wrong", belief="Routers name hosts"),
             t(5, "assistant", "No.", rec(2, "answered_wrong")),
             t(6, "user", "it maps names", grade="right"), t(7, "assistant", "Yes.", rec(1, "answered_right"))]
    c = build_recap("", "P", [], [], turns)["corrected"]
    assert c == [{"belief": "DNS carries data", "cleared": True}, {"belief": "Routers name hosts", "cleared": False}]   # right on step 1 only


def test_grade_is_stored_on_the_learner_turn(tmp_path):
    from test_mindprint import GPLAN, rec as mrec, setup
    from backend.mindprint_store import grade_and_store
    db_engine, nb = setup(tmp_path)
    with Session(db_engine) as db:
        db.add(ChatTurn(id="u1", notebook_id=nb, page_id="p1", seq=1, role="user", content="a router"))
        db.commit()
    grade_and_store(db_engine, nb, GPLAN, "p1", "u1", "a router", "q?", [mrec(1, "answered_wrong")],
                    chat=lambda s, u: {"grade": "wrong", "belief": None})
    with Session(db_engine) as db:
        turn = db.get(ChatTurn, "u1")
        assert (turn.grade, turn.belief) == ("wrong", None)


def test_migration_adds_and_drops_columns(tmp_path):
    url = f"sqlite:///{(tmp_path / 'm.db').as_posix()}"
    cfg = alembic_config(url)
    command.upgrade(cfg, "head")
    cols = lambda: {r[1] for r in create_engine(url).connect().execute(text("pragma table_info(chat_turns)"))}
    assert {"grade", "belief"} <= cols()
    command.downgrade(cfg, "0014")
    assert not {"grade", "belief"} & cols()


def test_endpoint_and_export():
    nb = client.post("/api/notebooks", json={"topic": "Recap demo"}).json()["id"]
    pg = client.get(f"/api/notebooks/{nb}").json()["pages"][0]["id"]
    with Session(engine) as db:
        db.add(ChatTurn(notebook_id=nb, page_id=pg, seq=1, role="assistant", content="What is <b>DNS</b>?"))
        db.add(ChatTurn(notebook_id=nb, page_id=pg, seq=2, role="user", content="a <i>phone book</i>", grade="right"))
        db.commit()
    r = client.get(f"/api/notebooks/{nb}/pages/{pg}/recap")
    assert r.status_code == 200 and r.json()["answers"][0]["result"] == "right" and r.json()["goal"] is None
    assert client.get(f"/api/notebooks/{nb}/pages/nope/recap").status_code == 404
    html = client.get(f"/api/notebooks/{nb}/export").text
    assert "Lesson recap" in html and "&lt;i&gt;phone book" in html and "<i>phone book" not in html
