"""Put a drawing on a page without a model: the append-only event log and the page's current_svg, as a scene block's step elements leave them.
(The old POST /pages/{id}/draw and /modify endpoints are gone; tests that need a page with content seed it here.)"""
import sys
from pathlib import Path
from types import SimpleNamespace

from sqlmodel import Session, select

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.event_store import append_event
from backend.models import PageEvent

OK = SimpleNamespace(status_code=200, text="", json=lambda: {"status": "ok"})


def draw(engine, page_id, element_id, svg_fragment, narration=None, nb=None):
    """With `nb` (the notebook id) the element also gets small audio and alignment files, named as the tutor's are."""
    audio = alignment = None
    if nb:
        from engine.author import OUTPUT_DIR
        d = OUTPUT_DIR / nb / page_id
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{element_id}_audio.mp3").write_bytes(b"mp3")
        (d / f"{element_id}_alignment.json").write_text("{}", encoding="utf-8")
        audio, alignment = (f"/static/notebooks/{nb}/{page_id}/{element_id}_{n}" for n in ("audio.mp3", "alignment.json"))

    def apply(pg):
        pg.current_svg = (pg.current_svg or "") + "\n" + svg_fragment
        pg.element_count += 1
    append_event(engine, page_id, apply, kind="draw", element_id=element_id, svg_fragment=svg_fragment, old_svg_fragment=None,
                 narration=narration or f"Drew {element_id}", audio_path=audio, alignment_path=alignment)
    return OK


def modify(engine, page_id, element_id, new_svg_fragment):
    with Session(engine) as db:
        old = db.exec(select(PageEvent).where(PageEvent.page_id == page_id, PageEvent.element_id == element_id)
                      .where(PageEvent.kind.in_(("draw", "modify"))).order_by(PageEvent.seq.desc())).first().svg_fragment

    def apply(pg):
        pg.current_svg = pg.current_svg.replace(old, new_svg_fragment, 1)
    append_event(engine, page_id, apply, kind="modify", element_id=element_id, svg_fragment=new_svg_fragment, old_svg_fragment=old,
                 narration=None, audio_path=None, alignment_path=None)
    return OK


def draw_live(page_id, element_id, svg_fragment, narration=None):
    """Seed a drawing into the database a RUNNING dev server uses (browser tests; the server only learns of it when the page loads). The server's
    database is the repo's SQLite file unless LP_LIVE_DATABASE_URL names another."""
    import os

    from sqlalchemy import create_engine
    url = os.environ.get("LP_LIVE_DATABASE_URL") or f"sqlite:///{Path(__file__).parent.parent / 'learning_platform.db'}"
    eng = create_engine(url)
    try:
        return draw(eng, page_id, element_id, svg_fragment, narration)
    finally:
        eng.dispose()
