"""Playbook phase A: vetoes, the selector, the teaching log, the intake, and the move line in the turn note (all with fakes)."""
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

from backend.main import app
from backend.mindprint_store import grade_and_store
from backend.models import DEFAULT_LEARNER_ID, Concept, Learner, Notebook, Page, TeachingLog
from backend.playbook_store import current_step, playbook_for_turn
from engine import author
from engine.playbook import MOVES, choose_move, facts_text, intake_sentence, move_note, vetoes

PLAN = "GOAL: dns\nSTEPS:\n1. Names to numbers - idea; q\n2. Caching - idea; q\nMISCONCEPTIONS:\n- x"
client = TestClient(app)


def test_vetoes_are_exactly_the_three():
    assert vetoes({"level": "new", "tried": []}, "I don't get it") == set()                       # nothing tried: nothing to repeat
    assert vetoes({"level": "understood", "tried": []}, "ok") == {"explain_direct", "worked_example"}
    assert vetoes({"level": "remembered"}, "ok") == {"explain_direct", "worked_example"}
    assert vetoes({"level": "taught", "tried": [("analogy", "wrong"), ("trace", "right"), ("analogy", "wrong")]}, "ok") == {"analogy"}
    assert vetoes({"level": "new", "tried": [("analogy", "wrong"), ("trace", "partial")]}, "ok") == set()      # one wrong is not two
    tried = [("worked_example", "pending"), ("trace", "pending")]
    assert vetoes({"level": "new", "tried": tried}, "Can you explain it DIFFERENTLY?") == {"trace"}              # the last move on the concept
    for phrase in ("another way please", "I still don't understand", "this doesn't make sense", "still do not get it"):
        assert vetoes({"tried": tried}, phrase) == {"trace"}
    assert vetoes({"tried": tried}, "ok, continue") == set()
    assert vetoes({"tried": [], "last_move": "analogy"}, "explain it differently") == {"analogy"}               # the previous step's move
    assert vetoes({"tried": tried, "last_move": "story_case"}, "another way") == {"story_case"}
    assert vetoes({"level": "taught", "tried": [], "misconception": "x", "purpose": "exam", "time_budget": "quick"}, "ok") == set()   # no taste rules


def test_facts_text():
    assert facts_text({"level": "new", "tried": []}) == "- Concept level: new to the learner.\n- Moves already tried on this concept: none."
    full = facts_text({"level": "taught", "tried": [("analogy", "wrong"), ("trace", "pending")], "misconception": "believes DNS is a router",
                       "purpose": "work", "time_budget": "quick", "self_level": "some"})
    assert "Moves already tried on this concept: analogy -> answer graded wrong; trace -> no answer graded yet." in full
    assert "- Open misconception: learner believes DNS is a router." in full
    assert "Purpose" not in full                                  # intake only when Mindprint knows nothing about the concept
    intake = facts_text({"level": None, "tried": [], "purpose": "work", "time_budget": "quick", "self_level": "some"})
    assert "- Purpose: learning it for work or an interview." in intake and "- Time available: under 30 minutes available." in intake
    assert intake_sentence(None, None, None) == "" and "exam" in intake_sentence("exam", None, "bogus")


def test_choose_move_uses_only_allowed_moves_and_falls_back():
    seen = []
    def chat(system, user):
        seen.append(system)
        return {"move": "trace", "reason": "mechanism"}
    assert choose_move("Step", "DNS", "ok", {}, chat, {"explain_direct"}) == {"move": "trace", "reason": "mechanism"}
    assert "- explain_direct" not in seen[0] and "- trace" in seen[0]
    for bad in ({"move": "explain_direct"}, {"move": "retrieve_check"}, "text", {}):        # removed id, typo, not a dict, nothing
        got = choose_move("Step", "DNS", "ok", {}, lambda s, u: bad, {"explain_direct"})
        assert got["move"] == "worked_example" and got["reason"].startswith("fallback")
    assert choose_move("S", "T", "ok", {}, lambda s, u: {"move": "x"})["move"] == "explain_direct"
    assert move_note("trace") == "TEACHING MOVE for this turn (chosen for this learner): Trace: step through what actually happens, e.g. at runtime."
    assert len(MOVES) == 14


