"""MKA fork: add mka_user_profile (Majlis/Region reporting)

Revision ID: mka_20261004_user_profile
Revises: b1c2d3e4f5a6
Create Date: 2026-10-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "mka_20261004_user_profile"
down_revision: Union[str, None] = "b1c2d3e4f5a6"  # re-verify with `alembic heads` before merging
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mka_user_profile",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("majlis", sa.String(), nullable=False),
        sa.Column("region", sa.String(), nullable=False),
        sa.Column("mobile", sa.String(), nullable=True),
        sa.Column("amc_id", sa.String(), nullable=True),
        sa.Column("tanzeem", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False, server_default=""),
        sa.Column("updated_at", sa.String(), nullable=False, server_default=""),
    )
    op.create_index(
        "ix_mka_user_profile_amc_id", "mka_user_profile", ["amc_id"],
        unique=True, postgresql_where=sa.text("amc_id IS NOT NULL"),
    )
    op.create_index("ix_mka_user_profile_region", "mka_user_profile", ["region"])
    op.create_index("ix_mka_user_profile_majlis", "mka_user_profile", ["majlis"])


def downgrade() -> None:
    op.drop_index("ix_mka_user_profile_majlis", table_name="mka_user_profile")
    op.drop_index("ix_mka_user_profile_region", table_name="mka_user_profile")
    op.drop_index("ix_mka_user_profile_amc_id", table_name="mka_user_profile")
    op.drop_table("mka_user_profile")
