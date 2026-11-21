"""
backend/main.py
FastAPI backend for Learning Platform Phase 1.

Endpoints:
  POST /api/notebooks                  — create a new notebook
  GET  /api/notebooks                  — list notebooks
  GET  /api/notebooks/{id}             — get notebook with pages
  POST /api/notebooks/{id}/pages       — start a new page
  POST /api/notebooks/{id}/pages/{pid}/save  — save (lock) a page
  POST /api/notebooks/{id}/chat        — send a learner message → triggers WhiteboardAuthor
  GET  /api/notebooks/{id}/pages/{pid}/events — page event log (for replay)
  WS   /api/ws/notebooks/{id}          — real-time event stream

Static: /static/notebooks/{notebook_id}/{page_id}/
"""

import sys
import os
import asyncio
import json
from contextlib import asynccontextmanager
import re
import shutil

if sys.platform == "win32":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass

from pathlib import Path
from typing import Optional, List, Annotated
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
import requests
import websockets

load_dotenv()

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func
from sqlmodel import Session, select

from core.log import get_logger, log_context, init_logging
from core.events import BackendEvent, SessionEvent
from backend.database import init_db, get_session, engine
from backend.models import Notebook, Page, PageEvent, ChatTurn
from backend.ws import manager, emit_notebook_event
from engine.markers import strip_markers
from backend.event_store import append_event
from engine.validator import compute_coverage
from backend.page_summary import summarise_saved_page
from backend.page_state import is_drawing, rebuild_page_svg, annotation_target_ids, prior_pages_summary, summaries_in_context
from backend.limits import no_control_chars
from backend.limits import (
    CHAT_LIMITER, VOICE_LIMITER, CLIENT_LOG_LIMITER, TOO_FAST, MAX_VOICE_SECONDS, Topic, Title, ChatText, Summary, Narration, Svg,
)

from engine.scene import ID_RE as SCENE_ID_RE, board_blocks, board_font_css, missing_parts
from engine.lesson_plan import final_check, path_titles, split_course, step_levels, write_next_plan, write_plan
from engine.author import run_whiteboard_author, OUTPUT_DIR, ModelUnreachable, MODEL_UNREACHABLE_MESSAGE, EmptyReply, EMPTY_REPLY_MESSAGE, MODEL_NOT_CONFIGURED_MESSAGE, model_configured

logger = get_logger("backend")

# How many chat turns the tutor reads. TEST ONLY: LP_TEST_HISTORY_TURNS shrinks the window so an earlier page is out of the history (eval M); the default is 15.
HISTORY_TURNS = int(os.getenv("LP_TEST_HISTORY_TURNS", "15"))

# Active agent tasks per notebook for live barge-in cancellation
ACTIVE_AGENT_TASKS: dict[str, asyncio.Task] = {}

SessionDep = Annotated[Session, Depends(get_session)]

MAX_AUDIO_BYTES = 10 * 1024 * 1024  # ~10 MB covers minutes of speech
MAX_VOICE_STREAM_BYTES = 50 * 1024 * 1024  # per live-voice connection

@asynccontextmanager
async def lifespan(_app: FastAPI):
    on_startup()
    yield


app = FastAPI(title="Learning Platform API", version="1.0.0", lifespan=lifespan)

# Only pages served from this machine may call the API from a browser: any port on localhost,
# 127.0.0.1 or [::1] (Vite picks 5173 by default, other tools use other ports). Other websites are
# refused. CORS_ORIGINS="https://a.example,https://b.example" adds extra origins.
LOCAL_ORIGIN_PATTERN = r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$"
EXTRA_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=EXTRA_ORIGINS,
    allow_origin_regex=LOCAL_ORIGIN_PATTERN,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _origin_ok(origin: str) -> bool:
    return bool(re.match(LOCAL_ORIGIN_PATTERN, origin)) or origin in EXTRA_ORIGINS


def _ws_origin_ok(websocket: WebSocket) -> bool:
    """Browsers don't apply CORS to WebSockets; reject foreign pages. Non-browser clients send no Origin."""
    origin = websocket.headers.get("origin")
    return origin is None or _origin_ok(origin)


@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    notebook_id = request.headers.get("X-Notebook-ID") or request.query_params.get("notebook_id")
    page_id = request.headers.get("X-Page-ID") or request.query_params.get("page_id")
    path_parts = request.url.path.strip("/").split("/")
    for i, part in enumerate(path_parts):
        if part == "notebooks" and i + 1 < len(path_parts) and not notebook_id:
            notebook_id = path_parts[i + 1]
        elif part == "pages" and i + 1 < len(path_parts) and not page_id:
            page_id = path_parts[i + 1]
    with log_context(session_id=notebook_id, page_id=page_id):
        if request.method == "POST" and "/chat" in request.url.path:
            import time as _time
            t0 = _time.time()
            logger.info(BackendEvent.CHAT_RECEIVED,
                        f"Chat request started: {request.url.path}",
                        data={"path": request.url.path})
            response = await call_next(request)
            elapsed = round(_time.time() - t0, 2)
            logger.info(BackendEvent.CHAT_COMPLETED,
                        f"Chat request finished in {elapsed}s: {request.url.path}",
                        data={"elapsed_s": elapsed, "status": response.status_code})
            return response
        return await call_next(request)


OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static/notebooks", StaticFiles(directory=str(OUTPUT_DIR)), name="notebooks_static")


def on_startup():
    # Explicit logging init — file + console with INFO level
    from pathlib import Path as _Path
    init_logging(log_file=_Path("logs/learning_platform.jsonl"), force=True)
    # Import models so SQLModel registers all tables before create_all
    from backend import models  # noqa: F401
    init_db()
    logger.info(BackendEvent.SERVER_STARTUP, "Learning Platform API started", data={"port": 8001})
    if not model_configured():
        logger.warn(BackendEvent.SERVER_STARTUP, MODEL_NOT_CONFIGURED_MESSAGE, data={"missing": ["AZURE_OPENAI_API_KEY or AZURE_OPENAI_ENDPOINT"]})
    missing = missing_parts()   # say at startup what the lesson board needs, not at the learner's first question
    if missing:
        logger.warn(BackendEvent.SERVER_STARTUP, "Scene mode is on but cannot draw: " + "; ".join(missing), data={"missing": missing})
    else:
        try:
            board_font_css()   # build the export fonts now (about a second, once), not in the middle of the first lesson
        except Exception as e:  # a broken font file must not keep the app from starting; the first block will report it to the tutor
            logger.warn(BackendEvent.SERVER_STARTUP, f"Scene mode: export fonts could not be built: {e}", data={"error": str(e)[:300]})


# ---------------------------------------------------------------------------
# Request/Response schemas
# ---------------------------------------------------------------------------

class CreateNotebookRequest(BaseModel):
    topic: Topic
    title: Optional[Title] = None

class UpdateNotebookRequest(BaseModel):
    topic: Optional[Topic] = None
    title: Optional[Title] = None

class StartPageRequest(BaseModel):
    title: Optional[Title] = None

