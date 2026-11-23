"""
backend/learner_api.py
The learner card (Mindprint phase 2): what the tutor remembers about the one local learner, and the learner's way to correct it.
Every route returns the card. Only stored data is read or edited, so these work with LP_MINDPRINT=0.
"""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from backend.database import get_session
from backend.models import DEFAULT_LEARNER_ID, Concept, LearnerPref, Notebook, Page, TeachingLog, utc_now
from engine.lesson_plan import lesson_line, path_titles, roadmap
from engine.mindprint import EXCLUSIVE_PREFERENCES, PREFERENCES

router = APIRouter(prefix="/api/learner")
SessionDep = Annotated[Session, Depends(get_session)]
CONCEPT_NOT_FOUND = "Concept not found"
NOT_FOUND = {404: {"description": CONCEPT_NOT_FOUND}}      # OpenAPI `responses` like backend/main.py (not imported from it: main imports this module)


class PrefRequest(BaseModel):
    kind: str


def _kinds(kinds) -> list:
    return [{"kind": k, "label": PREFERENCES[k][0]} for k in kinds]


def card(db: Session) -> dict:
    concepts = db.exec(select(Concept).where(Concept.learner_id == DEFAULT_LEARNER_ID).order_by(Concept.updated_at.desc())).all()
    prefs = db.exec(select(LearnerPref).where(LearnerPref.learner_id == DEFAULT_LEARNER_ID).order_by(LearnerPref.created_at)).all()
    return {
        "known": [{"id": c.id, "name": c.name, "description": c.description, "level": c.level}
                  for c in concepts if c.level in ("understood", "remembered")],
        "misconceptions": [{"id": c.id, "belief": c.misconception, "corrected": c.misconception_corrected} for c in concepts if c.misconception],
        "preferences": _kinds(p.kind for p in prefs if p.kind in PREFERENCES),
        "available_preferences": _kinds(PREFERENCES),
    }


def _concept(db: Session, concept_id: str) -> Concept:
    c = db.get(Concept, concept_id)
    if c is None or c.learner_id != DEFAULT_LEARNER_ID:
        raise HTTPException(status_code=404, detail=CONCEPT_NOT_FOUND)
    return c


def _lessons(nb, pages) -> list:
    """(title, page_id, plan, step_concepts) for each place a plan is stored. The first plan sits on the notebook and, with a course, on the
    first page too: that is one lesson. Older notebooks keep it only on the notebook."""
    out = []
    first = pages[0].id if pages else None
    if nb.lesson_plan and not any(p.lesson_plan == nb.lesson_plan for p in pages):
        title = (roadmap(nb.course, 1) or [{"title": nb.topic}])[0]["title"]
        out.append((title, first, nb.lesson_plan, nb.step_concepts or []))
    for p in pages:
        if not p.lesson_plan:
            continue
        line = lesson_line(p.lesson_plan)
        if line is None:         # the first plan: lesson 1 of the roadmap
            title, steps = (roadmap(nb.course, 1) or [{"title": nb.topic}])[0]["title"], p.step_concepts or nb.step_concepts or []
        else:
            title, steps = line[1] or p.title or nb.topic, p.step_concepts or []
        out.append((title, p.id, p.lesson_plan, steps))
    return out


