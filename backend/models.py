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
from sqlalchemy import Column, Index, JSON, String, Text


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


DEFAULT_LEARNER_ID = "default"


class Learner(SQLModel, table=True):
    """Who a notebook belongs to. There is no login yet: the one row (DEFAULT_LEARNER_ID) is created by migration 0004 and every notebook points at it."""
    __tablename__ = "learners"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    name: str = Field(default="Learner")
    created_at: datetime = Field(default_factory=utc_now)


class Notebook(SQLModel, table=True):
    __tablename__ = "notebooks"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    learner_id: str = Field(default=DEFAULT_LEARNER_ID, foreign_key="learners.id", index=True)
    title: str = Field(index=True)
    topic: str
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    # Scene mode: the private lesson plan written before the first answer (engine/lesson_plan.py); null until a learning question was asked.
    lesson_plan: Optional[str] = Field(default=None, sa_column=Column(Text))
    # Scene mode: the learner's overall goal and the roadmap of lessons that reach it, written with the first plan; null for older notebooks.
    course: Optional[str] = Field(default=None, sa_column=Column(Text))

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
    timestamp: datetime = Field(default_factory=utc_now)

    notebook: Optional[Notebook] = Relationship(back_populates="chat_turns")
