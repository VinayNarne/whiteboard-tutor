"""Playbook: `teaching_log` (the teaching move chosen for each turn and how it turned out) and the notebook intake columns
(purpose, time_budget, self_level; all optional).

Idempotent (an adopted database created from the current models already has them).

Revision ID: 0013
Revises: 0012
"""
from alembic import op
import sqlalchemy as sa

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

INTAKE = ("purpose", "time_budget", "self_level")


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    have = {c["name"] for c in insp.get_columns("notebooks")}
    with op.batch_alter_table("notebooks") as batch:
        for name in INTAKE:
            if name not in have:
                batch.add_column(sa.Column(name, sa.String(), nullable=True))
    if "teaching_log" in insp.get_table_names():
        return
    op.create_table(
        "teaching_log",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("learner_id", sa.String(), sa.ForeignKey("learners.id"), nullable=False),
        sa.Column("concept_id", sa.String(), nullable=True),
        sa.Column("notebook_id", sa.String(), nullable=False),
        sa.Column("page_id", sa.String(), nullable=False),
        sa.Column("step", sa.Integer(), nullable=False),
        sa.Column("move", sa.String(), nullable=False),
        sa.Column("turn_id", sa.String(), nullable=False),
        sa.Column("outcome", sa.String(), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_teaching_log_learner_id", "teaching_log", ["learner_id"])


def downgrade() -> None:
    op.drop_index("ix_teaching_log_learner_id", table_name="teaching_log")
    op.drop_table("teaching_log")
    with op.batch_alter_table("notebooks") as batch:
        for name in INTAKE:
            batch.drop_column(name)