class SavePageRequest(BaseModel):
    title: Optional[Title] = None
    final_svg: Optional[Svg] = None
    summary: Optional[Summary] = None
    element_count: Optional[int] = None

class UpdatePageRequest(BaseModel):
    title: Optional[Title] = None
    summary: Optional[Summary] = None

class ChatRequest(BaseModel):
    message: ChatText
    page_id: Optional[str] = None  # if None, uses the most recent active page
    selected_element_ids: Optional[List[str]] = Field(default=None, max_length=10)
    gesture_type: Optional[str] = Field(default="circle", max_length=20)
    match_score: Optional[float] = None
    # "Try again": the id of the learner turn the tutor never answered. That same turn is sent again (its stored text and pointed-at drawings; `message`
    # is ignored), so no second learner turn is created.
    retry_turn_id: Optional[str] = Field(default=None, max_length=64)

class AnnotateElementRequest(BaseModel):
    annotation_id: str = Field(max_length=100)
    style: str = Field(max_length=20)
    target_element_id: str = Field(max_length=100)
    from_element_id: Optional[str] = Field(default=None, max_length=100)
    color: Optional[str] = Field(default=None, max_length=40)
    note: Optional[str] = Field(default=None, max_length=200)
    lifetime: Optional[str] = Field(default="ephemeral", max_length=20)
    duration_ms: Optional[int] = Field(default=3000, ge=0, le=60000)
    narration: Optional[Narration] = None

class RemoveAnnotationRequest(BaseModel):
    annotation_id: str = Field(max_length=100)


# ---------------------------------------------------------------------------
# Notebook endpoints
# ---------------------------------------------------------------------------

@app.post("/api/notebooks", status_code=201)
def create_notebook(req: CreateNotebookRequest, session: SessionDep):
    nb = Notebook(
        topic=req.topic,
        title=req.title or req.topic,
    )
    session.add(nb)
    session.commit()
    session.refresh(nb)

    # Auto-create initial active Page 1
    p1 = Page(
        notebook_id=nb.id,
        page_number=1,
        status="active"
    )
    session.add(p1)
    session.commit()

    logger.info(BackendEvent.NOTEBOOK_CREATED, f"Notebook created: {nb.id}",
                data={"topic": nb.topic})
    return {"id": nb.id, "topic": nb.topic, "title": nb.title, "created_at": nb.created_at.isoformat()}


@app.get("/api/notebooks")
def list_notebooks(session: SessionDep):
    nbs = session.exec(select(Notebook).order_by(Notebook.created_at.desc())).all()
    return [{"id": n.id, "topic": n.topic, "title": n.title,
             "created_at": n.created_at.isoformat()} for n in nbs]


@app.get("/api/notebooks/{notebook_id}")
def get_notebook(notebook_id: str, session: SessionDep):
    nb = session.get(Notebook, notebook_id)
    if not nb:
        raise HTTPException(status_code=404, detail="Notebook not found")
    pages = session.exec(
        select(Page).where(Page.notebook_id == notebook_id).order_by(Page.page_number)
    ).all()
    turns = session.exec(
        select(ChatTurn).where(ChatTurn.notebook_id == notebook_id).order_by(ChatTurn.seq.asc())
    ).all()
    return {
        "id": nb.id, "topic": nb.topic, "title": nb.title,
        "created_at": nb.created_at.isoformat(),
        "pages": [
            {
                "id": p.id, "page_number": p.page_number,
                "title": p.title, "summary": p.summary,
                "status": p.status, "element_count": p.element_count,
                "created_at": p.created_at.isoformat()
            } for p in pages
        ],
        "chat_turns": _chat_turns_json(turns),
        "lesson_board": True,   # pages are lesson boards that never fill up (the frontend reads this)
        **_lesson_state(nb, pages, turns),
    }


def _lesson_state(nb, pages, turns) -> dict:
    """What the learner sees of the current lesson: its checklist, its final check, and the course goal."""
    plan, records = current_lesson(nb, pages, turns)
    goal = next((line.split(":", 1)[1].strip() for line in (nb.course or "").splitlines() if line.startswith("COURSE GOAL:")), None)
    return {"lesson_path": lesson_path(plan, records), "lesson_final": lesson_final(plan, records), "goal": goal or None}


def time_away(last, now=None) -> str:
    """How long the learner was away since the last turn, in words, when it was at least 30 minutes ("" otherwise): their next
    message gets a one-sentence welcome back instead of the lesson carrying on as if no time had passed."""
    last = last if last.tzinfo else last.replace(tzinfo=timezone.utc)
    gap = (now or datetime.now(timezone.utc)) - last
    if gap < timedelta(minutes=30):
        return ""
    hours = gap.total_seconds() / 3600
    return "about an hour" if hours < 1.5 else f"about {round(hours)} hours" if hours < 36 else f"about {round(hours / 24)} days"


def _tutor_records(turns, scope=None) -> list:
    """Each ok tutor turn's tool records, oldest first. scope: page ids; only records made on those pages count (a record_step carries the
    page it was made on, older ones the turn's page), so a new lesson's checklist starts empty."""
    out = []
    for t in sorted(turns, key=lambda t: t.seq):
        if t.role != "assistant" or t.status not in ("ok", "silent"):   # silent: a turn that only drew, or was interrupted (its records count)
            continue
        records = [r for r in (t.tool_calls_made or []) if scope is None or (isinstance(r, dict) and (r.get("page_id") or t.page_id) in scope)]
        if scope is None or t.page_id in scope or records:
            out.append(records)
    return out


def current_lesson(nb, pages, turns) -> tuple:
    """(plan, records) of the lesson in progress: the plan of the latest page that has one, and the records from that page on. A notebook
    without page plans (older ones) has one plan for every page, as before."""
    planned = [p for p in pages if p.lesson_plan]
    if not planned:
        return nb.lesson_plan or "", _tutor_records(turns)
    start = max(planned, key=lambda p: p.page_number)
    return start.lesson_plan, _tutor_records(turns, {p.id for p in pages if p.page_number >= start.page_number})


def lessons_taught(pages) -> str:
    """The earlier lessons, for planning the next one: each planned page's lesson line and goal, and every page's summary."""
    lines = []
    for p in sorted(pages, key=lambda p: p.page_number):
        plan = [line for line in (p.lesson_plan or "").splitlines() if line.startswith(("LESSON:", "GOAL:"))]
        lines.append(f"Page {p.page_number}: {p.title or ''} | {' '.join(plan)} | {p.summary or ''}".strip(" |"))
    return "\n".join(lines)


def lesson_final(plan, records) -> dict:
    """The end-of-lesson check's state (engine/lesson_plan.final_check): which step to check next, then the final problem, then done."""
    n = len(path_titles(plan or ""))
    state = final_check(n, records)
    state["asked"] = final_check(n, records[:-1])["next"] if state["active"] and records else None   # what the last turn was told to ask
    return state


def lesson_path(plan, records, away: bool = False) -> list:
    """The learner's checklist: the plan's step titles (nothing else of the private plan), each with the level it has earned from what
    the tutor recorded (engine/lesson_plan.step_levels) and whether a surprise review of it is due."""
    titles = path_titles(plan or "")
    return [{"title": t, **lv} for t, lv in zip(titles, step_levels(len(titles), records, away))]


