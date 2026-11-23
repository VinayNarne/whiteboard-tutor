"""
backend/mindprint_store.py
Runs engine/mindprint.py's concept mapping for a lesson plan that was just saved and stores the result: new rows in `concepts`, and
`step_concepts` on the notebook and/or page that hold this plan. Best effort by design, like the page summary: it runs in the background
after the plan is saved, and any failure (embeddings, model, database) is logged and swallowed, so it never blocks or fails a chat turn.
LP_MINDPRINT=0 turns it off.
"""
import asyncio
import hashlib
import os
import threading

from sqlmodel import Session, select

from backend.models import Concept, LearnerPref, Notebook, Page, utc_now
from core.events import BackendEvent
from core.log import get_logger
from engine.author import is_skip
from engine.mindprint import azure_chat, azure_embed, cosine, grade_answer, learner_note, map_plan, plan_misconceptions, plan_step_text

logger = get_logger("backend")
_TASKS: set = set()      # the event loop keeps only weak references to tasks


def enabled() -> bool:
    return os.getenv("LP_MINDPRINT", "1") != "0"


def map_and_store(db_engine, notebook_id: str, page_id: str, plan: str, embed=azure_embed, chat=azure_chat) -> None:
    """Blocking (model calls): run it in a thread. Never raises."""
    try:
        with Session(db_engine) as db:
            nb = db.get(Notebook, notebook_id)
            if not nb or not plan:
                return
            rows = db.exec(select(Concept).where(Concept.learner_id == nb.learner_id)).all()
            known = [{"id": c.id, "name": c.name, "description": c.description, "embedding": c.embedding} for c in rows]
        mapped = map_plan(plan, known, embed, chat)
        if not mapped:
            return
        ids, created = [], 0
        with Session(db_engine) as db:
            nb = db.get(Notebook, notebook_id)
            for m in mapped:
                if isinstance(m, dict):
                    c = Concept(learner_id=nb.learner_id, name=m["name"], description=m["description"], embedding=m["embedding"],
                                created_from_page_id=page_id)
                    db.add(c)
                    m = c.id
                    created += 1
                ids.append(m)
            for row in (nb, db.get(Page, page_id)):
                if row is not None and row.lesson_plan == plan:       # the plan may have been replaced meanwhile: then these ids do not fit it
                    row.step_concepts = ids
                    db.add(row)
            db.commit()
        logger.info(BackendEvent.MINDPRINT_MAPPED, f"Mapped {len(ids)} plan step(s): {created} new concept(s)",
                    data={"steps": len(ids), "new": created, "reused": sum(1 for m in mapped if isinstance(m, str))}, page_id=page_id)
    except Exception as e:
        logger.warn(BackendEvent.MINDPRINT_FAILED, f"Concept mapping failed: {type(e).__name__}: {e}"[:300], data={"notebook_id": notebook_id})


def schedule_mapping(db_engine, notebook_id: str, page_id: str, plan: str) -> None:
    """Fire and forget, from inside the running event loop."""
    if not enabled() or not plan:
        return
    task = asyncio.create_task(asyncio.to_thread(map_and_store, db_engine, notebook_id, page_id, plan))
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)


def apply_grade(c: Concept, grade, misconception, answer: str, turn_id: str, plan: str = "") -> None:
    """The concept's new state after one graded answer. The first "right" from the separate grader means understood (it had 0 false accepts in 60
    answers, and the tutor rarely asks a step twice); a "right" in a later, different turn means remembered. "understood" and "remembered" are
    never lowered here (spaced review handles forgetting): the tutor false-misses 10-23% of right answers, so one wrong answer must not undo
    earned mastery. A misconception is not cleared by the right answer that follows its correction (they often return after one correction):
    that marks it corrected; only a right answer in a later lesson (another plan) clears it."""
    lesson = hashlib.sha256((plan or "").encode("utf-8")).hexdigest()[:16]
    if grade == "right":
        _apply_right(c, turn_id, lesson)
    elif grade in ("wrong", "partial"):
        _apply_miss(c, grade, misconception, answer, lesson)


