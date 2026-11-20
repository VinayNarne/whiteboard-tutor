"""(page_id, seq) is unique: two events of one page can never share a sequence number.

Replay is "all events of a page in seq order", so a duplicate seq makes the order ambiguous. The app now takes the next seq inside the
insert transaction (backend/event_store.py); this index is what makes a lost race an error instead of a silently ambiguous page.

If a database already holds duplicates (the real one did not, checked 2026-10-08), the events of each affected page are renumbered
1..N in their existing order (seq, then timestamp, then id) before the index is created, so nothing is lost and the order is kept.
Idempotent: an existing index with the same name is left alone.

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    pages = {r[0] for r in bind.execute(sa.text("SELECT page_id FROM page_events GROUP BY page_id, seq HAVING COUNT(*) > 1")).fetchall()}
    for page_id in sorted(pages):
        ids = [r[0] for r in bind.execute(sa.text("SELECT id FROM page_events WHERE page_id = :p ORDER BY seq, timestamp, id"), {"p": page_id}).fetchall()]
        for n, event_id in enumerate(ids, start=1):
            bind.execute(sa.text("UPDATE page_events SET seq = :n WHERE id = :i"), {"n": n, "i": event_id})
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_page_events_page_seq ON page_events (page_id, seq)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_page_events_page_seq")
