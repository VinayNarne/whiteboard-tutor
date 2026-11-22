"""Alembic migrations: fresh databases, pre-Alembic databases, drift between models and migrations."""
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

sys.path.insert(0, str(Path(__file__).parent.parent))

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlmodel import SQLModel

import backend.models  # noqa: F401  (registers tables)
from backend.migrate import alembic_config, migrate

NOW = "2026-01-01 00:00:00"   # plain string: avoids sqlite3's deprecated datetime adapter
def _head():
    from alembic.script import ScriptDirectory
    return ScriptDirectory.from_config(alembic_config("sqlite://")).get_current_head()


HEAD = _head()      # the newest migration, so this file does not need an edit for every new one
MODEL_TABLES = {"learners", "notebooks", "pages", "page_events", "chat_turns", "concepts", "learner_prefs"}


def _url(tmp_path, name="m.db"):
    return f"sqlite:///{(tmp_path / name).as_posix()}"


def _version(engine):
    with engine.connect() as c:
        return c.execute(text("select version_num from alembic_version")).scalar()


def test_fresh_database_gets_every_table_the_index_and_the_head_version(tmp_path):
    url = _url(tmp_path)
    migrate(url)
    engine = create_engine(url)
    insp = inspect(engine)
    assert set(insp.get_table_names()) == MODEL_TABLES | {"alembic_version"}
    uq = [i for i in insp.get_indexes("pages") if i["name"] == "uq_pages_notebook_number"]
    assert uq and uq[0]["unique"] and uq[0]["column_names"] == ["notebook_id", "page_number"]
    assert _version(engine) == HEAD
    migrate(url)                                          # safe to run on every start
    assert _version(engine) == HEAD


def test_migrations_match_the_models_exactly(tmp_path):
    """If you change a model without writing a migration, this fails and prints the missing change."""
    url = _url(tmp_path)
    migrate(url)
    engine = create_engine(url)
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn, opts={"compare_type": True})
        diff = compare_metadata(ctx, SQLModel.metadata)
    assert diff == [], f"models and migrations have drifted: {diff}"


def test_database_created_before_migrations_is_adopted_without_touching_its_data(tmp_path):
    url = _url(tmp_path, "old.db")
    engine = create_engine(url)
    SQLModel.metadata.create_all(engine)                  # how the app created tables before Alembic
    with engine.begin() as c:
        now = NOW
        c.execute(text("insert into notebooks (id,title,topic,learner_id,created_at,updated_at) values ('n1','T','topic','default',:t,:t)"), {"t": now})
        c.execute(text("insert into pages (id,notebook_id,page_number,element_count,canvas_coverage,status,created_at,updated_at) "
                       "values ('p1','n1',1,3,0.2,'active',:t,:t)"), {"t": now})
    assert "alembic_version" not in inspect(engine).get_table_names()

    migrate(url)

    assert _version(engine) == HEAD
    with engine.connect() as c:
        assert c.execute(text("select topic from notebooks where id='n1'")).scalar() == "topic"
        assert c.execute(text("select element_count from pages where id='p1'")).scalar() == 3
        assert c.execute(text("select id from learners")).fetchall() == [("default",)]      # the adopted database gets its default learner


def test_adoption_tolerates_a_legacy_database_that_already_has_the_unique_index(tmp_path):
    url = _url(tmp_path, "legacy.db")
    engine = create_engine(url)
    SQLModel.metadata.create_all(engine)
    with engine.begin() as c:                              # the old startup hook had created this index by hand
        c.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_pages_notebook_number ON pages (notebook_id, page_number)"))
    migrate(url)                                           # must not fail with "index already exists"
    assert _version(engine) == HEAD


def test_unique_page_number_is_enforced_by_the_schema(tmp_path):
    url = _url(tmp_path)
    migrate(url)
    engine = create_engine(url)
    now = NOW
    with engine.begin() as c:
        c.execute(text("insert into notebooks (id,title,topic,created_at,updated_at) values ('n','T','t',:t,:t)"), {"t": now})
        c.execute(text("insert into pages (id,notebook_id,page_number,element_count,canvas_coverage,status,created_at,updated_at) "
                       "values ('a','n',1,0,0,'active',:t,:t)"), {"t": now})
    with pytest.raises(IntegrityError):
        with engine.begin() as c:
            c.execute(text("insert into pages (id,notebook_id,page_number,element_count,canvas_coverage,status,created_at,updated_at) "
                           "values ('b','n',1,0,0,'active',:t,:t)"), {"t": now})


def test_downgrade_to_base_removes_everything(tmp_path):
    url = _url(tmp_path)
    migrate(url)
    command.downgrade(alembic_config(url), "base")
    assert set(inspect(create_engine(url)).get_table_names()) <= {"alembic_version"}
