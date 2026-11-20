"""
Which turns go into a page's summary: the turns whose ANSWER is on that page.

The learner's question that opens a new page is asked while page 1 is open, so it is stored with page 1; the page is saved (and summarised) in the middle of the
turn, before the answer exists; the answer is drawn on page 2. Page 1's summary used to carry that question and read "the learner asked for X, which was not yet
addressed" about something page 2 answers (L runs 2 and 3, docs/PAGE_SUMMARIES_REVIEW.md). Rule: a tutor turn belongs to the page it ended on; a learner turn belongs
to the page of the tutor turn that answers it; a learner turn with no answer yet belongs to no page. Both ways: a two-page fixture where page 1's input leaves out
page 2's turns and narration, and a normal one-page fixture whose input is unchanged.
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

sys.path.insert(0, str(Path(__file__).parent.parent))

import backend.main as bm
import backend.page_summary as page_summary
from backend.database import engine, init_db
from backend.models import ChatTurn, Page
from engine import voice

init_db()
client = TestClient(bm.app)
ALIGN = {"characters": list("x"), "character_start_times_seconds": [0.0], "character_end_times_seconds": [1.0]}


def card(eid, i=0):
    return f'<g id="{eid}"><rect x="{40 + 380 * (i % 3)}" y="100" width="340" height="200"/><text x="{60 + 380 * (i % 3)}" y="160" font-size="16">{eid}</text></g>'


def _tc(i, name, args):
    return SimpleNamespace(id=f"c{i}", function=SimpleNamespace(name=name, arguments=json.dumps(args)))


def _model(rounds, reply):
    out = [SimpleNamespace(choices=[SimpleNamespace(finish_reason="tool_calls", message=SimpleNamespace(
        content=None, tool_calls=[_tc(i, n, a) for i, (n, a) in enumerate(r)]))], usage=None, model="fake") for r in rounds]
    out.append(SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=reply, tool_calls=None))], usage=None, model="fake"))
    it = iter(out)
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: next(it))))


class SummaryModel:
    def __init__(self):
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="A stub summary."))])


def _draw(eid, narration, i=0):
    return ("draw_new_element", {"element_id": eid, "svg_fragment": card(eid, i), "narration": f"[[MARK:{eid}]] {narration}"})


def _turn(nb, text, rounds, reply, summary_model, monkeypatch):
    monkeypatch.setattr(page_summary, "CLIENT_FACTORY", lambda: summary_model)
    with patch.object(voice, "_call_elevenlabs_tts", lambda t: (b"MP3", ALIGN, 1.0, False)), patch("engine.author.get_azure_client", lambda: _model(rounds, reply)):
        r = client.post(f"/api/notebooks/{nb}/chat", json={"message": text})
    assert r.status_code == 200, r.text


@pytest.fixture()
def notebook():
    nb = client.post("/api/notebooks", json={"topic": "Boundary"}).json()["id"]
    yield nb
    client.delete(f"/api/notebooks/{nb}")


def _pages(nb):
    with Session(engine) as db:
        return db.exec(select(Page).where(Page.notebook_id == nb).order_by(Page.page_number)).all()


def test_a_question_whose_answer_opens_the_next_page_is_not_in_the_summary_input_of_the_page_it_was_asked_on(notebook, monkeypatch):
    summaries = SummaryModel()
    _turn(notebook, "FIRST QUESTION about OSI layers", [[_draw("osi", "OSI NARRATION")]], "FIRST REPLY about OSI.", summaries, monkeypatch)
    _turn(notebook, "SECOND QUESTION about handshakes",
          [[("start_new_page", {"title": "Handshakes"})], [_draw("handshake", "HANDSHAKE NARRATION")]], "SECOND REPLY about handshakes.", summaries, monkeypatch)
    assert len(summaries.calls) == 1, "only page 1 was saved, so one summary call"
    sent = summaries.calls[0]["messages"][1]["content"]
    assert "FIRST QUESTION about OSI layers" in sent and "FIRST REPLY about OSI." in sent and "OSI NARRATION" in sent
    assert "SECOND QUESTION" not in sent and "SECOND REPLY" not in sent and "HANDSHAKE NARRATION" not in sent


def test_the_same_turns_are_tied_to_the_pages_their_answers_are_on(notebook, monkeypatch):
    _turn(notebook, "Q1", [[_draw("a", "A")]], "R1", SummaryModel(), monkeypatch)
    _turn(notebook, "Q2", [[("start_new_page", {"title": "Two"})], [_draw("b", "B")]], "R2", SummaryModel(), monkeypatch)
    p1, p2 = _pages(notebook)
    with Session(engine) as db:
        turns = db.exec(select(ChatTurn).where(ChatTurn.notebook_id == notebook).order_by(ChatTurn.seq)).all()
        assert [(t.content, t.page_id) for t in turns] == [("Q1", p1.id), ("R1", p1.id), ("Q2", p1.id), ("R2", p2.id)], "as stored: Q2 is tied to page 1"
        one, two = page_summary._transcript(db, p1), page_summary._transcript(db, p2)
    assert [(who, text) for who, _, text in one[0] if who != "drawing"] == [("learner", "Q1"), ("tutor", "R1")]
    assert [(who, text) for who, _, text in two[0] if who != "drawing"] == [("learner", "Q2"), ("tutor", "R2")], "page 2 gets the question it answered"
    assert [text for who, _, text in one[0] if who == "drawing"] == ["A"] and [text for who, _, text in two[0] if who == "drawing"] == ["B"]


def test_a_normal_one_page_notebook_has_the_input_it_always_had(notebook, monkeypatch):
    _turn(notebook, "How does binary search work?", [[_draw("array", "Here is a sorted array.")]], "It halves the range.", SummaryModel(), monkeypatch)
    _turn(notebook, "And duplicates?", [], "They can sit side by side.", SummaryModel(), monkeypatch)
    (page,) = _pages(notebook)
    with Session(engine) as db:
        items, has_drawing = page_summary._transcript(db, page)
    assert has_drawing and items == [("learner", "", "How does binary search work?"), ("tutor", "", "It halves the range."),
                                     ("learner", "", "And duplicates?"), ("tutor", "", "They can sit side by side."), ("drawing", "array", "Here is a sorted array.")]


def test_an_unanswered_question_and_a_failed_turn_are_handled_by_the_same_rule(notebook, monkeypatch):
    _turn(notebook, "Q1", [[_draw("a", "A")]], "R1", SummaryModel(), monkeypatch)
    (page,) = _pages(notebook)
    with Session(engine) as db:
        for seq, (role, status, content) in enumerate([("user", "ok", "Q2 failed"), ("assistant", "failed", "notice"), ("user", "ok", "Q3 in flight")], 10):
            db.add(ChatTurn(notebook_id=notebook, page_id=page.id, seq=seq, role=role, content=content, status=status))
        db.commit()
        items, _ = page_summary._transcript(db, page)
    said = [text for who, _, text in items if who != "drawing"]
    assert said == ["Q1", "R1"], "no answer yet, so the questions after the last ok answer belong to no page"
    with Session(engine) as db:
        db.add(ChatTurn(notebook_id=notebook, page_id=page.id, seq=20, role="assistant", content="R3 covers both", status="ok"))
        db.commit()
        items, _ = page_summary._transcript(db, page)
    assert [text for who, _, text in items if who != "drawing"] == ["Q1", "R1", "Q2 failed", "Q3 in flight", "R3 covers both"], "a failed turn's question goes with the next ok answer"
