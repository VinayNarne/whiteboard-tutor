"""
backend/event_store.py
The one place a PageEvent is written. The seq of an event is "the next number of its page", taken INSIDE the transaction that inserts it, and
(page_id, seq) is unique in the database (migration 0003). If two writers take the same number (a barge-in: a new learner message arrives while
the cancelled turn is still persisting), the database refuses the second insert and the write is simply tried again with the new maximum. On Postgres the page row is locked while
an event is written, so writers of one page take turns and the retry is only a safety net.
"""
import threading
from contextlib import nullcontext
from datetime import datetime, timezone
from typing import Callable, Optional

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from backend.models import Page, PageEvent
from engine.validator import compute_coverage

ATTEMPTS = 5
# SQLite has no row lock, so concurrent writers of one page can all read the same max seq and exhaust their retries. Take turns in-process instead.
# ponytail: one lock for all SQLite writers (fine for one process; Postgres uses the page row lock and takes no Python lock).
_sqlite_lock = threading.Lock()


def append_event(engine, page_id: str, apply_to_page: Optional[Callable[[Page], None]] = None, **fields) -> Optional[int]:
    """Insert one event at the next seq of `page_id` and let `apply_to_page(page)` update the page's cached values in the same transaction.
    Returns the seq, or None if the page does not exist or is already saved (a locked page takes no events)."""
    lock = _sqlite_lock if engine.dialect.name == "sqlite" else nullcontext()
    for _ in range(ATTEMPTS):
        with lock, Session(engine) as db:
            # Postgres: writers of one page take turns (FOR NO KEY UPDATE; foreign-key checks on the page row are not blocked). SQLite serialises writes itself.
            pg = db.get(Page, page_id, with_for_update={"key_share": True})
            if not pg or pg.status == "saved":
                return None
            seq = (db.exec(select(func.max(PageEvent.seq)).where(PageEvent.page_id == page_id)).one() or 0) + 1
            db.add(PageEvent(page_id=page_id, seq=seq, **fields))
            if apply_to_page:
                apply_to_page(pg)
            if fields.get("kind") in ("draw", "modify"):
                pg.canvas_coverage = round(compute_coverage(pg.current_svg), 3)      # the page's cached fill, the same number the density check logs
            pg.updated_at = datetime.now(timezone.utc)
            db.add(pg)
            try:
                db.commit()
                return seq
            except IntegrityError:
                db.rollback()                 # someone else took this seq: read the maximum again
    raise RuntimeError(f"could not find a free seq for page {page_id} after {ATTEMPTS} attempts")
