"""
Test isolation.
1. Point tests at a throwaway database so they never touch real notebooks (must run before backend.database is
   imported: load_dotenv will not override an environment variable that is already set).
2. Start every run from an empty test database and write audio into a temp folder, so repeated runs do not pile up
   rows or files.
"""
import os

import pytest
from dotenv import load_dotenv

load_dotenv()
url = os.environ.get("DATABASE_URL", "")
if os.environ.get("TEST_DATABASE_URL"):
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
elif url.startswith("postgresql") and url.endswith("/learning_platform"):
    os.environ["DATABASE_URL"] = url + "_test"
elif not url or url.startswith("sqlite"):   # the default is the real learning_platform.db, which the wipe below would empty
    import tempfile
    os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(prefix="lp_test_"), "test.db").replace("\\", "/")


@pytest.fixture(scope="session", autouse=True)
def _clean_database_and_output_dir(tmp_path_factory):
    import backend.main as backend_main
    import engine.author as author
    from sqlmodel import SQLModel
    from backend.database import engine as db_engine, init_db

    init_db()
    db_name = str(db_engine.url.database or "")
    # Only ever wipe a database that is clearly a test database (or the throwaway SQLite fallback).
    if db_name.endswith("_test") or str(db_engine.url).startswith("sqlite"):
        with db_engine.begin() as conn:
            for table in reversed(SQLModel.metadata.sorted_tables):
                if table.name != "learners":          # the default learner is part of the schema, not test data
                    conn.execute(table.delete())

    out = tmp_path_factory.mktemp("generated_notebooks")
    mp = pytest.MonkeyPatch()
    mp.setattr(author, "OUTPUT_DIR", out)
    mp.setattr(backend_main, "OUTPUT_DIR", out)
    yield
    mp.undo()


# ---- a database URL for migration tests: SQLite, and a throwaway Postgres database when there is a server -------------------------------

def _postgres_server():
    """An autocommit engine on the server part of DATABASE_URL if it is a reachable Postgres we can create databases on, else None."""
    import sqlalchemy
    from sqlalchemy.engine import make_url
    url = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL", "")
    if not url.startswith("postgresql"):
        return None, None
    try:
        import psycopg2  # noqa: F401
        eng = sqlalchemy.create_engine(make_url(url).set(database="postgres"), isolation_level="AUTOCOMMIT")
        with eng.connect() as c:
            c.execute(sqlalchemy.text("select 1"))
        return eng, url
    except Exception:
        return None, None


@pytest.fixture(params=["sqlite", "postgres"])
def db_url(request, tmp_path):
    """A fresh, empty database URL, once for SQLite and once for Postgres (a database created on the server in DATABASE_URL and dropped afterwards;
    skipped when there is no Postgres or no psycopg2)."""
    import sqlalchemy
    import uuid
    from sqlalchemy.engine import make_url
    if request.param == "sqlite":
        yield f"sqlite:///{(tmp_path / 'm.db').as_posix()}"
        return
    server, url = _postgres_server()
    if server is None:
        pytest.skip("no reachable Postgres (and psycopg2) in DATABASE_URL")
    name = f"lp_migr_{uuid.uuid4().hex[:10]}"
    with server.connect() as c:
        c.execute(sqlalchemy.text(f'CREATE DATABASE "{name}"'))
    try:
        yield make_url(url).set(database=name).render_as_string(hide_password=False)
    finally:
        with server.connect() as c:
            c.execute(sqlalchemy.text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        server.dispose()


@pytest.fixture(autouse=True)
def _no_real_model_for_summaries(monkeypatch):
    """Saving a page writes a summary with one cheap model call. In the in-process suite that call must never reach the real model: it fails
    (and is logged) unless a test installs its own fake client on backend.page_summary.CLIENT_FACTORY."""
    import backend.page_summary as page_summary

    def refuse():
        raise RuntimeError("tests never call the real model for a page summary")
    monkeypatch.setattr(page_summary, "CLIENT_FACTORY", refuse)
    import engine.lesson_plan as lesson_plan                                   # nor for a scene-mode lesson plan (a failure: teaching goes on without one)
    monkeypatch.setattr(lesson_plan, "CLIENT_FACTORY", refuse)
    # Scene mode is the app's default; most tests were written for the raw-SVG tutor and keep testing it. A scene test sets LP_SCENE_MODE=1.
    monkeypatch.setenv("LP_SCENE_MODE", "0")
    monkeypatch.delenv("LP_VOICE", raising=False)   # voice tests fake ElevenLabs; LP_VOICE=0 (a lesson-check setting) would bypass them
    # Tests fake the model client, but the app checks that a model is configured: a placeholder lets the suite run on a machine
    # with no .env (GitHub CI, a fresh clone). The missing-key test removes it again.
    import engine.author as author
    if not author.AZURE_OPENAI_API_KEY:
        monkeypatch.setattr(author, "AZURE_OPENAI_API_KEY", "placeholder-key-for-tests")
    if not author.AZURE_OPENAI_ENDPOINT:
        monkeypatch.setattr(author, "AZURE_OPENAI_ENDPOINT", "https://placeholder.invalid/")


@pytest.fixture()
def api(db_url, monkeypatch):
    """The app (a TestClient) on a fresh database, once for SQLite and once for a throwaway Postgres database when there is a server. Yields (client, engine)."""
    from fastapi.testclient import TestClient
    from sqlmodel import create_engine
    import backend.database as database
    import backend.main as backend_main
    from backend.migrate import migrate
    migrate(db_url)
    eng = create_engine(db_url)
    monkeypatch.setattr(database, "engine", eng)
    monkeypatch.setattr(backend_main, "engine", eng)
    yield TestClient(backend_main.app), eng
    eng.dispose()
