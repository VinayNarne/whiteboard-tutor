"""Course roadmap (engine/lesson_plan.roadmap, GET /api/notebooks/{id}) and 'Your map' (GET /api/learner/map)."""
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from backend.database import engine, init_db
from backend.main import app
from backend.models import DEFAULT_LEARNER_ID, Concept, Learner, Notebook, Page
from engine.lesson_plan import lesson_line, roadmap

init_db()
client = TestClient(app)
COURSE = "COURSE GOAL: Read a balance sheet.\nROADMAP:\n1. Assets - what you own\n2) Liabilities\nLesson 3: Equity\n\nLEARNER: x"
PLAN = "LEARNER: x\nSTEPS:\n1. Cash: money\n2. Debt: owed\n3. Recap\nMISCONCEPTIONS: none"


def test_roadmap_parsing_and_status():
    r = roadmap(COURSE, 2)
    assert [(x["n"], x["title"], x["status"]) for x in r] == [(1, "Assets", "done"), (2, "Liabilities", "current"), (3, "Equity", "upcoming")]
    assert roadmap("", 1) == [] and roadmap(None, 1) == []
    assert [x["status"] for x in roadmap(COURSE, 0, 2)] == ["done", "done", "upcoming"]      # off the roadmap: nothing current


def test_lesson_line():
    assert lesson_line("LESSON: 2 Liabilities\nGOAL: x") == (2, "Liabilities")
    assert lesson_line("LESSON: 0 Side question") == (0, "Side question")
    assert lesson_line(PLAN) is None


@pytest.fixture(autouse=True)
def learner():
    with Session(engine) as db:
        if db.get(Learner, DEFAULT_LEARNER_ID) is None:
            db.add(Learner(id=DEFAULT_LEARNER_ID))
            db.commit()
    client.delete("/api/learner")
    created = []
    yield created
    with Session(engine) as db:
        for kind, rid in reversed(created):          # pages were made after their notebook
            if db.get(kind, rid):
                db.delete(db.get(kind, rid))
                db.commit()
    client.delete("/api/learner")


def make(created, db, rows):
    for r in rows:
        db.add(r)
        created.append((type(r), r.id))
    db.commit()


def test_notebook_roadmap_follows_current_plan(learner):
    with Session(engine, expire_on_commit=False) as db:
        nb = Notebook(title="a", topic="Balance sheets", course=COURSE, lesson_plan=PLAN)
        p1 = Page(notebook_id=nb.id, page_number=1, lesson_plan=PLAN)
        make(learner, db, [nb, p1])
        nid = nb.id
    assert [x["status"] for x in client.get(f"/api/notebooks/{nid}").json()["roadmap"]] == ["current", "upcoming", "upcoming"]
    with Session(engine, expire_on_commit=False) as db:
        p2 = Page(notebook_id=nid, page_number=2, lesson_plan="LESSON: 2 Liabilities\n" + PLAN)
        make(learner, db, [p2])
    assert [x["status"] for x in client.get(f"/api/notebooks/{nid}").json()["roadmap"]] == ["done", "current", "upcoming"]
    with Session(engine, expire_on_commit=False) as db:
        make(learner, db, [Page(notebook_id=nid, page_number=3, lesson_plan="LESSON: 0 Side question\n" + PLAN)])
    assert [x["status"] for x in client.get(f"/api/notebooks/{nid}").json()["roadmap"]] == ["done", "done", "upcoming"]
    with Session(engine, expire_on_commit=False) as db:
        nb2 = Notebook(title="b", topic="No course")
        make(learner, db, [nb2])
    assert client.get(f"/api/notebooks/{nb2.id}").json()["roadmap"] == []


def test_map_shape_shared_concepts_and_skips(learner):
    with Session(engine, expire_on_commit=False) as db:
        cash = Concept(learner_id=DEFAULT_LEARNER_ID, name="Cash", description="d", embedding=[1.0], level="understood")
        debt = Concept(learner_id=DEFAULT_LEARNER_ID, name="Debt", description="d", embedding=[1.0], level="taught")
        make(learner, db, [cash, debt])
        old = Notebook(title="old", topic="Old topic", course=COURSE, lesson_plan=PLAN, step_concepts=[cash.id, debt.id, None])
        make(learner, db, [old])
        make(learner, db, [Page(notebook_id=old.id, page_number=1, lesson_plan=PLAN, step_concepts=[cash.id, debt.id, None]),
                           Page(notebook_id=old.id, page_number=2, lesson_plan="LESSON: 2 Liabilities\n" + PLAN, step_concepts=[debt.id, None, None])])
        newer = Notebook(title="new", topic="Other topic", lesson_plan=PLAN, step_concepts=[cash.id, None, None])   # no course: first plan on the notebook only
        empty = Notebook(title="none", topic="No plan")
        make(learner, db, [newer, empty])
        make(learner, db, [Page(notebook_id=newer.id, page_number=1)])
    data = client.get("/api/learner/map").json()["notebooks"]
    ours = {n["id"]: n for n in data}
    assert empty.id not in ours
    assert [n["id"] for n in data if n["id"] in (old.id, newer.id)] == [newer.id, old.id]    # newest first
    o = ours[old.id]
    assert o["goal"] == "Read a balance sheet." and ours[newer.id]["goal"] is None
    assert [(l["title"], len(l["steps"])) for l in o["lessons"]] == [("Assets", 3), ("Liabilities", 3)]
    s = o["lessons"][0]["steps"]
    assert s[0] == {"title": "Cash", "concept_id": cash.id, "concept": "Cash", "level": "understood", "shared": 1}     # also in the other notebook
    assert s[1]["shared"] == 1 and s[1]["level"] == "taught"                                                          # debt: lesson 2 too
    assert s[2] == {"title": "Recap", "concept_id": None, "concept": None, "level": None, "shared": 0}
    n = ours[newer.id]["lessons"]
    assert len(n) == 1 and n[0]["title"] == "Other topic" and n[0]["page_id"]