@router.get("/map")
def learner_map(db: SessionDep):
    """Your map: each notebook's lessons and their steps, with the concept each step teaches and how many other lessons share it."""
    names = {c.id: c for c in db.exec(select(Concept).where(Concept.learner_id == DEFAULT_LEARNER_ID)).all()}
    nbs = db.exec(select(Notebook).where(Notebook.learner_id == DEFAULT_LEARNER_ID).order_by(Notebook.created_at.desc())).all()
    built = []
    for nb in nbs:
        pages = db.exec(select(Page).where(Page.notebook_id == nb.id).order_by(Page.page_number)).all()
        lessons = _lessons(nb, pages)
        if lessons:
            built.append((nb, lessons))
    uses = {}                   # concept id -> number of lessons (any notebook) that include it
    for _, lessons in built:
        for *_, steps in lessons:
            for cid in {c for c in steps if c}:
                uses[cid] = uses.get(cid, 0) + 1
    out = []
    for nb, lessons in built:
        goal = next((ln.split(":", 1)[1].strip() for ln in (nb.course or "").splitlines() if ln.startswith("COURSE GOAL:")), None)
        rows = []
        for title, page_id, plan, concepts in lessons:
            steps = []
            for i, step in enumerate(path_titles(plan)):
                cid = concepts[i] if i < len(concepts) else None
                c = names.get(cid) if cid else None
                steps.append({"title": step, "concept_id": c.id if c else None, "concept": c.name if c else None,
                              "level": c.level if c else None, "shared": uses.get(c.id, 1) - 1 if c else 0})
            rows.append({"title": title, "page_id": page_id, "steps": steps})
        out.append({"id": nb.id, "topic": nb.topic, "goal": goal or None, "lessons": rows})
    return {"notebooks": out}


@router.get("")
def get_card(db: SessionDep):
    return card(db)


@router.post("/preferences", responses={422: {"description": "Unknown preference"}})
def add_preference(req: PrefRequest, db: SessionDep):
    if req.kind not in PREFERENCES:
        raise HTTPException(status_code=422, detail=f"Unknown preference: {req.kind}")
    drop = [req.kind, EXCLUSIVE_PREFERENCES.get(req.kind)]     # the opposite one goes; an existing row of this kind is kept
    rows = db.exec(select(LearnerPref).where(LearnerPref.learner_id == DEFAULT_LEARNER_ID, LearnerPref.kind.in_(drop))).all()
    if not any(r.kind == req.kind for r in rows):
        db.add(LearnerPref(learner_id=DEFAULT_LEARNER_ID, kind=req.kind))
    for r in rows:
        if r.kind != req.kind:
            db.delete(r)
    db.commit()
    return card(db)


@router.delete("/preferences/{kind}")
def remove_preference(kind: str, db: SessionDep):
    for r in db.exec(select(LearnerPref).where(LearnerPref.learner_id == DEFAULT_LEARNER_ID, LearnerPref.kind == kind)).all():
        db.delete(r)
    db.commit()
    return card(db)


@router.delete("/concepts/{concept_id}/known", responses=NOT_FOUND)
def not_known(concept_id: str, db: SessionDep):
    c = _concept(db, concept_id)
    c.level, c.right_turns, c.updated_at = "taught", [], utc_now()      # the learner says they do not know it yet: earlier right answers no longer count
    db.add(c)
    db.commit()
    return card(db)


@router.delete("/concepts/{concept_id}/misconception", responses=NOT_FOUND)
def clear_misconception(concept_id: str, db: SessionDep):
    c = _concept(db, concept_id)
    c.misconception, c.misconception_corrected, c.misconception_lesson, c.updated_at = None, False, None, utc_now()
    db.add(c)
    db.commit()
    return card(db)


@router.delete("")
def forget_everything(db: SessionDep):
    for row in db.exec(select(Concept).where(Concept.learner_id == DEFAULT_LEARNER_ID)).all():
        db.delete(row)
    for row in db.exec(select(LearnerPref).where(LearnerPref.learner_id == DEFAULT_LEARNER_ID)).all():
        db.delete(row)
    for row in db.exec(select(TeachingLog).where(TeachingLog.learner_id == DEFAULT_LEARNER_ID)).all():     # the log is learner memory too
        db.delete(row)
    notebooks = db.exec(select(Notebook).where(Notebook.learner_id == DEFAULT_LEARNER_ID)).all()
    ids = [n.id for n in notebooks]
    pages = db.exec(select(Page).where(Page.notebook_id.in_(ids))).all() if ids else []
    for row in (*notebooks, *pages):          # their step_concepts point at the deleted concepts
        row.step_concepts = None
        db.add(row)
    db.commit()
    return card(db)
