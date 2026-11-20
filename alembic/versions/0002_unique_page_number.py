"""Page numbers are unique within a notebook.

Idempotent on purpose: databases created before migrations existed already got this index from a startup hook,
so an existing index with the same name is left alone.

Revision ID: 0002
Revises: 0001
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_pages_notebook_number ON pages (notebook_id, page_number)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_pages_notebook_number")
