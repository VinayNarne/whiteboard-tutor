"""Alembic environment. The URL comes from the caller (backend/migrate.py) or, for the CLI, from DATABASE_URL."""
from alembic import context
from sqlalchemy import create_engine
from sqlmodel import SQLModel

import backend.models  # noqa: F401  (registers every table on SQLModel.metadata)
from backend.database import DATABASE_URL

config = context.config
url = config.get_main_option("sqlalchemy.url") or DATABASE_URL.replace("%", "%%")
target_metadata = SQLModel.metadata


def _opts():
    return dict(target_metadata=target_metadata, compare_type=True, render_as_batch=url.startswith("sqlite"))


def run_migrations_offline() -> None:
    context.configure(url=url.replace("%%", "%"), literal_binds=True, **_opts())
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(url.replace("%%", "%"))
    with engine.connect() as connection:
        context.configure(connection=connection, **_opts())
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
