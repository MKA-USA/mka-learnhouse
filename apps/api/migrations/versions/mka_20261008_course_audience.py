"""MKA fork: add mka_course_audience

Revision ID: mka_20261008_course_audience
Revises: mka_20261007_identity_sync
Create Date: 2026-10-08

Idempotent on purpose (same reason as the other mka_* migrations): the API bootstraps missing tables with
``SQLModel.metadata.create_all`` at startup, so ``alembic upgrade head`` may find the table already present.
Names must stay identical to ``src/db/mka_course_audience.py``.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "mka_20261008_course_audience"
down_revision: str | None = "mka_20261007_identity_sync"  # re-verify with `alembic heads` before merging
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

TABLE = "mka_course_audience"


def _has(table: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table)


def upgrade() -> None:
    if _has(TABLE):
        return
    op.create_table(
        TABLE,
        sa.Column("course_id", sa.Integer(), sa.ForeignKey("course.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("org_id", sa.Integer(), sa.ForeignKey("organization.id", ondelete="CASCADE"), nullable=False),
        sa.Column("audience", sa.String(), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("rule", _JSON, nullable=True),
        sa.Column("usergroup_id", sa.Integer(), sa.ForeignKey("usergroup.id", ondelete="SET NULL"), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("audience IN ('everyone','officeholders','custom')", name="ck_mka_course_audience_audience"),
        sa.CheckConstraint("mode IN ('required','optin')", name="ck_mka_course_audience_mode"),
    )
    op.create_index("ix_mka_course_audience_org_id", TABLE, ["org_id"])


def downgrade() -> None:
    if _has(TABLE):
        op.drop_table(TABLE)
