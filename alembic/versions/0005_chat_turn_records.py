"""chat_turns.about_element_ids: which drawings a learner's question was about ("ask about a drawing").

chat_turns.tool_calls_made already existed and was never written; it is now filled for every tutor turn (backend/main.py). Nothing existing is touched:
old turns keep NULL in the new column. Idempotent (an adopted database created from the current models already has the column).

Revision ID: 0005
Revises: 0004
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "about_element_ids" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("chat_turns")}:
        with op.batch_alter_table("chat_turns") as batch:
            batch.add_column(sa.Column("about_element_ids", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("chat_turns") as batch:
        batch.drop_column("about_element_ids")