def _chat_turns_json(turns) -> list:
    """The conversation as the client shows it. A failed tutor turn carries `retry_turn_id`: the learner turn to send again."""
    out, last_user_id = [], None
    for t in turns:
        if t.status == "silent":      # only keeps the checklist records of a turn with no reply: nothing to show
            continue
        if t.role == "user":
            last_user_id = t.id
        row = {"id": t.id, "role": t.role, "content": t.content, "timestamp": t.timestamp.isoformat(), "status": t.status,
               "about_element_ids": t.about_element_ids, "tool_calls_made": t.tool_calls_made}
        if t.status == "failed":
            row["retry_turn_id"] = last_user_id
        out.append(row)
    return out


@app.get("/api/notebooks/{notebook_id}/export")
def export_notebook(notebook_id: str, session: SessionDep, download: bool = False,
                    print_view: bool = Query(False, alias="print")):
    """Print-ready HTML of the whole notebook (drawings + what the tutor said + conversation)."""
    from fastapi.responses import HTMLResponse
    from backend.export import build_notebook_html
    nb = session.get(Notebook, notebook_id)
    if not nb:
        raise HTTPException(status_code=404, detail="Notebook not found")
    pages = []
    for p in session.exec(select(Page).where(Page.notebook_id == notebook_id).order_by(Page.page_number)).all():
        events = session.exec(select(PageEvent).where(PageEvent.page_id == p.id).order_by(PageEvent.seq)).all()
        pages.append({
            "page_number": p.page_number, "title": p.title, "summary": p.summary, "current_svg": p.current_svg,
            # annotation events store JSON, not SVG: only real drawings carry narration worth listing
            "narrations": [(e.element_id, e.narration) for e in events
                           if e.kind == "draw" and e.narration and e.svg_fragment.lstrip().startswith("<")],
        })
    turns = [{"role": t.role, "content": t.content} for t in session.exec(
        select(ChatTurn).where(ChatTurn.notebook_id == notebook_id).order_by(ChatTurn.seq)).all()
        if t.role in ("user", "assistant") and t.status == "ok" and t.content.strip()]
    html = build_notebook_html(nb, pages, turns, print_on_load=print_view)
    headers = {}
    if download:
        safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", nb.title or nb.topic).strip("_") or "notebook"
        headers["Content-Disposition"] = f'attachment; filename="{safe}.html"'
    return HTMLResponse(html, headers=headers)


@app.delete("/api/notebooks/{notebook_id}")
def delete_notebook(notebook_id: str, session: SessionDep):
    nb = session.get(Notebook, notebook_id)
    if not nb:
        raise HTTPException(status_code=404, detail="Notebook not found")
    pages = session.exec(select(Page).where(Page.notebook_id == notebook_id)).all()
    for p in pages:
        events = session.exec(select(PageEvent).where(PageEvent.page_id == p.id)).all()
        for e in events:
            session.delete(e)
        session.delete(p)
    turns = session.exec(select(ChatTurn).where(ChatTurn.notebook_id == notebook_id)).all()
    for t in turns:
        session.delete(t)
    session.delete(nb)
    session.commit()
    shutil.rmtree(OUTPUT_DIR / notebook_id, ignore_errors=True)  # id matched a DB row, so it is a UUID
    logger.info(BackendEvent.NOTEBOOK_DELETED, f"Notebook deleted: {notebook_id}")
    return {"status": "deleted", "id": notebook_id}


@app.patch("/api/notebooks/{notebook_id}")
def update_notebook(notebook_id: str, req: UpdateNotebookRequest, session: SessionDep):
    nb = session.get(Notebook, notebook_id)
    if not nb:
        raise HTTPException(status_code=404, detail="Notebook not found")
    if req.topic is not None:
        nb.topic = req.topic.strip()
    if req.title is not None:
        nb.title = req.title.strip()
    session.add(nb)
    session.commit()
    session.refresh(nb)
    return {"id": nb.id, "topic": nb.topic, "title": nb.title}


# ---------------------------------------------------------------------------
# Page endpoints
# ---------------------------------------------------------------------------

@app.post("/api/notebooks/{notebook_id}/pages", status_code=201)
async def start_page(notebook_id: str, req: StartPageRequest, session: SessionDep):
    nb = session.get(Notebook, notebook_id)
    if not nb:
        raise HTTPException(status_code=404, detail="Notebook not found")

    # If the notebook currently only has an uninitialized active page (page 1, 0 elements, no title), reuse it
    existing_pages = session.exec(
        select(Page).where(Page.notebook_id == notebook_id)
    ).all()
    if len(existing_pages) == 1 and existing_pages[0].page_number == 1 and existing_pages[0].element_count == 0 and not existing_pages[0].title:
        p1 = existing_pages[0]
        if req.title:
            p1.title = req.title
        session.add(p1)
        session.commit()
        session.refresh(p1)
        await emit_notebook_event(notebook_id, SessionEvent.PAGE_STARTED, {
            "page_id": p1.id, "page_number": p1.page_number, "status": p1.status
        })
        return {"id": p1.id, "page_number": 1, "status": "active", "created_at": p1.created_at.isoformat()}

    # Cleanly auto-save any currently active pages in this notebook
    active_pages = session.exec(
        select(Page).where(Page.notebook_id == notebook_id, Page.status == "active")
    ).all()
    for ap in active_pages:
        ap.status = "saved"
        ap.updated_at = datetime.now(timezone.utc)
        session.add(ap)

    existing = session.exec(
        select(Page).where(Page.notebook_id == notebook_id).order_by(Page.page_number.desc())
    ).first()
    next_number = (existing.page_number + 1) if existing else 1

    page = Page(
        notebook_id=notebook_id,
        page_number=next_number,
        title=req.title,
        status="active"
    )
    session.add(page)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=409, detail="Another page was just created; retry")
    session.refresh(page)

    for ap in active_pages:
        await emit_notebook_event(notebook_id, SessionEvent.PAGE_SAVED, {"page_id": ap.id})
        await summarise_saved_page(engine, ap.id)          # one cheap model call per page that was just saved; best effort, never blocks the save
    logger.info(BackendEvent.PAGE_CREATED, f"Page {next_number} created for notebook {notebook_id}")
    await emit_notebook_event(notebook_id, SessionEvent.PAGE_STARTED, {
        "page_id": page.id, "page_number": page.page_number, "status": page.status
    })

    return {"id": page.id, "page_number": page.page_number,
            "status": page.status, "created_at": page.created_at.isoformat()}


