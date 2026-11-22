"""Mindprint step 3: the learner note (engine/mindprint.py), where it goes in the messages, which concepts are relevant, and known steps in the checklist."""
from sqlmodel import Session, SQLModel, create_engine

from backend.main import lesson_final, lesson_path
from backend.mindprint_store import known_steps, note_for_turn, relevant_concepts
from backend.models import DEFAULT_LEARNER_ID, Concept, Learner, Notebook, Page
from engine import author, lesson_plan
from engine.mindprint import PLAN_SUFFIX, learner_note

C = {"name": "DNS lookup", "description": "DNS turns a name into an IP address", "level": "understood", "misconception": None}
M = {"name": "DNS role", "description": "d", "level": "taught", "misconception": "believes DNS carries the data like a router"}


def test_note_empty_understood_misconception_and_caps():
    assert learner_note([]) == ("", "")
    assert learner_note([{**C, "level": "taught"}, {**C, "level": "new"}]) == ("", "")
    turn, plan = learner_note([C])
    assert turn == ("Already understood (answered correctly in earlier lessons): DNS lookup: DNS turns a name into an IP address. "
                    "Do not re-teach these; build on them, with at most a one-line reminder.")
    assert plan == f"{turn} {PLAN_SUFFIX}"
    turn, _ = learner_note([M])
    assert turn == ("Known misconception from an earlier lesson, still open: the learner believes DNS carries the data like a router. "
                    "If it comes up, address it briefly first.")
    turn, _ = learner_note([{**M, "misconception_corrected": True}])
    assert turn == ("Misconception corrected in an earlier lesson, not yet confirmed: the learner believed DNS carries the data like a router. "
                    "Check briefly, without dwelling on it, that it has not come back.")
    turn, _ = learner_note([{**C, "name": f"n{i}"} for i in range(9)] + [{**M, "misconception": f"believes {i}"} for i in range(5)])
    assert "n5:" in turn and "n6:" not in turn and "believes 2." in turn and "believes 3" not in turn


ARGS = ("prior", "course", "plan", {}, [], None, None, [], "", "hello")


def test_tutor_messages_unchanged_without_note_and_note_right_before_the_learner():
    base = author.build_messages(*ARGS)
    assert author.build_messages(*ARGS, "") == base
    with_note = author.build_messages(*ARGS, "NOTE")
    assert with_note[:-2] == base[:-1] and with_note[-1] == base[-1]
    assert with_note[-2] == {"role": "system", "content": "LEARNER NOTES (from earlier lessons; follow them): NOTE"}


def test_plan_messages_unchanged_without_note_and_note_appended():
    assert lesson_plan.build_messages("t", "q", "") == lesson_plan.build_messages("t", "q")
    assert lesson_plan.build_next_messages("c", "x", "m", "") == lesson_plan.build_next_messages("c", "x", "m")
    for old, new in ((lesson_plan.build_messages("t", "q"), lesson_plan.build_messages("t", "q", "NOTE")),
                     (lesson_plan.build_next_messages("c", "x", "m"), lesson_plan.build_next_messages("c", "x", "m", "NOTE"))):
        assert new[0] == old[0] and new[1]["content"] == old[1]["content"] + "\n\nLEARNER NOTES (from earlier lessons; plan around them): NOTE"


PLAN = "GOAL: spoofing\nSTEPS:\n1. Names to numbers - idea; q\n2. Fake answers - idea; q\n3. Defences - idea; q\nMISCONCEPTIONS:\n- x"
X, Y = [1.0, 0.0], [0.0, 1.0]


def make(tmp_path, monkeypatch):
    monkeypatch.setenv("LP_MINDPRINT", "1")
    db_engine = create_engine(f"sqlite:///{(tmp_path / 'u.db').as_posix()}")
    SQLModel.metadata.create_all(db_engine)
    with Session(db_engine) as db:
        db.add(Learner(id=DEFAULT_LEARNER_ID))
        nb = Notebook(title="t", topic="topic", lesson_plan=PLAN, step_concepts=["a", "b", "c"])
        db.add(nb)
        db.add(Page(id="p1", notebook_id=nb.id, page_number=1, lesson_plan=PLAN, step_concepts=["a", "b", "c"]))
        for cid, level, emb, page in (("a", "understood", X, "old"), ("b", "taught", Y, "p1"), ("c", "understood", Y, "p1")):
            db.add(Concept(id=cid, learner_id=DEFAULT_LEARNER_ID, name=cid, description="d", embedding=emb, level=level, created_from_page_id=page))
        db.add(Concept(id="far", learner_id=DEFAULT_LEARNER_ID, name="far", description="d", embedding=[0.6, 0.8], level="understood"))
        db.add(Concept(id="near", learner_id=DEFAULT_LEARNER_ID, name="near", description="d", embedding=[0.9, 0.436], level="remembered"))
        db.add(Concept(id="newer", learner_id=DEFAULT_LEARNER_ID, name="newer", description="d", embedding=X, level="new"))
        db.commit()
        return db_engine, nb.id


