"""Mindprint concept mapping: the gate (engine/mindprint.py) with fake embeddings and a fake model, and storing a mapped plan (backend/mindprint_store.py)."""
from sqlmodel import Session, SQLModel, create_engine, select

from backend.mindprint_store import map_and_store
from backend.models import Concept, Notebook
from engine.mindprint import map_steps

# Unit vectors in 2-D: cosine to X is the first coordinate.
X = [1.0, 0.0]
CLOSE = [0.8, 0.6]      # cosine 0.80 to X
FAR = [0.6, 0.8]        # cosine 0.60 to X


def concepts(*vecs):
    return [{"id": f"id{i}", "name": f"n{i}", "description": f"d{i}", "embedding": v} for i, v in enumerate(vecs)]


def run(steps, known, vec_of_step, choices):
    """vec_of_step: the fake embedding of every step text; choices: the fake model's answer per live step."""
    def embed(texts):
        return [vec_of_step.get(t, [0.0, 1.0]) for t in texts]

    def chat(system, user):
        return {"steps": [{"step": i + 1, **c} for i, c in enumerate(choices)]}
    return map_steps(steps, known, embed, chat)


def test_reuse_accepted_when_in_top3_and_similar_enough():
    assert run(["Step A"], concepts(CLOSE, [0.0, 1.0]), {"Step A": X}, [{"choice": "c1"}]) == ["id0"]


def test_reuse_refused_when_cosine_below_gate():
    out = run(["Step A"], concepts(FAR), {"Step A": X}, [{"choice": "c1", "name": "Fresh", "description": "new idea"}])
    assert out[0]["name"] == "Fresh" and out[0]["description"] == "new idea" and "embedding" in out[0]


def test_reuse_refused_when_outside_top3():
    known = concepts(X, X, X, CLOSE)                  # the model picks the 4th nearest: similar enough, but not in the top 3
    out = run(["Step A"], known, {"Step A": X}, [{"choice": "c4"}])
    assert isinstance(out[0], dict) and out[0]["name"] == "Step A"       # no name from the model: the step text


def test_recap_step_gets_no_concept_and_is_not_sent_to_the_model():
    out = run(["Step A", "Recap and review"], [], {}, [{"choice": "NEW", "name": "A", "description": "a"}])
    assert out[1] is None and out[0]["name"] == "A"


def test_invalid_id_becomes_new():
    out = run(["Step A"], concepts(CLOSE), {"Step A": X}, [{"choice": "c99", "name": "B", "description": "b"}])
    assert isinstance(out[0], dict) and out[0]["name"] == "B"


PLAN = "LESSON: DNS\nSTEPS:\n1. Names and addresses - why\n2. The lookup chain - how\n3. Recap and review - all\nMISCONCEPTIONS:\n- none\n"


def test_store_maps_a_plan_into_the_database(tmp_path):
    db_engine = create_engine(f"sqlite:///{(tmp_path / 'mp.db').as_posix()}")
    SQLModel.metadata.create_all(db_engine)
    from backend.models import Learner, DEFAULT_LEARNER_ID
    with Session(db_engine) as db:
        db.add(Learner(id=DEFAULT_LEARNER_ID))
        nb = Notebook(title="t", topic="t", lesson_plan=PLAN)
        db.add(nb)
        db.add(Concept(learner_id=DEFAULT_LEARNER_ID, name="Old", description="old", embedding=CLOSE))
        db.commit()
        nb_id = nb.id
    answers = [{"choice": "c1"}, {"choice": "NEW", "name": "Lookup chain", "description": "resolvers"}]
    map_and_store(db_engine, nb_id, "no-such-page", PLAN, embed=lambda texts: [X] * len(texts), chat=lambda s, u: {"steps": answers})
    with Session(db_engine) as db:
        old = db.exec(select(Concept).where(Concept.name == "Old")).one()
        new = db.exec(select(Concept).where(Concept.name == "Lookup chain")).one()
        assert db.get(Notebook, nb_id).step_concepts == [old.id, new.id, None]
        assert new.level == "new" and new.right_turns == [] and new.embedding == X


# ---- the separate grader -------------------------------------------------------------------------------------------------------------------

from backend.mindprint_store import apply_grade, grade_and_store  # noqa: E402
from backend.models import DEFAULT_LEARNER_ID, Learner  # noqa: E402
from engine.mindprint import grade_answer, plan_misconceptions, plan_step_text  # noqa: E402

