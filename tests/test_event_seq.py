"""
(page_id, seq) is unique, on SQLite and on Postgres (migration 0003), and the app can still write, undo and race.

The Postgres cases run against a throwaway database created on the server in DATABASE_URL and dropped afterwards; they skip when there is
no Postgres (or no psycopg2).
"""
import sys
import threading
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

sys.path.insert(0, str(Path(__file__).parent.parent))

from alembic import command
from backend.migrate import alembic_config, migrate

NOW = "2026-01-01 00:00:00"


def _seed(c, events):
    """A notebook with one page and the given (id, seq, timestamp) events."""
    c.execute(text("insert into notebooks (id,title,topic,created_at,updated_at) values ('n','T','t',:t,:t)"), {"t": NOW})
    c.execute(text("insert into pages (id,notebook_id,page_number,element_count,canvas_coverage,status,created_at,updated_at) "
                   "values ('p','n',1,0,0,'active',:t,:t)"), {"t": NOW})
    for eid, seq, ts in events:
        c.execute(text("insert into page_events (id,page_id,seq,kind,element_id,svg_fragment,timestamp) values (:i,'p',:s,'draw',:i,'<g/>',:t)"),
                  {"i": eid, "s": seq, "t": ts})


def test_the_schema_refuses_two_events_with_the_same_seq_on_one_page(db_url):
    migrate(db_url)
    engine = create_engine(db_url)
    with engine.begin() as c:
        _seed(c, [("a", 1, NOW)])
    idx = [i for i in inspect(engine).get_indexes("page_events") if i["name"] == "uq_page_events_page_seq"]
    assert idx and idx[0]["unique"] and idx[0]["column_names"] == ["page_id", "seq"]
    with pytest.raises(IntegrityError):
        with engine.begin() as c:
            c.execute(text("insert into page_events (id,page_id,seq,kind,element_id,svg_fragment,timestamp) values ('b','p',1,'draw','b','<g/>',:t)"), {"t": NOW})
    with engine.begin() as c:                      # the same seq on ANOTHER page is fine
        c.execute(text("insert into pages (id,notebook_id,page_number,element_count,canvas_coverage,status,created_at,updated_at) "
                       "values ('p2','n',2,0,0,'active',:t,:t)"), {"t": NOW})
        c.execute(text("insert into page_events (id,page_id,seq,kind,element_id,svg_fragment,timestamp) values ('c','p2',1,'draw','c','<g/>',:t)"), {"t": NOW})


def test_existing_duplicates_are_renumbered_in_their_order_and_nothing_is_lost(db_url):
    cfg = alembic_config(db_url)
    command.upgrade(cfg, "0002")                   # the schema as it was before the constraint
    engine = create_engine(db_url)
    with engine.begin() as c:
        _seed(c, [("a", 1, "2026-01-01 00:00:01"), ("b", 2, "2026-01-01 00:00:02"), ("c", 2, "2026-01-01 00:00:03"),
                  ("d", 2, "2026-01-01 00:00:02"), ("e", 4, "2026-01-01 00:00:05")])
    command.upgrade(cfg, "head")
    with engine.connect() as c:
        rows = c.execute(text("select id, seq from page_events where page_id='p' order by seq")).fetchall()
    # the three events that shared seq 2 keep their order (timestamp, then id): b, d (same second, id order), c; then e
    assert [r[0] for r in rows] == ["a", "b", "d", "c", "e"] and [r[1] for r in rows] == [1, 2, 3, 4, 5]


def test_a_database_without_duplicates_keeps_its_seq_numbers(db_url):
    cfg = alembic_config(db_url)
    command.upgrade(cfg, "0002")
    engine = create_engine(db_url)
    with engine.begin() as c:
        _seed(c, [("a", 1, NOW), ("b", 3, NOW), ("c", 7, NOW)])        # gaps are fine
    command.upgrade(cfg, "head")
    with engine.connect() as c:
        assert [r[0] for r in c.execute(text("select seq from page_events order by seq"))] == [1, 3, 7]


def test_the_migration_can_be_undone(db_url):
    migrate(db_url)
    command.downgrade(alembic_config(db_url), "0002")
    assert not [i for i in inspect(create_engine(db_url)).get_indexes("page_events") if i["name"] == "uq_page_events_page_seq"]


# ---- the app side: next seq inside the transaction, a lost race is retried ---------------------------------------------------------

def _page(engine):
    from backend.models import Notebook, Page
    from sqlmodel import Session
    with Session(engine) as db:
        nb = Notebook(title="T", topic="t")
        db.add(nb)
        db.commit()
        pg = Page(notebook_id=nb.id, page_number=1)
        db.add(pg)
        db.commit()
        return pg.id


def test_append_event_numbers_events_one_after_another_and_refuses_a_saved_page(db_url):
    from backend.event_store import append_event
    from backend.models import Page
    from sqlmodel import Session
    migrate(db_url)
    engine = create_engine(db_url)
    pid = _page(engine)
    assert [append_event(engine, pid, kind="draw", element_id=f"e{i}", svg_fragment="<g/>") for i in range(3)] == [1, 2, 3]
    with Session(engine) as db:
        pg = db.get(Page, pid)
        pg.status = "saved"
        db.add(pg)
        db.commit()
    assert append_event(engine, pid, kind="draw", element_id="late", svg_fragment="<g/>") is None


def test_a_lost_race_for_the_same_seq_is_retried_with_the_new_maximum(db_url, monkeypatch):
    from backend import event_store
    from backend.models import PageEvent
    from sqlmodel import Session, select
    migrate(db_url)
    engine = create_engine(db_url)
    pid = _page(engine)
    event_store.append_event(engine, pid, kind="draw", element_id="first", svg_fragment="<g/>")
    real = Session
    raced = []

    class Racing(real):
        def commit(self):
            if not raced:                              # a competing writer takes the number this insert was about to use
                raced.append(True)
                with real(engine) as other:
                    other.add(PageEvent(page_id=pid, seq=2, kind="draw", element_id="rival", svg_fragment="<g/>"))
                    other.commit()
            return super().commit()
    monkeypatch.setattr(event_store, "Session", Racing)
    assert event_store.append_event(engine, pid, kind="draw", element_id="mine", svg_fragment="<g/>") == 3
    with real(engine) as db:
        got = [(e.seq, e.element_id) for e in db.exec(select(PageEvent).where(PageEvent.page_id == pid).order_by(PageEvent.seq))]
    assert got == [(1, "first"), (2, "rival"), (3, "mine")]


def test_concurrent_writers_never_produce_a_duplicate_or_lose_an_event(db_url):
    from backend.event_store import append_event
    migrate(db_url)
    engine = create_engine(db_url)
    pid = _page(engine)
    errors, seqs = [], []

    def writer(k):
        try:
            for i in range(6):
                seqs.append(append_event(engine, pid, kind="draw", element_id=f"w{k}_{i}", svg_fragment="<g/>"))
        except Exception as e:           # pragma: no cover - the point of the test is that this stays empty
            errors.append(e)
    threads = [threading.Thread(target=writer, args=(k,)) for k in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors and sorted(seqs) == list(range(1, 25)) and len(set(seqs)) == 24
