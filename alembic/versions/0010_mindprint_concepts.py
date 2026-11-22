"""Mindprint foundations: the `concepts` table (one row per idea a learner has met, with its mastery state) and `step_concepts`
(the concept id of each lesson-plan step) next to both places a plan is stored, notebooks.lesson_plan and pages.lesson_plan.

Idempotent (an adopted database created from the current models already has them).

Revision ID: 0010
Revises: 0009
"""
from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "concepts" not in insp.get_table_names():
        op.create_table(
            "concepts",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("learner_id", sa.String(), sa.ForeignKey("learners.id"), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("embedding", sa.JSON(), nullable=False),
            sa.Column("level", sa.String(), nullable=False, server_default="new"),
            sa.Column("right_turns", sa.JSON(), nullable=False),
            sa.Column("last_wrong", sa.Text(), nullable=True),
            sa.Column("misconception", sa.Text(), nullable=True),
            sa.Column("created_from_page_id", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_concepts_learner_id", "concepts", ["learner_id"])
    for table in ("notebooks", "pages"):
        if "step_concepts" not in {c["name"] for c in insp.get_columns(table)}:
            with op.batch_alter_table(table) as batch:
                batch.add_column(sa.Column("step_concepts", sa.JSON(), nullable=True))


def downgrade() -> None:
    for table in ("pages", "notebooks"):
        with op.batch_alter_table(table) as batch:
            batch.drop_column("step_concepts")
    op.drop_index("ix_concepts_learner_id", table_name="concepts")
    op.drop_table("concepts")
