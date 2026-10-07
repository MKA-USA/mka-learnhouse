"""MKA fork: add mka_managed_role, mka_managed_group, mka_identity_sync_state

Revision ID: mka_20261007_identity_sync
Revises: f1a2b3c4d5e7
Create Date: 2026-10-07

Idempotent on purpose (same reason as the other mka_* migrations): the API bootstraps missing tables with
``SQLModel.metadata.create_all`` at startup, so ``alembic upgrade head`` may find them already present. Every
create/drop is guarded by an inspector check. Names must stay identical to ``src/db/mka_identity.py``.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "mka_20261007_identity_sync"
down_revision: Union[str, None] = "f1a2b3c4d5e7"  # re-verify with `alembic heads` before merging
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

ROLE = "mka_managed_role"
GROUP = "mka_managed_group"
STATE = "mka_identity_sync_state"


def _has(table: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table)


def upgrade() -> None:
    if not _has(ROLE):
        op.create_table(
            ROLE,
            sa.Column("org_id", sa.Integer(), sa.ForeignKey("organization.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("key", sa.String(), primary_key=True),
            sa.Column("role_id", sa.Integer(), sa.ForeignKey("role.id", ondelete="CASCADE"), nullable=False),
            sa.Column("rights_version", sa.Integer(), nullable=False),
        )
    if not _has(GROUP):
        op.create_table(
            GROUP,
            sa.Column("org_id", sa.Integer(), sa.ForeignKey("organization.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("key", sa.String(), primary_key=True),
            sa.Column("usergroup_id", sa.Integer(), sa.ForeignKey("usergroup.id", ondelete="CASCADE"), nullable=False),
        )
    if not _has(STATE):
        op.create_table(
            STATE,
            sa.Column("org_id", sa.Integer(), sa.ForeignKey("organization.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("last_sync_at", sa.DateTime(), nullable=True),
            sa.Column("last_counts", _JSON, nullable=True),
        )


def downgrade() -> None:
    for table in (STATE, GROUP, ROLE):
        if _has(table):
            op.drop_table(table)
