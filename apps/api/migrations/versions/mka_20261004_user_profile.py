"""MKA fork: add mka_user_profile (Majlis/Region reporting)

Revision ID: mka_20261004_user_profile
Revises: b1c2d3e4f5a6
Create Date: 2026-10-04

Idempotent on purpose: the API bootstraps missing tables (and the indexes in
the model's ``__table_args__``) with ``SQLModel.metadata.create_all`` at
startup, so a manual ``alembic upgrade head`` may find the table and indexes
already present. Every create/drop below is guarded by an inspector check.
Index names must stay identical to ``src/db/mka_user_profile.py``.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "mka_20261004_user_profile"
down_revision: Union[str, None] = "b1c2d3e4f5a6"  # re-verify with `alembic heads` before merging
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE = "mka_user_profile"


def _index_names(inspector) -> set:
    return {ix["name"] for ix in inspector.get_indexes(TABLE)}


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(TABLE):
        op.create_table(
            TABLE,
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("majlis", sa.String(), nullable=False),
            sa.Column("region", sa.String(), nullable=False),
            sa.Column("mobile", sa.String(), nullable=True),
            sa.Column("amc_id", sa.String(), nullable=True),
            sa.Column("tanzeem", sa.String(), nullable=True),
            sa.Column("created_at", sa.String(), nullable=False, server_default=""),
            sa.Column("updated_at", sa.String(), nullable=False, server_default=""),
        )
        inspector = sa.inspect(op.get_bind())
    existing = _index_names(inspector)
    if "ix_mka_user_profile_amc_id" not in existing:
        op.create_index(
            "ix_mka_user_profile_amc_id", TABLE, ["amc_id"],
            unique=True, postgresql_where=sa.text("amc_id IS NOT NULL"),
        )
    if "ix_mka_user_profile_region" not in existing:
        op.create_index("ix_mka_user_profile_region", TABLE, ["region"])
    if "ix_mka_user_profile_majlis" not in existing:
        op.create_index("ix_mka_user_profile_majlis", TABLE, ["majlis"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(TABLE):
        return
    existing = _index_names(inspector)
    for name in (
        "ix_mka_user_profile_majlis",
        "ix_mka_user_profile_region",
        "ix_mka_user_profile_amc_id",
    ):
        if name in existing:
            op.drop_index(name, table_name=TABLE)
    op.drop_table(TABLE)
