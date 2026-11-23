"""Lesson recap: the grader's verdict on a learner's answer is kept on that learner turn (`grade`: right|partial|wrong, `belief`: the
quote-checked wrong belief it found), so the recap can be built from stored records alone.

Idempotent (an adopted database created from the current models already has them).

Revision ID: 0015
Revises: 0014
"""
from alembic import op
import sqlalchemy as sa

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    have = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("chat_turns")}
    with op.batch_alter_table("chat_turns") as batch:
        if "grade" not in have:
            batch.add_column(sa.Column("grade", sa.String(), nullable=True))
        if "belief" not in have:
            batch.add_column(sa.Column("belief", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("chat_turns") as batch:
        batch.drop_column("belief")
        batch.drop_column("grade")
