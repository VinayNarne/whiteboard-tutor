"""page_events.block: the structured record of a scene-mode block (what the tutor asked for and where code put it), on the block's
first step; null for every existing row.

Idempotent (an adopted database created from the current models already has the column).

Revision ID: 0009
Revises: 0008
"""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "block" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("page_events")}:
        with op.batch_alter_table("page_events") as batch:
            batch.add_column(sa.Column("block", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("page_events") as batch:
        batch.drop_column("block")
