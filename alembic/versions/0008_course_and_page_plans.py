"""notebooks.course (the learner's goal and roadmap) and pages.lesson_plan (one lesson plan per page); null for every existing row.

Idempotent (an adopted database created from the current models already has the columns).

Revision ID: 0008
Revises: 0007
"""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

COLUMNS = (("notebooks", "course"), ("pages", "lesson_plan"))


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table, column in COLUMNS:
        if column not in {c["name"] for c in inspector.get_columns(table)}:
            with op.batch_alter_table(table) as batch:
                batch.add_column(sa.Column(column, sa.Text(), nullable=True))


def downgrade() -> None:
    for table, column in COLUMNS:
        with op.batch_alter_table(table) as batch:
            batch.drop_column(column)
