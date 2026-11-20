"""Baseline: the four tables as they existed when migrations were introduced.

(svg_fragment and content are nullable because the models declare them with sa_column, which bypasses
SQLModel's not-null default. This matches the databases that already exist.)

Revision ID: 0001
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notebooks",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("topic", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_notebooks_title", "notebooks", ["title"])

    op.create_table(
        "pages",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("notebook_id", sa.String(), sa.ForeignKey("notebooks.id"), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("summary", sa.String(), nullable=True),
        sa.Column("current_svg", sa.Text(), nullable=True),
        sa.Column("element_count", sa.Integer(), nullable=False),
        sa.Column("canvas_coverage", sa.Float(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_pages_notebook_id", "pages", ["notebook_id"])
    op.create_index("ix_pages_page_number", "pages", ["page_number"])
    op.create_index("ix_pages_status", "pages", ["status"])

    op.create_table(
        "page_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("page_id", sa.String(), sa.ForeignKey("pages.id"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("element_id", sa.String(), nullable=False),
        sa.Column("svg_fragment", sa.Text(), nullable=True),
        sa.Column("old_svg_fragment", sa.Text(), nullable=True),
        sa.Column("narration", sa.Text(), nullable=True),
        sa.Column("audio_path", sa.String(), nullable=True),
        sa.Column("alignment_path", sa.String(), nullable=True),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_page_events_page_id", "page_events", ["page_id"])
    op.create_index("ix_page_events_seq", "page_events", ["seq"])
    op.create_index("ix_page_events_kind", "page_events", ["kind"])

    op.create_table(
        "chat_turns",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("notebook_id", sa.String(), sa.ForeignKey("notebooks.id"), nullable=False),
        sa.Column("page_id", sa.String(), nullable=True),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("tool_calls_made", sa.JSON(), nullable=True),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_chat_turns_notebook_id", "chat_turns", ["notebook_id"])
    op.create_index("ix_chat_turns_page_id", "chat_turns", ["page_id"])
    op.create_index("ix_chat_turns_seq", "chat_turns", ["seq"])
    op.create_index("ix_chat_turns_role", "chat_turns", ["role"])


def downgrade() -> None:
    for t in ("chat_turns", "page_events", "pages", "notebooks"):
        op.drop_table(t)
