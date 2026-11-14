"""MKA fork: purge RAG index rows of activities that contain audience sections

Revision ID: mka_20261013_purge_audience_rag
Revises: mka_20261011_merge_upstream
Create Date: 2026-10-13

Before ``services/mka/rag_audience.py`` the shared per-course RAG index embedded ``mkaAudience`` (restricted) lesson text. This
deletes the ``course_embedding`` rows of every activity whose content mentions ``mkaAudience``. Re-indexing is automatic and needs
no marker: the periodic RAG backfill (``services/ai/rag/scheduler.py``) treats an activity with no index rows as never indexed and
re-queues it (now through the audience guard). No network or embedding calls here. Idempotent; no-op when the tables or columns
are missing. Downgrade is a no-op (purged rows are rebuilt from content by the scheduler).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "mka_20261013_purge_audience_rag"
down_revision: str | None = "mka_20261011_merge_upstream"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if not (insp.has_table("course_embedding") and insp.has_table("activity")):
        return
    if "activity_id" not in {c["name"] for c in insp.get_columns("course_embedding")}:
        return
    if "content" not in {c["name"] for c in insp.get_columns("activity")}:
        return
    op.execute(sa.text(
        "DELETE FROM course_embedding WHERE activity_id IN "
        "(SELECT id FROM activity WHERE CAST(content AS TEXT) LIKE '%mkaAudience%')"
    ))


def downgrade() -> None:
    pass
