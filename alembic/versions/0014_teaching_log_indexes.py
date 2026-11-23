"""Playbook: indexes on teaching_log.notebook_id and concept_id (the per-turn lookups and the notebook delete filter by them).

Idempotent (an adopted database created from the current models already has them).

Revision ID: 0014
Revises: 0013
"""
from alembic import op
import sqlalchemy as sa

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

INDEXES = (("ix_teaching_log_notebook_id", "notebook_id"), ("ix_teaching_log_concept_id", "concept_id"))


def upgrade() -> None:
    have = {i["name"] for i in sa.inspect(op.get_bind()).get_indexes("teaching_log")}
    for name, column in INDEXES:
        if name not in have:
            op.create_index(name, "teaching_log", [column])


def downgrade() -> None:
    for name, _ in INDEXES:
        op.drop_index(name, table_name="teaching_log")