def names(rows):
    return sorted(c["id"] for c in rows)


def test_relevance_threshold_step_concepts_and_same_plan_new_concepts(tmp_path, monkeypatch):
    db_engine, nb = make(tmp_path, monkeypatch)
    seen = []
    embed = lambda texts: seen.extend(texts) or [X]
    got = relevant_concepts(db_engine, nb, PLAN, "how does spoofing work?", "topic", embed)
    # a is a step concept from an older page; b and c were made by this plan (left out); far (0.6) and near (0.9) pass 0.45; "newer" is new
    assert seen == ["how does spoofing work?"]
    assert names(got) == ["a", "far", "near"]
    got = relevant_concepts(db_engine, nb, PLAN, "q", "topic", lambda t: [[0.0, -1.0]])      # nothing similar: only the plan's own concepts
    assert names(got) == ["a"]


def test_skip_query_falls_back_to_goal_then_topic(tmp_path, monkeypatch):
    db_engine, nb = make(tmp_path, monkeypatch)
    seen = []
    relevant_concepts(db_engine, nb, PLAN, "ok", "topic", lambda t: seen.extend(t) or [X])
    relevant_concepts(db_engine, nb, "", "ok", "topic", lambda t: seen.extend(t) or [X])
    assert seen == ["spoofing", "topic"]


def test_note_never_fails_and_is_off_when_disabled(tmp_path, monkeypatch):
    db_engine, nb = make(tmp_path, monkeypatch)
    def boom(texts):
        raise RuntimeError("embeddings down")
    assert note_for_turn(db_engine, nb, PLAN, "hello", "topic", boom) == ("", "")
    assert note_for_turn(db_engine, nb, PLAN, "hello", "topic", lambda t: [X])[0].startswith("Already understood")
    monkeypatch.setenv("LP_MINDPRINT", "0")
    assert note_for_turn(db_engine, nb, PLAN, "hello", "topic", boom) == ("", "")


def test_known_steps_skip_concepts_made_by_this_plan(tmp_path, monkeypatch):
    db_engine, nb = make(tmp_path, monkeypatch)
    assert known_steps(db_engine, nb, PLAN) == {0}       # "a" is from an older page; "c" was made by this plan's page


def rec(step, event):
    return {"tool": "record_step", "status": "ok", "element_id": str(step), "event": event}


def test_lesson_path_marks_known_steps_and_leaves_others_alone():
    path = lesson_path(PLAN, [], known={0})
    assert [(p["level"], p["from_memory"]) for p in path] == [("understood", True), ("", False), ("", False)]
    assert path[0]["due"] is False
    assert [p["from_memory"] for p in lesson_path(PLAN, [])] == [False] * 3
    earned = lesson_path(PLAN, [[rec(1, "taught")], [rec(1, "answered_right")]], known={0})
    assert earned[0]["level"] == "understood" and earned[0]["from_memory"] is False       # earned in this lesson


def test_final_check_counts_known_steps_as_taught():
    turns = [[rec(2, "taught")], [rec(3, "taught")]]
    assert lesson_final(PLAN, turns, {0})["active"] is True        # step 1 known, 2 and 3 taught
    assert lesson_final(PLAN, turns)["active"] is False            # without memory step 1 was never taught


def test_open_belief_makes_its_concept_relevant_in_one_embedding_call(tmp_path, monkeypatch):
    db_engine, nb = make(tmp_path, monkeypatch)
    with Session(db_engine) as db:
        db.add(Concept(id="m", learner_id=DEFAULT_LEARNER_ID, name="m", description="d", embedding=[0.0, -1.0], level="taught",
                       misconception="believes DNS is a router"))
        db.add(Concept(id="m2", learner_id=DEFAULT_LEARNER_ID, name="m2", description="d", embedding=[0.0, -1.0], level="taught",
                       misconception="believes something unrelated"))
        db.commit()
    calls = []

    def embed(texts):
        calls.append(texts)
        return [X if t in ("q", "believes DNS is a router") else [0.0, -1.0] for t in texts]
    got = relevant_concepts(db_engine, nb, PLAN, "q", "topic", embed)
    assert len(calls) == 1 and calls[0][0] == "q" and set(calls[0][1:]) == {"believes DNS is a router", "believes something unrelated"}
    assert "m" in names(got) and "m2" not in names(got)         # the name embeddings are far from the query; the belief is not


def test_misconception_concepts_use_a_lower_threshold(tmp_path, monkeypatch):
    db_engine, nb = make(tmp_path, monkeypatch)
    with Session(db_engine) as db:
        for cid, level, misc in (("plain", "understood", None), ("wrong", "taught", "believes x")):
            db.add(Concept(id=cid, learner_id=DEFAULT_LEARNER_ID, name=cid, description="d", embedding=[0.4, 0.9165], level=level, misconception=misc))
        db.commit()
    got = relevant_concepts(db_engine, nb, PLAN, "q", "topic", lambda t: [X] + [[0.0, -1.0]] * (len(t) - 1))     # cosine 0.40 to the query
    assert "wrong" in names(got) and "plain" not in names(got)