@app.post("/api/notebooks/{notebook_id}/pages/{page_id}/save")
async def save_page(notebook_id: str, page_id: str, session: SessionDep, req: Optional[SavePageRequest] = None):
    page = session.get(Page, page_id)
    if not page or page.notebook_id != notebook_id:
        raise HTTPException(status_code=404, detail="Page not found")

    if req:
        if req.final_svg is not None:
            from engine.sanitiser import sanitize_svg
            page.current_svg = sanitize_svg(req.final_svg)
        if req.summary is not None:
            page.summary = req.summary
        # element_count is server-owned (incremented per draw event); the client value is ignored

    page.status = "saved"
    page.updated_at = datetime.now(timezone.utc)
    session.add(page)
    session.commit()
    session.refresh(page)

    logger.info(BackendEvent.PAGE_SAVED, f"Page {page_id} saved")
    await emit_notebook_event(notebook_id, SessionEvent.PAGE_SAVED, {"page_id": page.id})
    await summarise_saved_page(engine, page.id)           # one cheap model call; best effort: the page is saved already, a failure only leaves the summary empty

    return {"status": "saved", "page_id": page_id, "page_number": page.page_number}


@app.patch("/api/notebooks/{notebook_id}/pages/{page_id}")
def update_page(notebook_id: str, page_id: str, req: UpdatePageRequest, session: SessionDep):
    page = session.get(Page, page_id)
    if not page or page.notebook_id != notebook_id:
        raise HTTPException(status_code=404, detail="Page not found")
    if req.title is not None:
        page.title = req.title.strip()
    if req.summary is not None:
        page.summary = req.summary.strip()
    page.updated_at = datetime.now(timezone.utc)
    session.add(page)
    session.commit()
    session.refresh(page)
    return {"id": page.id, "title": page.title, "summary": page.summary}


@app.delete("/api/notebooks/{notebook_id}/pages/{page_id}")
def delete_page(notebook_id: str, page_id: str, session: SessionDep):
    page = session.get(Page, page_id)
    if not page or page.notebook_id != notebook_id:
        raise HTTPException(status_code=404, detail="Page not found")
    events = session.exec(select(PageEvent).where(PageEvent.page_id == page_id)).all()
    for e in events:
        session.delete(e)
    session.delete(page)
    session.commit()
    logger.info(BackendEvent.PAGE_DELETED, f"Page {page_id} deleted")
    return {"status": "deleted", "page_id": page_id}


@app.get("/api/notebooks/{notebook_id}/pages/{page_id}/events")
def get_page_events(notebook_id: str, page_id: str, session: SessionDep):
    """Returns all PageEvents for a page in seq order — used for replay."""
    page = session.get(Page, page_id)
    if not page or page.notebook_id != notebook_id:
        raise HTTPException(status_code=404, detail="Page not found")

    events = session.exec(
        select(PageEvent).where(PageEvent.page_id == page_id).order_by(PageEvent.seq)
    ).all()

    return {
        "page_id": page_id,
        "page_number": page.page_number,
        "status": page.status,
        "current_svg": page.current_svg,
        "final_svg": page.current_svg,
        "events": [
            {
                "seq": e.seq, "kind": e.kind,
                "element_id": e.element_id,
                "svg_fragment": e.svg_fragment,
                "narration": e.narration,
                "audio_path": e.audio_path,
                "audio_url": e.audio_path,
                "alignment_path": e.alignment_path,
                "alignment_url": e.alignment_path,
                "timestamp": e.timestamp.isoformat()
            } for e in events
        ]
    }


@app.post("/api/notebooks/{notebook_id}/pages/{page_id}/undo")
async def undo_last_drawing(notebook_id: str, page_id: str, session: SessionDep):
    """
    Removes the most recently drawn element together with everything that depends on it: later edits to it,
    annotations on it, and its audio files. The page's cached SVG and element count are recomputed from the
    remaining events, so replay, reload and export all agree.
    """
    page = session.get(Page, page_id)
    if not page or page.notebook_id != notebook_id:
        raise HTTPException(status_code=404, detail="Page not found")
    if page.status == "saved":
        raise HTTPException(status_code=400, detail="This page is saved and locked, so it can't be changed.")
    task = ACTIVE_AGENT_TASKS.get(notebook_id)
    if task and not task.done():
        raise HTTPException(status_code=409, detail="The tutor is still drawing. Try again in a moment.")

    events = session.exec(select(PageEvent).where(PageEvent.page_id == page_id).order_by(PageEvent.seq)).all()
    drawings = [e for e in events if is_drawing(e)]
    if not drawings:
        raise HTTPException(status_code=400, detail="There is nothing to undo on this page.")
    target = drawings[-1].element_id

    doomed = [e for e in events if e.element_id == target and e.kind in ("draw", "modify")]
    annotation_ids = []
    for e in events:
        if e.kind == "annotate" and target in annotation_target_ids(e):
            doomed.append(e)
            annotation_ids.append(e.element_id)
    doomed += [e for e in events if e.kind == "remove_annotation" and e.element_id in annotation_ids]

    # delete the audio / alignment files this drawing produced (only inside this page's own folder)
    page_dir = (OUTPUT_DIR / notebook_id / page_id).resolve()
    for e in doomed:
        for url in (e.audio_path, e.alignment_path):
            if url:
                f = (page_dir / Path(url).name).resolve()
                if f.parent == page_dir and f.is_file():
                    f.unlink()
    doomed_ids = {e.id for e in doomed}
    for e in doomed:
        session.delete(e)

    page.current_svg, page.element_count = rebuild_page_svg(e for e in events if e.id not in doomed_ids)
    page.canvas_coverage = round(compute_coverage(page.current_svg), 3)
    page.updated_at = datetime.now(timezone.utc)
    session.add(page)
    session.commit()

    await emit_notebook_event(notebook_id, SessionEvent.ELEMENT_REMOVED, {
        "page_id": page_id, "element_id": target, "annotation_ids": annotation_ids,
    })
    return {"status": "ok", "removed_element_id": target, "element_count": page.element_count}


@app.post("/api/notebooks/{notebook_id}/pages/{page_id}/annotate")
async def annotate_on_page(notebook_id: str, page_id: str, req: AnnotateElementRequest, session: SessionDep):
    page = session.get(Page, page_id)
    if not page or page.notebook_id != notebook_id:
        raise HTTPException(status_code=404, detail="Page not found")
    if page.status == "saved":
        raise HTTPException(status_code=400, detail="Page is saved and locked. Cannot annotate a saved page.")

    existing_events = session.exec(
        select(PageEvent).where(PageEvent.page_id == page.id)
    ).all()
    existing_element_ids = {e.element_id for e in existing_events if e.kind in ("draw", "modify")}

    async def _emit(event_type: str, payload: dict):
        await emit_notebook_event(notebook_id, event_type, payload)

    async def _persist(kind: str, element_id: str, svg_fragment: str,
                       narration: Optional[str] = None,
                       audio_path: Optional[str] = None,
                       alignment_path: Optional[str] = None,
                       old_svg_fragment: Optional[str] = None):
        append_event(engine, page.id, None,
                       kind=kind, element_id=element_id, svg_fragment=svg_fragment, old_svg_fragment=old_svg_fragment,
                       narration=narration, audio_path=audio_path, alignment_path=alignment_path)

    from engine.author import _handle_annotate_element
    res = await _handle_annotate_element(
        notebook_id=notebook_id,
        page_id=page_id,
        page_status=page.status,
        annotation_id=req.annotation_id,
        style=req.style,
        target_element_id=req.target_element_id,
        narration=req.narration or f"Focus on {req.target_element_id}",
        from_element_id=req.from_element_id,
        color=req.color,
        note=req.note,
        lifetime=req.lifetime,
        duration_ms=req.duration_ms,
        existing_element_ids=existing_element_ids,
        emit_fn=_emit,
        persist_fn=_persist,
    )
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("detail"))
    return res


