"""Learners: one default learner row, and every notebook belongs to a learner.

There is no login. The default learner (id "default") is created here, and notebooks.learner_id is added with the default as its value, so every
existing notebook belongs to it and a notebook created without saying more does too. Nothing existing is touched or removed.

Revision ID: 0004
Revises: 0003
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

DEFAULT = "default"


def upgrade() -> None:
    # Idempotent on purpose, like 0002: a database created by SQLModel's create_all from the current models (the "adopt a pre-Alembic
    # database" path) already has the table and the column.
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "learners" not in insp.get_table_names():
        op.create_table(
            "learners",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
    bind.execute(sa.text("INSERT INTO learners (id, name, created_at) SELECT :i, 'Learner', CURRENT_TIMESTAMP "
                         "WHERE NOT EXISTS (SELECT 1 FROM learners WHERE id = :i)"), {"i": DEFAULT})
    if "learner_id" not in {c["name"] for c in insp.get_columns("notebooks")}:
        with op.batch_alter_table("notebooks") as batch:
            batch.add_column(sa.Column("learner_id", sa.String(), nullable=False, server_default=DEFAULT))
            batch.create_foreign_key("fk_notebooks_learner_id", "learners", ["learner_id"], ["id"])
            batch.create_index("ix_notebooks_learner_id", ["learner_id"])


def downgrade() -> None:
    with op.batch_alter_table("notebooks") as batch:
        batch.drop_index("ix_notebooks_learner_id")
        batch.drop_constraint("fk_notebooks_learner_id", type_="foreignkey")
        batch.drop_column("learner_id")
    op.drop_table("learners")