def make(tmp_path, monkeypatch, level="new", **intake):
    monkeypatch.setenv("LP_MINDPRINT", "1")
    db_engine = create_engine(f"sqlite:///{(tmp_path / 'p.db').as_posix()}")
    SQLModel.metadata.create_all(db_engine)
    with Session(db_engine) as db:
        db.add(Learner(id=DEFAULT_LEARNER_ID))
        db.add(Concept(id="c1", learner_id=DEFAULT_LEARNER_ID, name="Names", description="d", level=level))
        nb = Notebook(title="t", topic="DNS", lesson_plan=PLAN, step_concepts=["c1", "c2"], **intake)
        db.add(nb)
        db.add(Page(id="p1", notebook_id=nb.id, page_number=1, lesson_plan=PLAN, step_concepts=["c1", "c2"]))
        db.commit()
        return db_engine, nb.id


def test_current_step_is_next_new_step_else_last_taught():
    taught = lambda n: {"tool": "record_step", "status": "ok", "element_id": str(n), "event": "taught"}
    assert current_step(PLAN, []) == 1
    assert current_step(PLAN, [[taught(1)]]) == 2
    assert current_step(PLAN, [[taught(1), taught(2)]]) == 2
    assert current_step("", []) == 0


def test_turn_note_has_move_line_logs_it_and_outcome_follows_the_grade(tmp_path, monkeypatch):
    db_engine, nb = make(tmp_path, monkeypatch, purpose="work", time_budget="quick", self_level="some")
    prompts = []
    chat = lambda s, u: prompts.append(u) or {"move": "analogy", "reason": "abstract"}
    note, plan_note = playbook_for_turn(db_engine, nb, PLAN, [], (), "ok", "DNS", "p1", "t1", chat)
    assert note == move_note("analogy") and "for work or an interview" in plan_note and "Purpose: learning it for work" in prompts[0]
    with Session(db_engine) as db:
        row = db.exec(select(TeachingLog)).one()
        assert (row.concept_id, row.step, row.move, row.turn_id, row.outcome) == ("c1", 1, "analogy", "t1", "pending")
    # a grade on the concept sets the most recent pending row; a retried turn does not add a second row
    playbook_for_turn(db_engine, nb, PLAN, [], (), "ok", "DNS", "p1", "t1", chat)
    rec = {"tool": "record_step", "status": "ok", "element_id": "1", "event": "answered_wrong", "page_id": "p1"}
    grade_and_store(db_engine, nb, PLAN, "p1", "t2", "a router", "q?", [rec], chat=lambda s, u: {"grade": "wrong", "belief": None})
    with Session(db_engine) as db:
        assert [r.outcome for r in db.exec(select(TeachingLog)).all()] == ["wrong"]
    # the next turn sees it in its facts
    playbook_for_turn(db_engine, nb, PLAN, [], (), "ok", "DNS", "p1", "t3", chat)
    assert "analogy -> answer graded wrong" in prompts[-1]


def test_move_is_reused_until_something_changes(tmp_path, monkeypatch):
    db_engine, nb = make(tmp_path, monkeypatch)
    calls = []
    def chat(s, u):
        calls.append(u)
        return {"move": "analogy", "reason": "r"}
    def turn(tid, msg="ok", plan=PLAN, records=()):
        return playbook_for_turn(db_engine, nb, plan, list(records), (), msg, "DNS", "p1", tid, chat)[0]
    def rows():
        with Session(db_engine) as db:
            return db.exec(select(TeachingLog)).all()
    assert turn("t1") == move_note("analogy") and len(calls) == 1
    assert turn("t2") == move_note("analogy") and len(calls) == 1 and len(rows()) == 1         # plain "ok", same step, pending: reused
    taught = {"tool": "record_step", "status": "ok", "element_id": "1", "event": "taught"}
    turn("t3", records=[[taught]])                                                              # new step
    assert len(calls) == 2 and rows()[-1].step == 2
    turn("t4", "explain it differently", records=[[taught]])                                    # asked for another way
    assert len(calls) == 3
    with Session(db_engine) as db:
        last = db.exec(select(TeachingLog).order_by(TeachingLog.created_at.desc())).first()
        last.outcome = "right"
        db.add(last)
        db.commit()
    turn("t5", records=[[taught]])                                                              # graded since the last pick
    assert len(calls) == 4
    with Session(db_engine) as db:                                                              # reused move now vetoed (two wrong on it)
        for i in range(2):
            db.add(TeachingLog(learner_id=DEFAULT_LEARNER_ID, concept_id="c2", notebook_id=nb, page_id="p1", step=2, move="analogy",
                               turn_id=f"w{i}", outcome="wrong"))
        db.commit()
        db.add(TeachingLog(learner_id=DEFAULT_LEARNER_ID, concept_id="c2", notebook_id=nb, page_id="p1", step=2, move="analogy", turn_id="p0"))
        db.commit()                                                                             # newest row: analogy, pending
    chat2 = lambda s, u: calls.append(u) or {"move": "trace", "reason": "r"}
    assert playbook_for_turn(db_engine, nb, PLAN, [[taught]], (), "ok", "DNS", "p1", "t6", chat2)[0] == move_note("trace")