@app.post("/api/notebooks/{notebook_id}/pages/{page_id}/remove-annotation")
async def remove_annotation_on_page(notebook_id: str, page_id: str, req: RemoveAnnotationRequest, session: SessionDep):
    page = session.get(Page, page_id)
    if not page or page.notebook_id != notebook_id:
        raise HTTPException(status_code=404, detail="Page not found")
    if page.status == "saved":
        raise HTTPException(status_code=400, detail="Page is saved and locked. Cannot remove annotations from a saved page.")

    async def _emit(event_type: str, payload: dict):
        await emit_notebook_event(notebook_id, event_type, payload)

    async def _persist(kind: str, element_id: str, svg_fragment: str,
                       narration: Optional[str] = None,
                       audio_path: Optional[str] = None,
                       alignment_path: Optional[str] = None,
                       old_svg_fragment: Optional[str] = None):
        append_event(engine, page.id, None,
                       kind=kind, element_id=element_id, svg_fragment=svg_fragment, old_svg_fragment=old_svg_fragment,
                       narration=narration, audio_path=audio_path, alignment_path=alignment_path)

    from engine.author import _handle_remove_annotation
    res = await _handle_remove_annotation(
        page_id=page_id,
        page_status=page.status,
        annotation_id=req.annotation_id,
        emit_fn=_emit,
        persist_fn=_persist,
    )
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("detail"))
    return res


# ---------------------------------------------------------------------------
# Chat endpoint — triggers WhiteboardAuthor
# ---------------------------------------------------------------------------

