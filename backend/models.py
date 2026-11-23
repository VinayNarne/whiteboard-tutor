"""
backend/models.py
SQLModel data models for Learning Platform Phase 1.

Schema:
  Learner   (who the notebooks belong to; one default row, no login yet)
  Notebook  (one per topic/subject)
  Page      (one per concept within a notebook)
  PageEvent (single append-only event log per page — source of truth for replay)
  ChatTurn  (full conversation audit log, spans pages)
"""

from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
import uuid
from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import Boolean, Column, Index, JSON, String, Text, false as sa_false


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


DEFAULT_LEARNER_ID = "default"
LEARNERS_ID = "learners.id"      # the foreign key target of every learner_id column


class Learner(SQLModel, table=True):
    """Who a notebook belongs to. There is no login yet: the one row (DEFAULT_LEARNER_ID) is created by migration 0004 and every notebook points at it."""
    __tablename__ = "learners"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    name: str = Field(default="Learner")
    created_at: datetime = Field(default_factory=utc_now)


class Notebook(SQLModel, table=True):
    __tablename__ = "notebooks"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    learner_id: str = Field(default=DEFAULT_LEARNER_ID, foreign_key=LEARNERS_ID, index=True)
    title: str = Field(index=True)
    topic: str
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    # Scene mode: the private lesson plan written before the first answer (engine/lesson_plan.py); null until a learning question was asked.
    lesson_plan: Optional[str] = Field(default=None, sa_column=Column(Text))
    # Scene mode: the learner's overall goal and the roadmap of lessons that reach it, written with the first plan; null for older notebooks.
    course: Optional[str] = Field(default=None, sa_column=Column(Text))
    # Mindprint: the concept id of each step of lesson_plan (engine/mindprint.py), null entries for recap steps; null until mapped.
    step_concepts: Optional[List[Optional[str]]] = Field(default=None, sa_column=Column(JSON))
    # Playbook intake, optional (engine/playbook.INTAKE holds the allowed values): why they learn, how much time, how well they know it.
    purpose: Optional[str] = Field(default=None)
    time_budget: Optional[str] = Field(default=None)
    self_level: Optional[str] = Field(default=None)

    pages: List["Page"] = Relationship(back_populates="notebook")
    chat_turns: List["ChatTurn"] = Relationship(back_populates="notebook")


class Page(SQLModel, table=True):
    __tablename__ = "pages"
    __table_args__ = (Index("uq_pages_notebook_number", "notebook_id", "page_number", unique=True),)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    notebook_id: str = Field(foreign_key="notebooks.id", index=True)
    page_number: int = Field(index=True)          # 1-indexed
    title: Optional[str] = Field(default=None)    # agent-generated, one line
    summary: Optional[str] = Field(default=None)  # agent-generated, one line
    # Scene mode: the plan of the lesson that started on this page; a page without one continues the latest earlier page's plan.
    lesson_plan: Optional[str] = Field(default=None, sa_column=Column(Text))
    step_concepts: Optional[List[Optional[str]]] = Field(default=None, sa_column=Column(JSON))   # Mindprint: as on Notebook, for this page's plan

    # Quick-access composite SVG — cache only, recomputable from PageEvent rows in seq order
    current_svg: Optional[str] = Field(default=None, sa_column=Column(Text))

    # Cached density metrics — updated after every PageEvent insert
    element_count: int = Field(default=0)
    canvas_coverage: float = Field(default=0.0)   # 0.0–1.0

    # Lifecycle: "active" accepts new PageEvents; "saved" rejects all inserts
    status: str = Field(default="active", index=True)  # active | saved

    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    notebook: Optional[Notebook] = Relationship(back_populates="pages")
    events: List["PageEvent"] = Relationship(back_populates="page")


class PageEvent(SQLModel, table=True):
    """
    Single append-only event log per page.
    One shared monotonic seq per page across ALL event kinds — no separate counters.
    Replay = read all rows for a page in seq order. No interleaving, no ambiguity.

    kind="draw"   — adds a new named element; narration/audio/alignment always set
    kind="modify" — corrects a named element already in a prior draw event;
                    narration/audio/alignment nullable (a correction may be silent)
    """
    __tablename__ = "page_events"
    __table_args__ = (Index("uq_page_events_page_seq", "page_id", "seq", unique=True),)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    page_id: str = Field(foreign_key="pages.id", index=True)

    # Monotonic per page, shared across all kinds
    seq: int = Field(index=True)

    # Discriminator
    kind: str = Field(index=True)          # "draw" | "modify"

    # Present in both kinds: the element being targeted
    element_id: str

    # The SVG fragment
    # kind="draw"   → the new element being appended
    # kind="modify" → the replacement fragment for the named element
    svg_fragment: str = Field(sa_column=Column(Text))

    # kind="modify" only — snapshot before correction (null for "draw")
    old_svg_fragment: Optional[str] = Field(default=None, sa_column=Column(Text))

    # kind="draw" — what was spoken when this element appeared (null for silent modify)
    narration: Optional[str] = Field(default=None, sa_column=Column(Text))
    audio_path: Optional[str] = Field(default=None)
    alignment_path: Optional[str] = Field(default=None)

    # Scene mode, on a block's FIRST step only: what the tutor asked for and where code put it, {n, tool, args, box, steps, ids}.
    # The SVG is only the picture of it; this is the board as data, for features that need the content (edits, re-layout, icons,
    # streaming). Null on every other event and on boards drawn before 2026-11-20.
    block: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))

    timestamp: datetime = Field(default_factory=utc_now)

    page: Optional[Page] = Relationship(back_populates="events")


