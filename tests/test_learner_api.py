"""Mindprint phase 2: the learner card API (what the tutor remembers, and the learner's corrections) and stated preferences in the learner note."""
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from backend.database import engine, init_db
from backend.main import app
from backend.models import DEFAULT_LEARNER_ID, Concept, Learner, Notebook, Page
from engine.mindprint import learner_note

init_db()
client = TestClient(app)


@pytest.fixture(autouse=True)
def clean():
    with Session(engine) as db:
        if db.get(Learner, DEFAULT_LEARNER_ID) is None:
            db.add(Learner(id=DEFAULT_LEARNER_ID))
            db.commit()
    client.delete("/api/learner")
    yield
    client.delete("/api/learner")


def add_concept(**kw) -> str:
    with Session(engine) as db:
        c = Concept(learner_id=DEFAULT_LEARNER_ID, name="DNS", description="names to addresses", embedding=[1.0], **kw)
        db.add(c)
        db.commit()
        return c.id


def kinds(card: dict) -> list:
    return [p["kind"] for p in card["preferences"]]


def test_card_shape_and_contents():
    empty = client.get("/api/learner").json()
    assert empty["known"] == [] and empty["misconceptions"] == [] and empty["preferences"] == []
    assert [p["kind"] for p in empty["available_preferences"]] == ["simpler", "examples", "deeper", "shorter"]
    assert empty["available_preferences"][1] == {"kind": "examples", "label": "More examples"}
    k = add_concept(level="understood")
    m = add_concept(level="taught", misconception="believes DNS is a router", misconception_corrected=True)
    add_concept(level="new")
    card = client.get("/api/learner").json()
    assert card["known"] == [{"id": k, "name": "DNS", "description": "names to addresses", "level": "understood"}]
    assert card["misconceptions"] == [{"id": m, "belief": "believes DNS is a router", "corrected": True}]


def test_preferences_add_remove_and_exclusion():
    assert client.post("/api/learner/preferences", json={"kind": "simpler"}).json()["preferences"] == [{"kind": "simpler", "label": "Simpler"}]
    client.post("/api/learner/preferences", json={"kind": "simpler"})                       # twice: still one
    client.post("/api/learner/preferences", json={"kind": "examples"})
    assert kinds(client.post("/api/learner/preferences", json={"kind": "deeper"}).json()) == ["examples", "deeper"]   # deeper replaced simpler
    assert kinds(client.post("/api/learner/preferences", json={"kind": "simpler"}).json()) == ["examples", "simpler"]
    assert kinds(client.delete("/api/learner/preferences/examples").json()) == ["simpler"]
    assert client.post("/api/learner/preferences", json={"kind": "bogus"}).status_code == 422


def test_known_goes_back_to_taught_and_misconception_clears():
    k = add_concept(level="remembered", right_turns=["a", "b"], misconception="believes x", misconception_corrected=True, misconception_lesson="h")
    card = client.delete(f"/api/learner/concepts/{k}/known").json()
    assert card["known"] == [] and len(card["misconceptions"]) == 1
    assert client.delete(f"/api/learner/concepts/{k}/misconception").json()["misconceptions"] == []
    with Session(engine) as db:
        c = db.get(Concept, k)
        assert (c.level, c.misconception, c.misconception_corrected, c.misconception_lesson) == ("taught", None, False, None)


def test_unknown_or_foreign_concept_is_404():
    assert client.delete("/api/learner/concepts/nope/known").status_code == 404
    assert client.delete("/api/learner/concepts/nope/misconception").status_code == 404
    with Session(engine) as db:
        db.add(Learner(id="other"))
        db.commit()
        c = Concept(learner_id="other", name="n", description="d", embedding=[1.0])
        db.add(c)
        db.commit()
        cid = c.id
    try:
        assert client.delete(f"/api/learner/concepts/{cid}/known").status_code == 404
    finally:
        with Session(engine) as db:
            db.delete(db.get(Concept, cid))
            db.delete(db.get(Learner, "other"))
            db.commit()


def test_forget_everything_clears_concepts_prefs_and_step_concepts():
    cid = add_concept(level="understood")
    client.post("/api/learner/preferences", json={"kind": "shorter"})
    nb = client.post("/api/notebooks", json={"topic": "Forget"}).json()["id"]
    pid = client.post(f"/api/notebooks/{nb}/pages", json={"title": "p"}).json()["id"]
    with Session(engine) as db:
        for row in (db.get(Notebook, nb), db.get(Page, pid)):
            row.step_concepts = [cid]
            db.add(row)
        db.commit()
    card = client.delete("/api/learner").json()
    assert card["known"] == [] and card["preferences"] == []
    with Session(engine) as db:
        assert db.exec(select(Concept).where(Concept.learner_id == DEFAULT_LEARNER_ID)).all() == []
        assert db.get(Notebook, nb).step_concepts is None and db.get(Page, pid).step_concepts is None


def test_note_includes_preferences_and_stays_empty_with_nothing():
    assert learner_note([], []) == ("", "") and learner_note([]) == ("", "")
    turn, plan = learner_note([], ["simpler", "shorter"])
    stated = "Stated preferences (the learner chose these): explain in simpler words, with less jargon; keep replies and board notes short."
    assert turn == stated and plan == stated
    c = {"name": "DNS", "description": "d", "level": "understood", "misconception": None}
    turn, plan = learner_note([c], ["examples"])
    stated = "Stated preferences (the learner chose these): give a concrete example before any definition."
    assert turn.endswith(stated) and plan.endswith(stated)