@app.post("/api/notebooks/{notebook_id}/chat")
async def chat(notebook_id: str, req: ChatRequest, session: SessionDep):
    """
    Receives a learner message and runs the WhiteboardAuthor agent.
    Returns the assistant's final text response.
    The WhiteboardAuthor emits WS events for each draw action during its run.
    """
    nb = session.get(Notebook, notebook_id)
    if not nb:
        raise HTTPException(status_code=404, detail="Notebook not found")
    CHAT_LIMITER.prune()
    wait = CHAT_LIMITER.check(notebook_id)
    if wait:
        raise HTTPException(status_code=429, detail=TOO_FAST, headers={"Retry-After": str(wait)})

    # "Try again": only the learner's latest question, and only while it has no answer
    retry_turn = None
    if req.retry_turn_id:
        retry_turn = session.get(ChatTurn, req.retry_turn_id)
        if not retry_turn or retry_turn.notebook_id != notebook_id or retry_turn.role != "user":
            raise HTTPException(status_code=404, detail="That question was not found.")
        later = session.exec(select(ChatTurn).where(
            ChatTurn.notebook_id == notebook_id, ChatTurn.seq > retry_turn.seq,
            ((ChatTurn.role == "user") | ((ChatTurn.role == "assistant") & (ChatTurn.status == "ok"))))).first()
        if later:
            raise HTTPException(status_code=409, detail="That question already has an answer, or a newer question was asked.")
    message_text = retry_turn.content if retry_turn else req.message

    # Resolve target page
    if req.page_id:
        page = session.get(Page, req.page_id)
        if not page or page.notebook_id != notebook_id:
            raise HTTPException(status_code=404, detail="Page not found")
        # A learner may ask about a saved lesson board: the tutor answers, and any new block goes to a fresh page (engine/author.add_block).
    else:
        page = session.exec(
            select(Page)
            .where(Page.notebook_id == notebook_id)
            .where(Page.status == "active")
            .order_by(Page.page_number.desc())
        ).first()
        if not page:
            # Auto-create first page
            existing = session.exec(
                select(Page).where(Page.notebook_id == notebook_id).order_by(Page.page_number.desc())
            ).first()
            next_number = (existing.page_number + 1) if existing else 1
            page = Page(notebook_id=notebook_id, page_number=next_number, status="active")
            session.add(page)
            session.commit()
            session.refresh(page)

    # Collect existing element IDs across ALL events (draw + modify)
    all_existing_events = session.exec(
        select(PageEvent).where(PageEvent.page_id == page.id)
    ).all()
    existing_element_ids = {e.element_id for e in all_existing_events if e.kind in ("draw", "modify")}
    if board_blocks(page.current_svg):   # a lesson board: the learner may point at a node or group inside a step
        existing_element_ids |= set(SCENE_ID_RE.findall(page.current_svg))

    # Strictly validate selected_element_ids against authoritative elements on this page
    valid_selected_ids = []
    pointed_at = (retry_turn.about_element_ids if retry_turn else req.selected_element_ids) or []
    if pointed_at:
        valid_selected_ids = [eid for eid in pointed_at if eid in existing_element_ids]

    allowed_gestures = {"circle", "underline", "point", "scribble"}
    gesture = req.gesture_type if req.gesture_type in allowed_gestures else "circle"

    augmented_message = message_text
    if valid_selected_ids:
        def _friendly_title(eid: str) -> str:
            eid = re.sub(r"^b\d+_(?!s\d+$)", "", eid)   # a lesson-board node: 'b2_load_balancer' reads 'Load Balancer'
            return eid.replace("_", " ").replace("-", " ").title()

        score_desc = f" ({req.match_score:.2f} match)" if req.match_score is not None else ""
        if len(valid_selected_ids) == 2:
            t1 = f"'{valid_selected_ids[0]}' ({_friendly_title(valid_selected_ids[0])})"
            t2 = f"'{valid_selected_ids[1]}' ({_friendly_title(valid_selected_ids[1])})"
            spatial_context = f"[Learner {gesture}d relationship between diagram elements: {t1} and {t2}{score_desc}]"
        else:
            targets = ", ".join(f"'{eid}' ({_friendly_title(eid)})" for eid in valid_selected_ids)
            spatial_context = f"[Learner {gesture}d diagram element(s): {targets}{score_desc}]"

        augmented_message = f"{spatial_context}\nLearner Question: {message_text}"
        logger.info(
            BackendEvent.CHAT_RECEIVED,
            f"Spatial grounding attached for page {page.id}: {valid_selected_ids} (gesture: {gesture}, relationship={len(valid_selected_ids) == 2})"
        )

    # A question asked on a saved lesson board (pointing included, checked above against that board) is answered on the notebook's
    # active board, so new blocks continue the current lesson. Drawing from the saved board would have opened a page, and opening a
    # page saves the active one: asking about an old board locked the current lesson (code review). With no active board the tutor
    # opens one itself (engine/author.add_block).
    if page.status == "saved":
        current = session.exec(select(Page).where(Page.notebook_id == notebook_id, Page.status == "active")
                               .order_by(Page.page_number.desc())).first()
        if current:
            page = current
            existing_element_ids = set(SCENE_ID_RE.findall(page.current_svg or ""))

    # Build page state
    from engine.validator import extract_element_bboxes, summarize_spatial_layout
    occupied = extract_element_bboxes(page.current_svg)
    page_state = {
        "current_svg": page.current_svg,
        "element_count": page.element_count,
        "notebook_id": notebook_id,
        "page_id": page.id,
        "page_number": page.page_number,
        "summary": page.summary or "Blank page — nothing drawn yet.",
        "occupied_regions": occupied,
        "available_space": summarize_spatial_layout(occupied),
    }

    # Build prior pages summary
    all_pages = session.exec(
        select(Page)
        .where(Page.notebook_id == notebook_id)
        .where(Page.id != page.id)
        .order_by(Page.page_number)
    ).all()
    prior_summary = prior_pages_summary(all_pages)

    # Build chat history (last 15 turns the tutor can read). Failed turns (a notice that the model was unreachable) are not part of the conversation and
    # do not use up a slot; the learner's unanswered question stays, so the next answer can cover it. Only those rows are read, however long the notebook is.
    history_query = select(ChatTurn).where(ChatTurn.notebook_id == notebook_id, ChatTurn.status == "ok",
                                           ~((ChatTurn.role == "assistant") & (func.trim(ChatTurn.content) == "")))      # an empty tutor turn (old notebooks) is never sent
    if retry_turn:
        history_query = history_query.where(ChatTurn.seq < retry_turn.seq)         # the retried question is sent as the new message, not twice
    recent_turns = session.exec(history_query.order_by(ChatTurn.seq.desc()).limit(HISTORY_TURNS)).all()
    history = [{"role": t.role, "content": t.content} for t in reversed(recent_turns)]
    away_for = time_away(recent_turns[0].timestamp) if recent_turns and not retry_turn else ""
    logger.info(BackendEvent.CONTEXT_BUILT, f"Context for the tutor: {len(all_pages)} earlier page(s), {summaries_in_context(all_pages)} with a summary, {len(history)} history turn(s)",
                data={"prior_pages": len(all_pages), "with_summary": summaries_in_context(all_pages), "history_turns": len(history),
                      "summaries_off": os.getenv("LP_TEST_SUMMARIES_OFF") == "1", "history_limit": HISTORY_TURNS})

    if retry_turn:
        # The earlier failed answer to this question is replaced by this attempt (the learner's turn stays as it is, once)
        user_turn = retry_turn
        for old in session.exec(select(ChatTurn).where(ChatTurn.notebook_id == notebook_id, ChatTurn.role == "assistant",
                                                       ChatTurn.status == "failed", ChatTurn.seq > retry_turn.seq)).all():
            session.delete(old)
        session.commit()
    else:
        # Persist learner message as a ChatTurn
        user_turn_seq = (session.exec(select(func.max(ChatTurn.seq)).where(ChatTurn.notebook_id == notebook_id)).one() or 0) + 1
        user_turn = ChatTurn(
            notebook_id=notebook_id,
            page_id=page.id,
            seq=user_turn_seq,
            role="user",
            content=req.message,
            about_element_ids=valid_selected_ids or None,       # "ask about a drawing": which drawings the question is about
        )
        session.add(user_turn)
        session.commit()

        # Emit learner message via WS so frontend shows it immediately
        await emit_notebook_event(notebook_id, SessionEvent.CHAT_TURN, {
            "role": "user", "content": req.message, "page_id": page.id
        })
    user_turn_id = user_turn.id

    # Scene mode: the first learning question gets a private lesson plan (engine/lesson_plan.py), written WHILE the tutor gives its first
    # answer and used from the next turn: written first, it was 8 of the 12 s before anything appeared (the first answer's main gain from
    # it, answering the whole question, is in the tutor's own rules). Saved when this turn ends.
    # The first plan also sets the course (goal and roadmap); each new page the tutor starts gets the next lesson's plan (_plan_next_lesson).
    plan_task = asyncio.create_task(write_plan(nb.topic, message_text)) if not nb.lesson_plan else None

    # -----------------------------------------------------------------------
    # Closures for emit and persist passed into the agent
    # -----------------------------------------------------------------------

    active = {"page_id": page.id}  # the agent may switch pages mid-turn (start_new_page)

    async def _emit(event_type: str, payload: dict):
        await emit_notebook_event(notebook_id, event_type, payload)

    async def _persist(kind: str, element_id: str, svg_fragment: str,
                       narration: Optional[str] = None,
                       audio_path: Optional[str] = None,
                       alignment_path: Optional[str] = None,
                       old_svg_fragment: Optional[str] = None,
                       block: Optional[dict] = None):
        def apply(pg):
            # Update page composite SVG and element count
            if kind == "draw":
                pg.current_svg = (pg.current_svg or "") + "\n" + svg_fragment
                pg.element_count += 1
            elif kind == "modify":
                # Replace old element in composite SVG
                if pg.current_svg and old_svg_fragment:
                    pg.current_svg = pg.current_svg.replace(old_svg_fragment, svg_fragment, 1)
        append_event(engine, active["page_id"], apply,       # None when the page was locked mid-session
                     kind=kind, element_id=element_id, svg_fragment=svg_fragment, old_svg_fragment=old_svg_fragment,
                     narration=narration, audio_path=audio_path, alignment_path=alignment_path, block=block)

    # -----------------------------------------------------------------------

    async def _new_page(title: Optional[str]) -> str:
        with Session(engine) as db:
            created = await start_page(notebook_id, StartPageRequest(title=title), db)
        active["page_id"] = created["id"]
        return created["id"]

    async def _plan_next_lesson() -> str:
        """start_new_page in a notebook with a course: the new page gets the next lesson's plan (the tutor waits for it), or "" to go on."""
        if not nb.course:
            return ""
        with Session(engine) as db:
            pages = db.exec(select(Page).where(Page.notebook_id == notebook_id, Page.id != active["page_id"])).all()
        plan = await write_next_plan(nb.course, lessons_taught(pages), message_text)
        if plan:
            with Session(engine) as db:
                new_page = db.get(Page, active["page_id"])
                if new_page:
                    new_page.lesson_plan = plan
                    lesson = re.match(r"LESSON:\s*(?:\d+[.):]?\s*)?(.+)", plan)
                    if lesson:   # the page list names the lesson, not the title the tutor guessed before it had the plan (live)
                        new_page.title = lesson.group(1).strip()[:100]
                    db.add(new_page)
                    db.commit()
        return plan

    # Run the agent (with live barge-in task tracking & cancellation)
    # -----------------------------------------------------------------------
    prev_task = ACTIVE_AGENT_TASKS.get(notebook_id)
    if prev_task and not prev_task.done():
        logger.info(f"Barge-in: Cancelling existing agent task for notebook {notebook_id}")
        prev_task.cancel()
        try:
            await prev_task
        except (asyncio.CancelledError, Exception):
            pass

    tool_log: list = []                                       # filled by the agent: one record per tool call of this turn
    planned = nb.lesson_plan
    past = session.exec(select(ChatTurn).where(ChatTurn.notebook_id == notebook_id)).all() if planned else []
    plan_now, records = current_lesson(nb, session.exec(select(Page).where(Page.notebook_id == notebook_id)).all(), past) if planned else ("", [])

    async def _run_agent_wrapper():
        return await run_whiteboard_author(
            notebook_id=notebook_id,
            page_id=page.id,
            page_status=page.status,
            learner_message=augmented_message,
            chat_history=history,
            page_state=page_state,
            prior_pages_summary=prior_summary,
            lesson_plan=plan_now,
            course=nb.course or "",
            away_for=away_for,
            lesson_path=lesson_path(plan_now, records, bool(away_for)) if planned else None,
            lesson_final=lesson_final(plan_now, records) if planned else None,
            existing_element_ids=existing_element_ids,
            emit_fn=_emit,
            persist_fn=_persist,
            new_page_fn=_new_page,
            plan_page_fn=_plan_next_lesson,
            tool_log=tool_log,
        )

    def keep_records():
        """A turn with no reply to store (it only drew, or the learner interrupted it) still keeps what the tutor recorded: a hidden tutor
        row (status "silent") that the checklist counts and the conversation, chat panel, summaries and export skip. Before this, those
        records were lost (architecture review, 2026-11-16)."""
        if not any(r.get("tool") == "record_step" for r in tool_log):
            return
        with Session(engine) as db:
            last = db.exec(select(func.max(ChatTurn.seq)).where(ChatTurn.notebook_id == notebook_id)).one() or 0
            db.add(ChatTurn(notebook_id=notebook_id, page_id=active["page_id"], seq=last + 1, role="assistant", content="",
                            tool_calls_made=tool_log, status="silent"))
            db.commit()

    current_task = asyncio.create_task(_run_agent_wrapper())
    ACTIVE_AGENT_TASKS[notebook_id] = current_task

    async def fail(status: int, code: str, text: str, exc: Exception):
        """The turn has no answer: keep it as a failed tutor turn (shown with a retry button, never read by the tutor) and answer with a typed error."""
        logger.error(BackendEvent.CHAT_FAILED, f"Chat turn failed ({code}): {type(exc).__name__}: {exc}",
                     data={"error": code, "exception": f"{type(exc).__name__}: {exc}"[:300], "turn_id": user_turn_id}, exc_info=True)
        with Session(engine) as db:
            last = db.exec(select(func.max(ChatTurn.seq)).where(ChatTurn.notebook_id == notebook_id)).one() or 0
            db.add(ChatTurn(notebook_id=notebook_id, page_id=active["page_id"], seq=last + 1, role="assistant", content=text,
                            tool_calls_made=tool_log, status="failed"))
            db.commit()
        await emit_notebook_event(notebook_id, SessionEvent.CHAT_TURN, {
            "role": "assistant", "content": text, "page_id": active["page_id"], "status": "failed", "retry_turn_id": user_turn_id})
        return JSONResponse(status_code=status, content={"error": code, "retryable": True, "turn_id": user_turn_id, "detail": text})

    try:
        response_text = await current_task
    except asyncio.CancelledError:
        logger.info(f"Agent turn cancelled via barge-in for notebook {notebook_id}")
        keep_records()
        return {"response": "[Interrupted by learner]", "page_id": page.id, "interrupted": True}
    except ModelUnreachable as e:
        return await fail(503, "model_unreachable", MODEL_UNREACHABLE_MESSAGE, e)
    except EmptyReply as e:
        return await fail(503, "empty_reply", EMPTY_REPLY_MESSAGE, e)
    except Exception as e:                                    # anything else that broke the turn: the learner still gets an answer they can retry
        if not model_configured():
            return await fail(503, "model_not_configured", MODEL_NOT_CONFIGURED_MESSAGE, e)
        return await fail(500, "turn_failed", "Something went wrong while the tutor was working on that. Please try again.", e)
    finally:
        if ACTIVE_AGENT_TASKS.get(notebook_id) is current_task:
            ACTIVE_AGENT_TASKS.pop(notebook_id, None)
        if plan_task is not None and (plan := await plan_task):   # write_plan never raises; "" = no plan (greeting or failure)
            course, plan = split_course(plan)
            with Session(engine) as db:
                fresh = db.get(Notebook, notebook_id)
                if fresh and not fresh.lesson_plan:
                    fresh.lesson_plan, fresh.course = plan, course or None
                    db.add(fresh)
                    first_page = db.get(Page, page.id)
                    if first_page and course:
                        first_page.lesson_plan = plan
                        db.add(first_page)
                    db.commit()
            if path_titles(plan):   # this first answer gave the short answer to the whole question, which is step 1 (live: never
                # recorded, because the plan did not exist yet, so the next page taught step 1 again)
                tool_log.append({"tool": "record_step", "status": "ok", "iteration": 0, "element_id": "1", "event": "taught", "page_id": page.id})

    # Strip any [[MARK:...]] tokens from assistant response before persisting and emitting
    response_text = strip_markers(response_text).strip()
    if not response_text:
        # The model wrote nothing after drawing or annotating (an empty reply with nothing drawn raised EmptyReply above): the board is the answer. No empty
        # tutor turn is stored or sent, so no empty bubble and no wasted history slot; the empty_reply event in the log has the details.
        keep_records()
        return {"response": "", "page_id": active["page_id"]}

    # Persist assistant response
    with Session(engine) as db:
        asst_seq = (db.exec(select(func.max(ChatTurn.seq)).where(ChatTurn.notebook_id == notebook_id)).one() or 0) + 1
        asst_turn = ChatTurn(
            notebook_id=notebook_id,
            page_id=active["page_id"],
            seq=asst_seq,
            role="assistant",
            content=response_text,
            tool_calls_made=tool_log,                         # [] for a reply that drew nothing
        )
        db.add(asst_turn)
        db.commit()

    await emit_notebook_event(notebook_id, SessionEvent.CHAT_TURN, {
        "role": "assistant", "content": response_text, "page_id": active["page_id"]
    })

    return {"response": response_text, "page_id": active["page_id"]}