def test_move_not_reused_across_pages_or_without_a_concept(tmp_path, monkeypatch):
    db_engine, nb = make(tmp_path, monkeypatch)
    calls = []
    chat = lambda s, u: calls.append(u) or {"move": "analogy", "reason": "r"}
    playbook_for_turn(db_engine, nb, PLAN, [], (), "ok", "DNS", "p1", "t1", chat)
    playbook_for_turn(db_engine, nb, PLAN, [], (), "ok", "DNS", "p2", "t2", chat)              # new lesson page, same step number
    assert len(calls) == 2
    with Session(db_engine) as db:                                                              # no concept for the step: never reused
        for row in (db.get(Notebook, nb), db.get(Page, "p1")):
            row.step_concepts = []
            db.add(row)
        db.commit()
    playbook_for_turn(db_engine, nb, PLAN, [], (), "ok", "DNS", "p2", "t3", chat)
    playbook_for_turn(db_engine, nb, PLAN, [], (), "ok", "DNS", "p2", "t4", chat)
    assert len(calls) == 4


def test_no_note_when_off_or_failing_and_intake_alone_without_a_plan(tmp_path, monkeypatch):
    db_engine, nb = make(tmp_path, monkeypatch, purpose="exam")
    boom = lambda s, u: (_ for _ in ()).throw(RuntimeError("model down"))
    note, plan_note = playbook_for_turn(db_engine, nb, PLAN, [], (), "ok", "DNS", "p1", "t1", boom)      # never fails the turn
    assert note == "" and plan_note != ""                                                                # intake still reaches the plan writer
    assert playbook_for_turn(db_engine, nb, "", [], (), "ok", "DNS", "p1", "t1", boom)[0] == ""           # no plan: no move
    monkeypatch.setenv("LP_MINDPRINT", "0")
    assert playbook_for_turn(db_engine, nb, PLAN, [], (), "ok", "DNS", "p1", "t1", lambda s, u: {"move": "trace"})[0] == ""
    db_engine, nb = make(tmp_path / "..", monkeypatch)                                                    # no intake: nothing at all
    monkeypatch.setenv("LP_MINDPRINT", "0")
    assert playbook_for_turn(db_engine, nb, PLAN, [], (), "ok", "DNS", "p1", "t9", boom) == ("", "")


def test_note_reaches_the_tutor_messages_before_the_learner():
    args = ("prior", "course", "plan", {}, [], None, None, [], "", "hello")
    msgs = author.build_messages(*args, move_note("trace"))
    assert move_note("trace") in msgs[-2]["content"] and msgs[-1] == author.build_messages(*args)[-1]


def test_intake_enums_accepted_rejected_and_returned():
    ok = client.post("/api/notebooks", json={"topic": "DNS", "purpose": "work", "time_budget": "quick", "self_level": "some"})
    assert ok.status_code == 201 and (ok.json()["purpose"], ok.json()["time_budget"], ok.json()["self_level"]) == ("work", "quick", "some")
    got = client.get(f"/api/notebooks/{ok.json()['id']}").json()
    assert (got["purpose"], got["time_budget"], got["self_level"]) == ("work", "quick", "some")
    bare = client.post("/api/notebooks", json={"topic": "DNS"})
    assert bare.status_code == 201 and bare.json()["purpose"] is None
    for bad in ({"purpose": "fun"}, {"time_budget": "forever"}, {"self_level": "expert"}):
        assert client.post("/api/notebooks", json={"topic": "DNS", **bad}).status_code == 422