GPLAN = ("LESSON: DNS\nMYTHS:\n- DNS carries your data to the server\nFACTS: x\nSTEPS:\n1. Names - why\n   Check: what does DNS return? Expected: an IP address.\n"
         "2. Chain - how\n3. Recap - all\nMISCONCEPTIONS:\n- A router looks up names\nTRAPS: none\n")
MISC = "A router looks up names"


def grade(reply, answer="I think DNS carries my data like a router"):
    return grade_answer("step", "q?", plan_misconceptions(GPLAN), answer, lambda s, u: reply)


BELIEF = {"belief": "believes DNS carries the data like a router", "quote": "DNS carries my data  LIKE a router"}


def test_plan_text_helpers():
    assert "Expected: an IP address." in plan_step_text(GPLAN, 1) and plan_step_text(GPLAN, 2).startswith("Chain")
    assert plan_step_text(GPLAN, 9) == "" and "DNS carries" in plan_misconceptions(GPLAN) and MISC in plan_misconceptions(GPLAN)


def test_grade_validation():
    assert grade({"grade": "Right", "belief": None}) == {"grade": "right", "misconception": None}
    assert grade({"grade": "great", "belief": None})["grade"] is None                   # not one of the three: no grade
    assert grade({"grade": "wrong", "belief": BELIEF})["misconception"] == BELIEF["belief"]     # quote found (whitespace/case normalised)
    assert grade({"grade": "wrong", "belief": {**BELIEF, "quote": "computers are magic"}})["misconception"] is None   # quote not in the answer
    assert grade({"grade": "wrong", "belief": {**BELIEF, "quote": "DNS"}})["misconception"] is None      # quote too short
    assert grade({"grade": "right", "belief": BELIEF})["misconception"] is None                   # never a belief for a right answer
    assert grade({"grade": "wrong", "belief": None}, "um, something maybe?")["misconception"] is None     # vague: no belief
    assert grade("not a dict") == {"grade": None, "misconception": None}


def setup(tmp_path, plan=GPLAN, mapping=("c-1", None, None)):
    db_engine = create_engine(f"sqlite:///{(tmp_path / 'g.db').as_posix()}")
    SQLModel.metadata.create_all(db_engine)
    with Session(db_engine) as db:
        db.add(Learner(id=DEFAULT_LEARNER_ID))
        db.add(Concept(id="c-1", learner_id=DEFAULT_LEARNER_ID, name="Names", description="d"))
        nb = Notebook(title="t", topic="t", lesson_plan=plan, step_concepts=list(mapping))
        db.add(nb)
        db.commit()
        return db_engine, nb.id


def rec(step, event, page="p1"):
    return {"tool": "record_step", "status": "ok", "element_id": str(step), "event": event, "page_id": page}


def run_grading(db_engine, nb_id, turn, answer, records, reply):
    calls = []
    grade_and_store(db_engine, nb_id, GPLAN, "p1", turn, answer, "q?", records, chat=lambda s, u: calls.append(u) or reply)
    with Session(db_engine) as db:
        return db.get(Concept, "c-1"), len(calls)


def test_first_right_answer_understood_later_turn_remembered_and_misconception_cleared(tmp_path):
    db_engine, nb = setup(tmp_path)
    with Session(db_engine) as db:
        c = db.get(Concept, "c-1")
        c.misconception = MISC
        db.add(c)
        db.commit()
    c, _ = run_grading(db_engine, nb, "t1", "an IP address", [rec(1, "answered_right")], {"grade": "right"})
    assert c.level == "understood" and c.right_turns == ["t1"] and c.misconception == MISC and c.misconception_corrected
    c, _ = run_grading(db_engine, nb, "t1", "an IP address", [rec(1, "answered_right")], {"grade": "right"})
    assert c.level == "understood" and c.right_turns == ["t1"]                   # the same turn counts once
    c, _ = run_grading(db_engine, nb, "t2", "the address", [rec(1, "answered_right")], {"grade": "right"})
    assert c.level == "remembered" and c.right_turns == ["t1", "t2"]


