"""Mindprint: a misconception is kept after the right answer that follows its correction (they often return after one correction).
`concepts.misconception_corrected` marks it corrected; `concepts.misconception_lesson` is a short hash of the lesson plan in force when
the belief was recorded or last corrected: only a right answer in a later lesson clears it.

Idempotent (an adopted database created from the current models already has them).

Revision ID: 0011
Revises: 0010
"""
from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    have = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("concepts")}
    with op.batch_alter_table("concepts") as batch:
        if "misconception_corrected" not in have:
            batch.add_column(sa.Column("misconception_corrected", sa.Boolean(), nullable=False, server_default=sa.false()))
        if "misconception_lesson" not in have:
            batch.add_column(sa.Column("misconception_lesson", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("concepts") as batch:
        batch.drop_column("misconception_lesson")
        batch.drop_column("misconception_corrected")
