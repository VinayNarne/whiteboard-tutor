"""
backend/migrate.py
Brings a database to the latest schema with Alembic. Safe to call on every start.

- brand-new database          -> runs every migration
- database that already has tables but no alembic_version (created before migrations existed)
                              -> marked as being at the baseline (no data is touched), then upgraded
- up-to-date database         -> does nothing
Change a model, then create the migration with:   alembic revision --autogenerate -m "describe the change"
"""
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

ROOT = Path(__file__).resolve().parent.parent
BASELINE = "0001"


def alembic_config(url: str) -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def migrate(url: str) -> None:
    engine = create_engine(url)
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    cfg = alembic_config(url)
    if "alembic_version" not in tables and "notebooks" in tables:
        command.stamp(cfg, BASELINE)
    command.upgrade(cfg, "head")
