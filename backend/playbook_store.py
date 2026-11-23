"""
backend/playbook_store.py
Playbook in a chat turn: finds the current lesson step and its concept, builds the facts from Mindprint and the teaching log, lets
engine/playbook.py choose the teaching move, writes the log row, and returns the notes. Best effort like Mindprint: any failure is logged
and swallowed, and the turn goes on without a move line.
"""
import time

from sqlmodel import Session, select

from backend.mindprint_store import _plan_context, enabled
from backend.models import Concept, Notebook, TeachingLog
from core.events import BackendEvent
from core.log import get_logger
from engine.lesson_plan import path_titles, step_levels
from engine.playbook import EXPLAIN_DIFFERENTLY, azure_move_chat, choose_move, intake_sentence, move_note, vetoes

logger = get_logger("backend")
MAX_TRIED = 8     # recent moves shown to the selector per concept


def current_step(plan: str, records: list, known=()) -> int:
    """1-based number of the step this turn is about: the checklist's next new step, else the last taught one. 0 for a plan without steps."""
    n = len(path_titles(plan))
    levels = step_levels(n, records, known=known)
    new = [i for i, lv in enumerate(levels) if lv["level"] == ""]
    taught = [i for i, lv in enumerate(levels) if lv["level"] != ""]
    return (new[0] if new else taught[-1] if taught else 0) + 1 if n else 0


def set_outcome(db, concept_id, grade) -> None:
    """The grader graded an answer on this concept: the most recent pending move gets the grade. The caller commits."""
    if not concept_id or grade not in ("right", "partial", "wrong"):
        return
    row = db.exec(select(TeachingLog).where(TeachingLog.concept_id == concept_id, TeachingLog.outcome == "pending")
                  .order_by(TeachingLog.created_at.desc())).first()
    if row is not None:
        row.outcome = grade
        db.add(row)


def _facts(db, nb: Notebook, concept_id, turn_id: str) -> dict:
    c = db.get(Concept, concept_id) if concept_id else None
    rows = db.exec(select(TeachingLog).where(TeachingLog.concept_id == concept_id, TeachingLog.turn_id != turn_id)
                   .order_by(TeachingLog.created_at.desc()).limit(MAX_TRIED)).all() if concept_id else []
    open_belief = c.misconception if c is not None and not c.misconception_corrected else None
    return {"level": c.level if c else None, "tried": [(r.move, r.outcome) for r in reversed(rows)], "misconception": open_belief,
            "purpose": nb.purpose, "time_budget": nb.time_budget, "self_level": nb.self_level}


def _log_row(db, nb: Notebook, concept_id, page_id: str, step: int, move: str, turn_id: str) -> None:
    """One row per learner turn: a retried turn replaces its earlier choice."""
    row = db.exec(select(TeachingLog).where(TeachingLog.turn_id == turn_id)).first() or TeachingLog(
        learner_id=nb.learner_id, concept_id=concept_id, notebook_id=nb.id, page_id=page_id, step=step, move=move, turn_id=turn_id)
    row.concept_id, row.page_id, row.step, row.move = concept_id, page_id, step, move
    db.add(row)
    db.commit()


def playbook_for_turn(db_engine, notebook_id: str, plan: str, records: list, known, message: str, topic: str, page_id: str, turn_id: str,
                      chat=azure_move_chat) -> tuple:
    """Blocking (a model call): run it in a thread. -> (turn_note, plan_note), "" for each when there is nothing to add.
    The plan note is the intake sentence (also when Mindprint is off: the learner said it); the turn note is the chosen move."""
    intake = ""     # computed first so a later failure still hands the plan writer what the learner said
    try:
        with Session(db_engine) as db:
            nb = db.get(Notebook, notebook_id)
            if nb is None:
                return "", ""
            intake = intake_sentence(nb.purpose, nb.time_budget, nb.self_level)
            step = current_step(plan, records, known) if plan and enabled() else 0
            if not step:
                return "", intake
            ids = _plan_context(db, notebook_id, plan)[0]
            concept_id = ids[step - 1] if step <= len(ids) else None
            last = db.exec(select(TeachingLog).where(TeachingLog.notebook_id == notebook_id).order_by(TeachingLog.created_at.desc())).first()
            facts = _facts(db, nb, concept_id, turn_id)
            facts["last_move"] = last.move if last else None     # any step: "explain it differently" is about the last explanation heard (veto only)
            removed = vetoes(facts, message)
            # The selector call costs ~0.8 s, so a new move is picked only when something changed: a new step, a graded answer since the
            # last pick, the learner asking for another explanation, or the last move now vetoed. Otherwise the last move stays (no call, no row).
            # Same concept and page only (a new lesson's step 1 must not inherit the old one's move); a step without a concept never gets
            # an outcome, so it would be reused for the whole step: pick again instead.
            reuse = (last is not None and concept_id is not None and last.concept_id == concept_id and last.page_id == page_id
                     and last.step == step and last.outcome == "pending" and last.move not in removed
                     and not EXPLAIN_DIFFERENTLY.search(message or ""))
            started = time.monotonic()
            pick = {"move": last.move, "reason": "reused"} if reuse else choose_move(path_titles(plan)[step - 1], topic, message, facts, chat, removed)
            seconds = round(time.monotonic() - started, 2)
            if not reuse:
                _log_row(db, nb, concept_id, page_id, step, pick["move"], turn_id)
        logger.info(BackendEvent.PLAYBOOK_CHOSEN, f"Teaching move for step {step}: {pick['move']}",
                    data={"move": pick["move"], "reason": pick["reason"], "vetoed": sorted(removed), "step": step, "seconds": seconds,
                          "reused": reuse},
                    page_id=page_id)
        return move_note(pick["move"]), intake
    except Exception as e:
        logger.warn(BackendEvent.MINDPRINT_FAILED, f"Teaching move failed: {type(e).__name__}: {e}"[:300], data={"notebook_id": notebook_id})
        return "", intake
