"""
Learners (migration 0004): one default learner row, created by the migration, and every notebook belongs to a learner. No login.
Migration tests run on SQLite and on a throwaway Postgres database (the `db_url` fixture in conftest.py).
"""
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

sys.path.insert(0, str(Path(__file__).parent.parent))

from alembic import command
from backend.migrate import alembic_config, migrate

NOW = "2026-01-01 00:00:00"


def test_a_fresh_database_gets_exactly_one_default_learner_and_notebooks_point_at_learners(db_url):
    migrate(db_url)
    engine = create_engine(db_url)
    with engine.connect() as c:
        assert c.execute(text("select id, name from learners")).fetchall() == [("default", "Learner")]
    insp = inspect(engine)
    assert "learner_id" in {col["name"] for col in insp.get_columns("notebooks")}
    assert [fk["referred_table"] for fk in insp.get_foreign_keys("notebooks")] == ["learners"]
    assert any(i["column_names"] == ["learner_id"] for i in insp.get_indexes("notebooks"))
    migrate(db_url)                                         # safe to run on every start: still exactly one default learner
    with engine.connect() as c:
        assert c.execute(text("select count(*) from learners")).scalar() == 1


def test_existing_data_survives_and_every_existing_notebook_gets_the_default_learner(db_url):
    cfg = alembic_config(db_url)
    command.upgrade(cfg, "0003")                            # the schema before learners
    engine = create_engine(db_url)
    with engine.begin() as c:
        for n in ("n1", "n2"):
            c.execute(text("insert into notebooks (id,title,topic,created_at,updated_at) values (:n,:n,'topic',:t,:t)"), {"n": n, "t": NOW})
        c.execute(text("insert into pages (id,notebook_id,page_number,title,summary,element_count,canvas_coverage,status,created_at,updated_at) "
                       "values ('p1','n1',1,'Title','Summary',2,0.2,'active',:t,:t)"), {"t": NOW})
        c.execute(text("insert into page_events (id,page_id,seq,kind,element_id,svg_fragment,narration,timestamp) values ('e1','p1',1,'draw','a','<g id=\"a\"/>','Hello',:t)"), {"t": NOW})
        c.execute(text("insert into chat_turns (id,notebook_id,page_id,seq,role,content,timestamp) values ('c1','n1','p1',1,'user','hi',:t)"), {"t": NOW})
    command.upgrade(cfg, "head")
    with engine.connect() as c:
        assert c.execute(text("select id, learner_id, topic from notebooks order by id")).fetchall() == [("n1", "default", "topic"), ("n2", "default", "topic")]
        assert c.execute(text("select title, summary, element_count from pages")).fetchall() == [("Title", "Summary", 2)]
        assert c.execute(text("select seq, narration from page_events")).fetchall() == [(1, "Hello")]
        assert c.execute(text("select content from chat_turns")).fetchall() == [("hi",)]
        assert c.execute(text("select count(*) from learners")).scalar() == 1


def test_a_notebook_inserted_without_a_learner_belongs_to_the_default_one(db_url):
    migrate(db_url)
    engine = create_engine(db_url)
    with engine.begin() as c:
        c.execute(text("insert into notebooks (id,title,topic,created_at,updated_at) values ('x','T','t',:t,:t)"), {"t": NOW})
        assert c.execute(text("select learner_id from notebooks where id='x'")).scalar() == "default"


def test_the_database_refuses_a_notebook_for_a_learner_that_does_not_exist(db_url):
    migrate(db_url)
    engine = create_engine(db_url)
    with engine.connect() as c:
        if db_url.startswith("sqlite"):
            c.exec_driver_sql("PRAGMA foreign_keys=ON")        # SQLite enforces foreign keys only when asked, per connection
        with pytest.raises(IntegrityError):
            c.execute(text("insert into notebooks (id,title,topic,learner_id,created_at,updated_at) values ('x','T','t','nobody',:t,:t)"), {"t": NOW})
            c.commit()


def test_the_migration_can_be_undone_and_redone_without_losing_notebooks(db_url):
    migrate(db_url)
    engine = create_engine(db_url)
    with engine.begin() as c:
        c.execute(text("insert into notebooks (id,title,topic,created_at,updated_at) values ('x','T','t',:t,:t)"), {"t": NOW})
    command.downgrade(alembic_config(db_url), "0003")
    insp = inspect(create_engine(db_url))
    assert "learners" not in insp.get_table_names() and "learner_id" not in {c["name"] for c in insp.get_columns("notebooks")}
    command.upgrade(alembic_config(db_url), "head")
    with create_engine(db_url).connect() as c:
        assert c.execute(text("select id, learner_id from notebooks")).fetchall() == [("x", "default")]


# ---- through the app ---------------------------------------------------------------------------------------------------------------

def test_a_new_notebook_gets_the_default_learner():
    from fastapi.testclient import TestClient
    from sqlmodel import Session
    import backend.main as bm
    from backend.database import engine, init_db
    from backend.models import DEFAULT_LEARNER_ID, Learner, Notebook
    init_db()
    client = TestClient(bm.app)
    nb = client.post("/api/notebooks", json={"topic": "Learner check"}).json()["id"]
    try:
        with Session(engine) as db:
            assert db.get(Notebook, nb).learner_id == DEFAULT_LEARNER_ID
            assert db.get(Learner, DEFAULT_LEARNER_ID).name == "Learner"
    finally:
        client.delete(f"/api/notebooks/{nb}")


def test_the_default_learner_is_put_back_if_it_was_ever_deleted(db_url, monkeypatch):
    from sqlmodel import Session, select
    import backend.database as database
    from backend.models import DEFAULT_LEARNER_ID, Learner
    migrate(db_url)
    engine = create_engine(db_url)
    monkeypatch.setattr(database, "engine", engine)           # a database of its own: the shared test database has notebooks that point at the learner
    with Session(engine) as db:
        db.delete(db.get(Learner, DEFAULT_LEARNER_ID))
        db.commit()
    database.ensure_default_learner()
    database.ensure_default_learner()                         # idempotent
    with Session(engine) as db:
        assert db.get(Learner, DEFAULT_LEARNER_ID) is not None
        assert len(db.exec(select(Learner)).all()) == 1