@app.post("/api/notebooks/{notebook_id}/interrupt")
async def interrupt_agent(notebook_id: str):
    """
    Barge-in interruption endpoint.
    Cancels any active agent generation and emits an interruption event.
    """
    task = ACTIVE_AGENT_TASKS.get(notebook_id)
    was_cancelled = False
    if task and not task.done():
        task.cancel()
        was_cancelled = True
        logger.info(f"Barge-in API: Cancelled active task for notebook {notebook_id}")

    # Emit barge-in event over WebSocket
    await emit_notebook_event(notebook_id, SessionEvent.BARGE_IN, {
        "interrupted": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    return {
        "status": "interrupted",
        "was_active": was_cancelled,
        "notebook_id": notebook_id,
    }


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------

@app.websocket("/api/ws/notebooks/{notebook_id}")
async def websocket_notebook_events(websocket: WebSocket, notebook_id: str):
    if not _ws_origin_ok(websocket):
        await websocket.close(code=1008)
        return
    await manager.connect(notebook_id, websocket)
    try:
        while True:
            _ = await websocket.receive_text()  # keep alive; client sends no commands yet
    except WebSocketDisconnect:
        manager.disconnect(notebook_id, websocket)
    except Exception:
        manager.disconnect(notebook_id, websocket)


# ---------------------------------------------------------------------------
# Voice Ingestion: Deepgram Nova-3 REST & Streaming WebSocket
# ---------------------------------------------------------------------------

@app.post("/api/transcribe-voice")
async def transcribe_voice(request: Request):
    """
    Transcribe audio blob using Deepgram Nova-3 REST API.
    Accepts raw binary audio (audio/webm, audio/wav, audio/mp4) or multipart upload.
    """
    wait = VOICE_LIMITER.check(request.client.host if request.client else "unknown")
    if wait:
        raise HTTPException(status_code=429, detail=TOO_FAST, headers={"Retry-After": str(wait)})
    deepgram_key = os.getenv("DEEPGRAM_API_KEY")
    if not deepgram_key:
        raise HTTPException(status_code=503, detail="DEEPGRAM_API_KEY is not configured on server")

    raw_content_type = request.headers.get("content-type", "audio/webm")
    content_type = raw_content_type.split(";")[0].strip() or "audio/webm"
    audio_data = await request.body()
    if not audio_data:
        raise HTTPException(status_code=400, detail="Empty audio payload")
    if len(audio_data) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Audio too large")

    headers = {
        "Authorization": f"Token {deepgram_key}",
        "Content-Type": content_type,
    }
    params = {
        "model": "nova-3",
        "smart_format": "true",
        "punctuate": "true",
    }

    try:
        resp = await asyncio.to_thread(
            requests.post,
            "https://api.deepgram.com/v1/listen",
            headers=headers,
            params=params,
            data=audio_data,
            timeout=15.0,
        )
        if resp.status_code != 200:
            logger.error(f"Deepgram transcription error {resp.status_code}: {resp.text}")
            raise HTTPException(status_code=502, detail="Transcription service error")

        res_json = resp.json()
        transcript = ""
        confidence = 0.0
        channels = res_json.get("results", {}).get("channels", [])
        if channels:
            alts = channels[0].get("alternatives", [])
            if alts:
                transcript = alts[0].get("transcript", "")
                confidence = alts[0].get("confidence", 0.0)

        return {
            "status": "ok",
            "transcript": transcript.strip(),
            "confidence": confidence,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in transcribe_voice: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Transcription failed")


@app.websocket("/api/ws/voice/{notebook_id}")
async def websocket_voice_streaming(websocket: WebSocket, notebook_id: str):
    """
    Live streaming WebSocket relay between browser microphone and Deepgram Nova-3.
    Keeps DEEPGRAM_API_KEY secure on backend.
    Relays binary audio packets upstream; relays interim & final transcripts downstream.
    """
    deepgram_key = os.getenv("DEEPGRAM_API_KEY")
    if not deepgram_key or not _ws_origin_ok(websocket) or VOICE_LIMITER.check(
            websocket.client.host if websocket.client else "unknown"):
        await websocket.close(code=1008, reason="Voice unavailable")
        return

    await websocket.accept()

    # Deepgram Live Streaming WebSocket URL
    # Note: omit encoding and sample_rate when streaming webm/opus containers
    # vad_events -> SpeechStarted, utterance_end_ms -> UtteranceEnd: the client's barge-in and hands-free send rely on both
    dg_url = ("wss://api.deepgram.com/v1/listen?model=nova-3&smart_format=true&interim_results=true"
              "&endpointing=300&vad_events=true&utterance_end_ms=1000")
    headers = {"Authorization": f"Token {deepgram_key}"}

    try:
        async with websockets.connect(dg_url, additional_headers=headers) as dg_ws:
            async def client_to_deepgram():
                sent = 0
                try:
                    while True:
                        message = await websocket.receive()
                        if "bytes" in message and message["bytes"]:
                            sent += len(message["bytes"])
                            if sent > MAX_VOICE_STREAM_BYTES:
                                await dg_ws.send(json.dumps({"type": "CloseStream"}))
                                break
                            await dg_ws.send(message["bytes"])
                        elif "text" in message and message["text"]:
                            text_data = message["text"]
                            try:
                                parsed = json.loads(text_data)
                                if parsed.get("type") in ("CloseStream", "stop"):
                                    await dg_ws.send(json.dumps({"type": "CloseStream"}))
                                    break
                            except Exception:
                                pass
                except (WebSocketDisconnect, asyncio.CancelledError):
                    try:
                        await dg_ws.send(json.dumps({"type": "CloseStream"}))
                    except Exception:
                        pass
                except Exception as ex:
                    logger.debug(f"client_to_deepgram stream ended: {ex}")

            async def deepgram_to_client():
                try:
                    async for dg_msg in dg_ws:
                        if isinstance(dg_msg, str):
                            await websocket.send_text(dg_msg)
                except (WebSocketDisconnect, asyncio.CancelledError):
                    pass
                except Exception as ex:
                    logger.debug(f"deepgram_to_client stream ended: {ex}")

            # Run both directions until either side ends (or the session-length cap), then tidy up.
            up = asyncio.create_task(client_to_deepgram())
            down = asyncio.create_task(deepgram_to_client())
            done, _ = await asyncio.wait({up, down}, timeout=MAX_VOICE_SECONDS, return_when=asyncio.FIRST_COMPLETED)
            if up in done:  # the learner pressed Done: give Deepgram a moment to flush the last words
                await asyncio.wait({down}, timeout=3)
            for t in (up, down):
                t.cancel()
            await asyncio.gather(up, down, return_exceptions=True)
        try:
            await websocket.close(code=1000, reason="Voice session ended")
        except Exception:
            pass  # the browser already hung up
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"Error in voice websocket relay: {e}")
        try:
            await websocket.close(code=1011, reason="Relay error")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

class ClientEvent(BaseModel):
    kind: str = Field(max_length=40)                       # error | unhandledrejection | console.error | console.warn | http_error | network_error
    message: str = Field(default="", max_length=2000)
    source: Optional[str] = Field(default=None, max_length=300)
    stack: Optional[str] = Field(default=None, max_length=3000)
    page_url: Optional[str] = Field(default=None, max_length=500)
    notebook_id: Optional[str] = Field(default=None, max_length=64)
    status: Optional[int] = None
    ts: Optional[str] = Field(default=None, max_length=40)            # the browser's own clock, ISO


class ClientLogRequest(BaseModel):
    events: List[ClientEvent] = Field(max_length=20)


@app.post("/api/client-log", status_code=204)
def client_log(req: ClientLogRequest, request: Request):
    """Errors the browser saw, written to the structured log next to the server's own events (so one file tells the whole story of a session)."""
    if CLIENT_LOG_LIMITER.check(request.client.host if request.client else "unknown"):
        return                                                   # too many: drop silently, the reporter must never cause trouble of its own
    for e in req.events:
        logger.warn(BackendEvent.CLIENT_ERROR, f"[browser {e.kind}] {no_control_chars(e.message)[:300]}",
                    data={**{k: (no_control_chars(v) if isinstance(v, str) else v) for k, v in e.model_dump().items() if v is not None}},
                    session_id=e.notebook_id)


@app.get("/health")
def health():
    return {"status": "ok", "service": "learning_platform"}

