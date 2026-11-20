"""
backend/page_summary.py
Writes pages.summary for a page that has just been saved (engine/summary.py builds the call). Best effort by design: the page is already saved when this
runs, so a failure (no key, timeout, an error from the model) leaves the summary empty and is logged, and never blocks or undoes the save.
"""
import asyncio
from typing import Optional

from sqlmodel import Session, select

from core.events import BackendEvent
from core.log import get_logger
from engine.markers import strip_markers
from engine.summary import SUMMARY_TIMEOUT, build_messages, summarise

logger = get_logger("backend")

# Tests replace this (the suite never calls the real model for a summary); None means the cheap Azure deployment.
CLIENT_FACTORY = None


def _transcript(db: Session, page):
    """The page's own turns, as (who, element id, text) in page order, and whether it has a drawing.

    Which turns belong to a page: a tutor turn belongs to the page it ENDED on (chat_turns.page_id); a learner turn belongs to the page of the tutor turn that
    ANSWERS it, not to the page that was open when it was asked. The difference matters when the answer opens a new page: that question is asked on page 1,
    the page is saved in the middle of the turn (this summary runs then), and the answer is drawn on page 2. Page 1's summary must not carry that question
    (it used to, and read "the learner asked for X, which was not yet addressed" about something the next page answers). A learner turn with no answer yet
    (the turn in flight) belongs to no page. Failed tutor turns are skipped, so their question goes with the next ok answer. What the tutor said while
    drawing comes from the page's own draw events."""
    from backend.models import ChatTurn, PageEvent
    from backend.page_state import is_drawing
    items, pending = [], []
    turns = db.exec(select(ChatTurn).where(ChatTurn.notebook_id == page.notebook_id, ChatTurn.role.in_(("user", "assistant")), ChatTurn.status == "ok")
                    .order_by(ChatTurn.seq)).all()
    for t in turns:
        if t.role == "user":
            pending.append(("learner", "", t.content))
            continue
        if t.page_id == page.id:
            items.extend(pending)
            items.append(("tutor", "", t.content))
        pending = []                                         # answered here or on another page: either way these questions are not left for the next answer
    events = db.exec(select(PageEvent).where(PageEvent.page_id == page.id).order_by(PageEvent.seq)).all()
    for e in events:
        if is_drawing(e) and e.narration:
            items.append(("drawing", e.element_id, strip_markers(e.narration)))
    return items, any(is_drawing(e) for e in events)


async def summarise_saved_page(engine, page_id: str, *, client_factory=None, deployment: Optional[str] = None) -> Optional[str]:
    """Write the summary of a SAVED page. Returns the summary, or None when nothing was written (unsaved or blank page, a summary already there,
    or the model call failed)."""
    from backend.models import Page
    with Session(engine) as db:
        page = db.get(Page, page_id)
        if page is None or page.status != "saved" or (page.summary or "").strip():
            return None                                     # never on an unsaved page; never over a summary the client sent
        items, has_drawing = _transcript(db, page)
        if not has_drawing and not items:
            return None                                     # a blank page has nothing to summarise
        title = page.title or ""
    try:
        client_factory = client_factory or CLIENT_FACTORY
        if client_factory is None:
            from engine.author import AZURE_OPENAI_DEPLOYMENT, get_azure_client
            client_factory = get_azure_client
        if deployment is None:
            from engine.author import AZURE_OPENAI_DEPLOYMENT
            deployment = AZURE_OPENAI_DEPLOYMENT                                                         # the cheap deployment, not the author's
        messages = build_messages(title, items)
        text = await asyncio.wait_for(asyncio.to_thread(lambda: summarise(client_factory(), deployment, messages)), timeout=SUMMARY_TIMEOUT + 3)
        if not text:
            raise ValueError("the model returned an empty summary")
    except Exception as e:                                  # the save has already happened: say so and move on
        logger.warn(BackendEvent.PAGE_SUMMARY_FAILED, f"Summary of page {page_id} failed ({type(e).__name__}: {e}); the page is saved without one",
                    data={"page_id": page_id, "error": f"{type(e).__name__}: {e}"[:200]})
        return None
    with Session(engine) as db:
        page = db.get(Page, page_id)
        if page is None or page.status != "saved" or (page.summary or "").strip():
            return None
        page.summary = text
        db.add(page)
        db.commit()
    logger.info(BackendEvent.PAGE_SUMMARISED, f"Summary written for page {page_id}", data={"page_id": page_id, "chars": len(text), "summary": text})
    return text
