"""notebooks.lesson_plan: the private lesson plan of scene mode (engine/lesson_plan.py); null for every existing notebook.

Idempotent (an adopted database created from the current models already has the column).

Revision ID: 0007
Revises: 0006
"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "lesson_plan" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("notebooks")}:
        with op.batch_alter_table("notebooks") as batch:
            batch.add_column(sa.Column("lesson_plan", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("notebooks") as batch:
        batch.drop_column("lesson_plan")