class ChatTurn(SQLModel, table=True):
    """
    Full conversation audit log. Persisted completely regardless of what the agent receives.
    Agent receives only the last 15 turns per SAD §3.6.
    """
    __tablename__ = "chat_turns"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    notebook_id: str = Field(foreign_key="notebooks.id", index=True)

    # nullable — some turns span page boundaries (e.g. "let's start a new page")
    page_id: Optional[str] = Field(default=None, index=True)

    seq: int = Field(index=True)               # monotonic per notebook
    role: str = Field(index=True)              # "user" | "assistant" | "tool" | "system"
    content: str = Field(sa_column=Column(Text))
    # "ok" | "failed". A failed tutor turn is the notice that the model could not be reached (or the turn broke): it is shown to the learner with a retry button
    # but is not part of the conversation the tutor reads (history, page summaries, export).
    status: str = Field(default="ok", sa_column=Column(String, nullable=False, server_default="ok"))
    # Learner turns: the drawings the learner pointed at when asking ("ask about this"), validated against the page's elements; null if they pointed at none.
    about_element_ids: Optional[List[str]] = Field(default=None, sa_column=Column(JSON))
    # Tutor turns: what the tutor did in this turn, one record per tool call {tool, element_id, status, iteration}; [] for a text-only reply.
    tool_calls_made: Optional[List[Dict[str, Any]]] = Field(default=None, sa_column=Column(JSON))
    # Learner turns the separate grader graded: its verdict (right|partial|wrong) and the quote-checked wrong belief it found. Null otherwise.
    grade: Optional[str] = Field(default=None, sa_column=Column(String, nullable=True))
    belief: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    timestamp: datetime = Field(default_factory=utc_now)

    notebook: Optional[Notebook] = Relationship(back_populates="chat_turns")


class Concept(SQLModel, table=True):
    """Mindprint: one idea a learner has met, and how well they know it (one learner per concept, so the mastery state lives on the row).
    level: new | taught | understood | remembered. right_turns: ids of the chat turns whose answer was graded right."""
    __tablename__ = "concepts"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    learner_id: str = Field(foreign_key=LEARNERS_ID, index=True)
    name: str
    description: str = Field(sa_column=Column(Text, nullable=False))
    embedding: List[float] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    level: str = Field(default="new")
    right_turns: List[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    last_wrong: Optional[str] = Field(default=None, sa_column=Column(Text))
    misconception: Optional[str] = Field(default=None, sa_column=Column(Text))
    # True once a right answer followed the belief; the belief is cleared only by a right answer in a later lesson (misconceptions return after one correction).
    misconception_corrected: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, server_default=sa_false()))
    misconception_lesson: Optional[str] = Field(default=None)    # short hash of the lesson plan in force when the belief was recorded or last corrected
    created_from_page_id: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class LearnerPref(SQLModel, table=True):
    """Mindprint: a way of being taught that the learner chose themselves (kinds are defined in engine/mindprint.PREFERENCES). Never inferred."""
    __tablename__ = "learner_prefs"
    __table_args__ = (Index("uq_learner_prefs_learner_kind", "learner_id", "kind", unique=True),)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    learner_id: str = Field(foreign_key=LEARNERS_ID, index=True)
    kind: str
    created_at: datetime = Field(default_factory=utc_now)


class TeachingLog(SQLModel, table=True):
    """Playbook: one teaching move chosen for a learner's turn. outcome: pending until the separate grader grades an answer on the concept
    (then right | partial | wrong)."""
    __tablename__ = "teaching_log"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    learner_id: str = Field(foreign_key=LEARNERS_ID, index=True)
    concept_id: Optional[str] = Field(default=None, index=True)
    notebook_id: str = Field(index=True)
    page_id: str
    step: int
    move: str
    turn_id: str
    outcome: str = Field(default="pending")
    created_at: datetime = Field(default_factory=utc_now)
