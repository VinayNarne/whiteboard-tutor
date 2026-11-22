"""Mindprint phase 2: `learner_prefs`, the ways of being taught that a learner chose themselves (one row per learner and kind).

Idempotent (an adopted database created from the current models already has it).

Revision ID: 0012
Revises: 0011
"""
from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "learner_prefs" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "learner_prefs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("learner_id", sa.String(), sa.ForeignKey("learners.id"), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_learner_prefs_learner_id", "learner_prefs", ["learner_id"])
    op.create_index("uq_learner_prefs_learner_kind", "learner_prefs", ["learner_id", "kind"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_learner_prefs_learner_kind", table_name="learner_prefs")
    op.drop_index("ix_learner_prefs_learner_id", table_name="learner_prefs")
    op.drop_table("learner_prefs")
