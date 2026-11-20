"""chat_turns.status: "ok" (default) or "failed" for a tutor turn the model never answered.

A failed turn is shown to the learner (with a retry button) but is not read by the tutor (history), the page summary or the export. Every existing turn is "ok".
Idempotent (an adopted database created from the current models already has the column).

Revision ID: 0006
Revises: 0005
"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "status" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("chat_turns")}:
        with op.batch_alter_table("chat_turns") as batch:
            batch.add_column(sa.Column("status", sa.String(), nullable=False, server_default="ok"))


def downgrade() -> None:
    with op.batch_alter_table("chat_turns") as batch:
        batch.drop_column("status")
