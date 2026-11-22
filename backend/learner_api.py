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
from backend.models import DEFAULT_LEARNER_ID, Concept, LearnerPref, Notebook, Page, utc_now
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
    notebooks = db.exec(select(Notebook).where(Notebook.learner_id == DEFAULT_LEARNER_ID)).all()
    ids = [n.id for n in notebooks]
    pages = db.exec(select(Page).where(Page.notebook_id.in_(ids))).all() if ids else []
    for row in (*notebooks, *pages):          # their step_concepts point at the deleted concepts
        row.step_concepts = None
        db.add(row)
    db.commit()
    return card(db)