def _apply_right(c: Concept, turn_id: str, lesson: str) -> None:
    """The misconception rules and the level rules for a right answer."""
    if turn_id not in c.right_turns:
        c.right_turns = [*c.right_turns, turn_id]                  # a new list: the JSON column does not see in-place changes
    if c.misconception and not c.misconception_corrected:
        c.misconception_corrected, c.misconception_lesson = True, lesson
    elif c.misconception and c.misconception_lesson != lesson:
        c.misconception, c.misconception_corrected, c.misconception_lesson = None, False, None
    if c.level in ("new", "taught"):
        c.level = "understood"
    elif c.level == "understood" and len(c.right_turns) >= 2:      # a right answer in a different turn than the first
        c.level = "remembered"


def _apply_miss(c: Concept, grade: str, misconception, answer: str, lesson: str) -> None:
    """A wrong or partial answer: remember the answer (wrong only) and any stated wrong belief."""
    if grade == "wrong":
        c.last_wrong = answer[:500]                                # last_wrong stays wrong-only
    if misconception:                                              # a partial answer can state a (quote-checked) wrong belief too
        c.misconception, c.misconception_corrected, c.misconception_lesson = misconception, False, lesson


def _plan_row(db_engine, notebook_id: str, plan: str):
    """The page or notebook whose plan is the one in force and already mapped, or None."""
    with Session(db_engine) as db:
        return next((r for r in [*db.exec(select(Page).where(Page.notebook_id == notebook_id)).all(), db.get(Notebook, notebook_id)]
                     if r is not None and r.lesson_plan == plan and r.step_concepts), None)


def _is_ok_record(r, page_id: str) -> bool:
    return isinstance(r, dict) and r.get("tool") == "record_step" and r.get("status") == "ok" and r.get("page_id") == page_id


def _top_answered_step(records: list, page_id: str) -> int:
    """The highest step the tutor recorded as answered on this page (0 for none)."""
    return max((int(r["element_id"]) for r in records if _is_ok_record(r, page_id) and r.get("event") in ("answered_right", "answered_wrong")
                and str(r.get("element_id")).isdigit()), default=0)


def _step_number(r):
    try:
        return int(r.get("element_id"))
    except (TypeError, ValueError):
        return None


def _store_record(db_engine, cid: str, event: str, g, n: int, answer: str, user_turn_id: str, plan: str, page_id: str) -> None:
    """Apply one record (taught, or a grade g) to its concept and save it."""
    with Session(db_engine) as db:
        c = db.get(Concept, cid)
        if c is None:
            return
        if event == "taught":
            if c.level == "new":
                c.level = "taught"
        else:
            apply_grade(c, g["grade"], g["misconception"], answer, user_turn_id, plan)
            from backend.playbook_store import set_outcome      # here: playbook_store imports this module
            set_outcome(db, cid, g["grade"])
        c.updated_at = utc_now()                               # the beliefs ranking (relevant_concepts) sorts by it
        db.add(c)
        db.commit()
        if event != "taught":
            logger.info(BackendEvent.MINDPRINT_GRADED, f"Graded step {n}: {g['grade']} (tutor: {event})",
                        data={"grade": g["grade"], "step": n, "concept_id": cid, "tutor_event": event, "misconception": g["misconception"],
                              "level": c.level, "turn_id": user_turn_id}, page_id=page_id)


def _record_target(r, page_id: str, concepts: list) -> tuple:
    """(step number, concept id, event) for an accepted step record of this page whose step has a concept; (None, None, None) otherwise."""
    n = _step_number(r) if _is_ok_record(r, page_id) else None
    cid = concepts[n - 1] if n is not None and 1 <= n <= len(concepts) else None
    event = r.get("event") if cid else None
    if event not in ("taught", "answered_right", "answered_wrong"):
        return None, None, None
    return n, cid, event


