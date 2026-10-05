"""Add moderation_flag table

Advisory AI-moderation flags (staff review queue). Stores ids, scores and a
truncated content hash only; never the flagged text.

Revision ID: f1a2b3c4d5e7
Revises: mka_20261005_automation
Create Date: 2026-10-04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f1a2b3c4d5e7"
down_revision: Union[str, None] = "mka_20261005_automation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLModel.create_all() may already have created the table on some DBs.
    if "moderation_flag" in sa.inspect(op.get_bind()).get_table_names():
        return

    op.create_table(
        "moderation_flag",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("flag_uuid", sa.String(100), nullable=False),
        sa.Column("org_id", sa.Integer(), sa.ForeignKey("organization.id", ondelete="CASCADE"), nullable=False),
        sa.Column("content_type", sa.String(32), nullable=False),
        sa.Column("content_uuid", sa.String(100), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("author_user_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("scores", sa.JSON(), nullable=True),
        sa.Column("reasons", sa.JSON(), nullable=True),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("reviewed_by", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.String(40), nullable=True),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.UniqueConstraint(
            "org_id", "content_type", "content_uuid", "content_hash",
            name="uq_moderation_flag_content_version",
        ),
    )
    op.create_index("ix_moderation_flag_flag_uuid", "moderation_flag", ["flag_uuid"], unique=True)
    op.create_index("ix_moderation_flag_org_id", "moderation_flag", ["org_id"])
    op.create_index("ix_moderation_flag_content_uuid", "moderation_flag", ["content_uuid"])
    op.create_index("ix_moderation_flag_author_user_id", "moderation_flag", ["author_user_id"])
    op.create_index("ix_moderation_flag_status", "moderation_flag", ["status"])
    op.create_index("ix_moderation_flag_org_status", "moderation_flag", ["org_id", "status"])


def downgrade() -> None:
    if "moderation_flag" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("moderation_flag")
