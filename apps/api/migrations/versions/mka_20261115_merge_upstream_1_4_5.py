"""MKA fork: merge the upstream 1.4.5 alembic head with the MKA head

Revision ID: mka_20261115_merge_upstream_1_4_5
Revises: mka_20261013_purge_audience_rag, f5a8b3d0c2e4
Create Date: 2026-11-15

Upstream 1.4.5 added a new head (``f5a8b3d0c2e4``, analytics tables) while the fork head is
``mka_20261013_purge_audience_rag``. This revision joins them into a single head so ``alembic upgrade head``
keeps working. It changes no schema. Downgrading it only splits the heads again; it never touches
``mka_20261004_user_profile`` or any MKA table.
"""
from collections.abc import Sequence

revision: str = "mka_20261115_merge_upstream_1_4_5"
down_revision: str | Sequence[str] | None = (
    "mka_20261013_purge_audience_rag",
    "f5a8b3d0c2e4",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