def grade_and_store(db_engine, notebook_id: str, plan: str, page_id: str, user_turn_id: str, answer: str, asked: str, records: list,
                    chat=azure_chat) -> None:
    """Blocking (model calls): run it in a thread. Never raises. records: the tutor's tool records of the finished turn. Each accepted
    answered_right/answered_wrong on this page gets one grading (a skip never does); "taught" only lifts a new concept to taught."""
    try:
        row = _plan_row(db_engine, notebook_id, plan)    # same plan as the one in force
        if row is None:
            return
        concepts = row.step_concepts
        # ponytail: one grading per turn, the highest answered step (the one being checked); a turn that really answers two steps loses
        # the lower one. Per-step grading needs the tutor to say which question each part answers.
        # Note: the first turn's "taught" for step 1 arrives before the concept mapping finishes, so it is not applied (harmless: the
        # first right answer lifts the concept to taught).
        top = _top_answered_step(records, page_id)
        for r in records:
            n, cid, event = _record_target(r, page_id, concepts)
            if cid is None:
                continue
            g = None
            if event != "taught":
                if is_skip(answer) or n != top:
                    continue
                top = 0                                                # one grading per turn, even when the step was recorded twice
                g = grade_answer(plan_step_text(plan, n), asked, plan_misconceptions(plan), answer, chat)
            _store_record(db_engine, cid, event, g, n, answer, user_turn_id, plan, page_id)
    except Exception as e:
        logger.warn(BackendEvent.MINDPRINT_FAILED, f"Grading failed: {type(e).__name__}: {e}"[:300], data={"notebook_id": notebook_id})


def schedule_grading(db_engine, notebook_id: str, plan: str, page_id: str, user_turn_id: str, answer: str, asked: str, records: list) -> None:
    """Fire and forget, from inside the running event loop, once the turn's records are saved."""
    if not enabled() or not plan or not any(isinstance(r, dict) and r.get("tool") == "record_step" for r in records):
        return
    task = asyncio.create_task(asyncio.to_thread(grade_and_store, db_engine, notebook_id, plan, page_id, user_turn_id, answer, asked, list(records)))
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)


# ---------------------------------------------------------------------------
# Step 3: using the memory in a lesson
# ---------------------------------------------------------------------------
MIN_SIMILARITY = 0.45   # ponytail: a first guess for "this concept is about the lesson's question"; to be measured in step 5
MIN_SIMILARITY_MISCONCEPTION = 0.35   # ponytail: first guess, measured next; lower because a wrong belief costs more when missed than a reminder does
TOP_SIMILAR = 6
MAX_BELIEFS = 10        # open beliefs embedded with the query (most recent first)


def warm_up() -> None:
    """At startup: one tiny background embedding opens the connection, so the first learner turn does not pay for it. Never blocks, never raises."""
    def go():
        try:
            azure_embed(["warm up"])
        except Exception as e:
            logger.warn(BackendEvent.MINDPRINT_FAILED, f"Warm-up failed: {type(e).__name__}: {e}"[:300])
    if enabled():
        threading.Thread(target=go, daemon=True).start()


def _plan_context(db, notebook_id: str, plan: str):
    """(step_concepts of the row that holds this plan, ids of the pages whose plan this is). ([], set()) for no plan."""
    if not plan:
        return [], set()
    nb = db.get(Notebook, notebook_id)
    pages = db.exec(select(Page).where(Page.notebook_id == notebook_id).order_by(Page.page_number)).all()
    rows = [*pages, nb]
    ids = [p.id for p in pages if p.lesson_plan == plan]
    if nb is not None and nb.lesson_plan == plan and pages:
        ids.append(pages[0].id)                      # the notebook's first plan was mapped for its first page
    row = next((r for r in rows if r is not None and r.lesson_plan == plan and r.step_concepts), None)
    return list(row.step_concepts) if row else [], set(ids)


def known_steps(db_engine, notebook_id: str, plan: str) -> set:
    """0-based steps of this plan whose concept the learner already understood or remembered before this lesson (not created from this plan).
    Never raises: on any error nothing is known."""
    if not enabled():
        return set()
    try:
        with Session(db_engine) as db:
            ids, same = _plan_context(db, notebook_id, plan)
            by_id = {c.id: c for c in db.exec(select(Concept).where(Concept.id.in_([i for i in ids if i]))).all()} if ids else {}
        # An open belief means not known: a wrong answer never lowers the level, so a concept can be understood and still hold one.
        return {i for i, cid in enumerate(ids) if cid in by_id and by_id[cid].level in ("understood", "remembered")
                and not (by_id[cid].misconception and not by_id[cid].misconception_corrected)
                and by_id[cid].created_from_page_id not in same}
    except Exception as e:
        logger.warn(BackendEvent.MINDPRINT_FAILED, f"Known steps failed: {type(e).__name__}: {e}"[:300], data={"notebook_id": notebook_id})
        return set()