def test_misconception_opens_is_corrected_in_same_lesson_cleared_in_another_and_reopens(tmp_path):
    db_engine, nb = setup(tmp_path)
    belief = {"grade": "wrong", "belief": {"belief": MISC, "quote": "x" * 20}}
    c, _ = run_grading(db_engine, nb, "t1", "x" * 20, [rec(1, "answered_wrong")], belief)
    assert (c.misconception, c.misconception_corrected) == (MISC, False) and len(c.misconception_lesson) == 16
    lesson = c.misconception_lesson
    c, _ = run_grading(db_engine, nb, "t2", "ip", [rec(1, "answered_right")], {"grade": "right"})
    assert (c.misconception, c.misconception_corrected, c.misconception_lesson) == (MISC, True, lesson)
    c, _ = run_grading(db_engine, nb, "t3", "ip", [rec(1, "answered_right")], {"grade": "right"})
    assert (c.misconception, c.misconception_corrected) == (MISC, True)          # same lesson again: still kept
    c, _ = run_grading(db_engine, nb, "t4", "x" * 20, [rec(1, "answered_wrong")], belief)
    assert (c.misconception, c.misconception_corrected) == (MISC, False)         # came back: re-opened


def test_apply_grade_right_in_another_lesson_clears_the_corrected_misconception():
    c = Concept(learner_id="l", name="n", description="d", misconception=MISC)
    apply_grade(c, "right", None, "a", "t1", "plan A")
    assert c.misconception == MISC and c.misconception_corrected
    apply_grade(c, "right", None, "a", "t2", "plan B")
    assert (c.misconception, c.misconception_corrected, c.misconception_lesson) == (None, False, None)


def test_partial_changes_nothing_and_wrong_sets_last_wrong_and_misconception(tmp_path):
    db_engine, nb = setup(tmp_path)
    c, _ = run_grading(db_engine, nb, "t1", "sort of", [rec(1, "answered_right")], {"grade": "partial"})
    assert (c.level, c.right_turns, c.last_wrong, c.misconception) == ("new", [], None, None)
    c, _ = run_grading(db_engine, nb, "t2", "x" * 600, [rec(1, "answered_wrong")], {"grade": "wrong", "belief": {"belief": MISC, "quote": "x" * 20}})
    assert c.level == "new" and c.last_wrong == "x" * 500 and c.misconception == MISC


def test_wrong_never_lowers_remembered(tmp_path):
    db_engine, nb = setup(tmp_path)
    run_grading(db_engine, nb, "t1", "a", [rec(1, "answered_right")], {"grade": "right"})
    run_grading(db_engine, nb, "t2", "a", [rec(1, "answered_right")], {"grade": "right"})
    c, _ = run_grading(db_engine, nb, "t3", "b", [rec(1, "answered_wrong")], {"grade": "wrong"})
    assert c.level == "remembered"


def test_taught_moves_new_to_taught_without_a_model_call(tmp_path):
    db_engine, nb = setup(tmp_path)
    c, calls = run_grading(db_engine, nb, "t1", "tell me more", [rec(1, "taught")], {"grade": "right"})
    assert c.level == "taught" and c.right_turns == [] and calls == 0


def test_skip_turn_and_step_without_concept_are_never_graded(tmp_path):
    db_engine, nb = setup(tmp_path)
    c, calls = run_grading(db_engine, nb, "t1", "ok", [rec(1, "answered_right")], {"grade": "right"})
    assert calls == 0 and c.right_turns == []
    c, calls = run_grading(db_engine, nb, "t2", "an IP address", [rec(2, "answered_right"), rec(1, "answered_right", page="other")], {"grade": "right"})
    assert calls == 0 and c.right_turns == []                                    # step 2 has no concept; the other page's record is not ours


def test_one_grading_per_turn_the_highest_step(tmp_path):
    db_engine, nb = setup(tmp_path, mapping=("c-1", "c-2", None))
    with Session(db_engine) as db:
        db.add(Concept(id="c-2", learner_id=DEFAULT_LEARNER_ID, name="Chain", description="d"))
        db.commit()
    _, calls = run_grading(db_engine, nb, "t1", "an IP address", [rec(1, "answered_right"), rec(2, "answered_wrong"), rec(2, "answered_wrong")], {"grade": "wrong"})
    assert calls == 1
    with Session(db_engine) as db:
        assert db.get(Concept, "c-2").last_wrong == "an IP address" and db.get(Concept, "c-1").last_wrong is None
