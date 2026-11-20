"""
backend/database.py
Database connection, session management, and table initialization.
Supports PostgreSQL (default per architecture) with local SQLite fallback.
"""

import os
from pathlib import Path
from dotenv import load_dotenv
from sqlmodel import create_engine, Session

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    db_path = Path(__file__).parent.parent / "learning_platform.db"
    DATABASE_URL = f"sqlite:///{db_path}"

if DATABASE_URL.startswith(("postgres://", "postgresql://", "postgresql+psycopg2://")):
    try:
        import psycopg2  # noqa: F401  (the driver SQLAlchemy uses for these URLs; optional, see requirements-postgres.txt)
    except ImportError as e:
        raise RuntimeError("DATABASE_URL points at Postgres but the psycopg2 driver is not installed. Install it with "
                           "`pip install -r requirements-postgres.txt`, or unset DATABASE_URL to use SQLite.") from e

connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(
    DATABASE_URL,
    echo=False,
    connect_args=connect_args,
    # Postgres drops idle connections; without these the first request after a quiet spell gets a 500.
    pool_pre_ping=True,
    pool_recycle=1800,
)

def init_db():
    """Bring the schema up to date (see backend/migrate.py) and make sure the default learner exists."""
    from backend.migrate import migrate
    migrate(DATABASE_URL)
    ensure_default_learner()


def ensure_default_learner():
    """The one learner every notebook belongs to until there is a login. Migration 0004 creates it; this puts it back if it was ever deleted."""
    from sqlalchemy.exc import IntegrityError
    from backend.models import DEFAULT_LEARNER_ID, Learner
    with Session(engine) as db:
        if db.get(Learner, DEFAULT_LEARNER_ID) is None:
            db.add(Learner(id=DEFAULT_LEARNER_ID, name="Learner"))
            try:
                db.commit()
            except IntegrityError:          # another process created it first
                db.rollback()


def get_session():
    with Session(engine) as session:
        yield session