def relevant_concepts(db_engine, notebook_id: str, plan: str, message: str, topic: str, embed=azure_embed) -> list:
    """The learner's concepts that matter to this turn: those of the current plan's steps, plus those most similar to the learner's message
    (the plan's GOAL, or the notebook topic, when the message is a skip). Only concepts with something to say count: understood, remembered, or
    an open misconception; concepts made by this very plan are left out (the lesson's own state is in the checklist)."""
    with Session(db_engine) as db:
        nb = db.get(Notebook, notebook_id)
        if nb is None:
            return []
        ids, same = _plan_context(db, notebook_id, plan)
        rows = db.exec(select(Concept).where(Concept.learner_id == nb.learner_id)).all()
        cands = [{"id": c.id, "name": c.name, "description": c.description, "level": c.level, "misconception": c.misconception,
                  "misconception_corrected": c.misconception_corrected, "embedding": c.embedding, "updated_at": c.updated_at} for c in rows
                 if (c.level in ("understood", "remembered") or c.misconception)
                 and c.created_from_page_id not in same]          # this lesson's own concepts: the checklist and the context already say where they stand
    chosen = [c for c in cands if c["id"] in ids]
    if cands:
        goal = next((line.split(":", 1)[1].strip() for line in plan.splitlines() if line.startswith("GOAL:")), "")
        query = (goal or topic) if is_skip(message) else message
        if query.strip():
            # One request: the query, then the open beliefs. A belief ("believes DNS carries the data like a router") sits closer to a question
            # than its concept's name does (0.52 against 0.39 live), so a concept with an open misconception also scores by its belief.
            believers = sorted((c for c in cands if c["misconception"]), key=lambda c: c["updated_at"], reverse=True)[:MAX_BELIEFS]
            vecs = embed([query] + [c["misconception"] for c in believers])
            v, belief_vec = vecs[0], {c["id"]: b for c, b in zip(believers, vecs[1:])}
            # ponytail: linear scan like map_steps; fine to a few thousand concepts per learner
            scored = sorted(((max(cosine(v, c["embedding"]), cosine(v, belief_vec[c["id"]]) if c["id"] in belief_vec else 0.0), c)
                             for c in cands if c["id"] not in ids), key=lambda t: -t[0])
            chosen += [c for sim, c in scored[:TOP_SIMILAR] if sim >= (MIN_SIMILARITY_MISCONCEPTION if c["misconception"] else MIN_SIMILARITY)]
    return chosen


def memory_for_turn(db_engine, notebook_id: str, plan: str, message: str, topic: str, embed=azure_embed) -> tuple:
    """Blocking: run it in a thread. -> (turn_note, plan_note, known_steps): both reads in one thread hop so the event loop never waits on the database."""
    return (*note_for_turn(db_engine, notebook_id, plan, message, topic, embed), known_steps(db_engine, notebook_id, plan))


def note_for_turn(db_engine, notebook_id: str, plan: str, message: str, topic: str, embed=azure_embed) -> tuple:
    """Blocking (an embedding call): run it in a thread. -> (turn_note, plan_note); ("", "") when off, when there is nothing to say, or on any error."""
    if not enabled():
        return "", ""
    try:
        concepts = relevant_concepts(db_engine, notebook_id, plan, message, topic, embed)
        with Session(db_engine) as db:
            nb = db.get(Notebook, notebook_id)
            prefs = [p.kind for p in db.exec(select(LearnerPref).where(LearnerPref.learner_id == nb.learner_id).order_by(LearnerPref.created_at))] if nb else []
        return learner_note(concepts, prefs)
    except Exception as e:
        logger.warn(BackendEvent.MINDPRINT_FAILED, f"Learner note failed: {type(e).__name__}: {e}"[:300], data={"notebook_id": notebook_id})
        return "", ""
