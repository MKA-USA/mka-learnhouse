"""MKA fork: add mka_user_attributes, mka_user_attributes_audit, mka_roster_override

Revision ID: mka_20261004_user_attributes
Revises: mka_20261004_user_profile
Create Date: 2026-10-04

NOTE: this revision has never been deployed anywhere, so columns added during development
(`stale`, `verified_hd`, roster `org_id`) were edited in place rather than via a follow-up revision.

Idempotent on purpose (same reason as mka_20261004_user_profile): the API
bootstraps missing tables and the indexes in the models' ``__table_args__`` with
``SQLModel.metadata.create_all`` at startup, so ``alembic upgrade head`` may find
them already present. Every create/drop is guarded by an inspector check. Table
and index names must stay identical to ``src/db/mka_user_attributes.py``.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "mka_20261004_user_attributes"
down_revision: Union[str, None] = "mka_20261004_user_profile"  # re-verify with `alembic heads` before merging
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ATTRS = "mka_user_attributes"
AUDIT = "mka_user_attributes_audit"
ROSTER = "mka_roster_override"

ATTRS_INDEXES = {
    "ix_mka_user_attributes_eff_status": "eff_status",
    "ix_mka_user_attributes_eff_level": "eff_level",
    "ix_mka_user_attributes_eff_department": "eff_department",
    "ix_mka_user_attributes_eff_region": "eff_region",
    "ix_mka_user_attributes_eff_majlis": "eff_majlis",
    "ix_mka_user_attributes_email_seen": "email_seen",
}
AUDIT_INDEXES = {"ix_mka_user_attributes_audit_user_id": "user_id"}

_JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _existing_indexes(table: str) -> set:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table):
        return set()
    return {ix["name"] for ix in inspector.get_indexes(table)}


def _ensure_indexes(table: str, wanted: dict) -> None:
    existing = _existing_indexes(table)
    for name, column in wanted.items():
        if name not in existing:
            op.create_index(name, table, [column])


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())

    if not inspector.has_table(ATTRS):
        op.create_table(
            ATTRS,
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("email_seen", sa.String(), nullable=False),
            sa.Column("derived", _JSON, nullable=False),
            sa.Column("rules_version", sa.String(), nullable=False),
            sa.Column("derived_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("override", _JSON, nullable=True),
            sa.Column("override_reason", sa.Text(), nullable=True),
            sa.Column("override_by", sa.Integer(), nullable=True),
            sa.Column("override_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("verified_hd", sa.String(), nullable=True),
            sa.Column("stale", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("effective", _JSON, nullable=False),
            sa.Column("eff_status", sa.String(), nullable=True),
            sa.Column("eff_is_officeholder", sa.Boolean(), nullable=True),
            sa.Column("eff_level", sa.String(), nullable=True),
            sa.Column("eff_department", sa.String(), nullable=True),
            sa.Column("eff_role", sa.String(), nullable=True),
            sa.Column("eff_majlis", sa.String(), nullable=True),
            sa.Column("eff_region", sa.String(), nullable=True),
        )
    _ensure_indexes(ATTRS, ATTRS_INDEXES)

    if not sa.inspect(op.get_bind()).has_table(AUDIT):
        op.create_table(
            AUDIT,
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
            sa.Column("actor_user_id", sa.Integer(), nullable=True),
            sa.Column("action", sa.String(), nullable=False),
            sa.Column("before", _JSON, nullable=True),
            sa.Column("after", _JSON, nullable=True),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        )
    _ensure_indexes(AUDIT, AUDIT_INDEXES)

    if not sa.inspect(op.get_bind()).has_table(ROSTER):
        op.create_table(
            ROSTER,
            sa.Column("org_id", sa.Integer(), sa.ForeignKey("organization.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("email", sa.String(), primary_key=True),
            sa.Column("attributes", _JSON, nullable=False),
            sa.Column("source", sa.String(), nullable=False),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_by", sa.Integer(), nullable=True),
        )


def downgrade() -> None:
    for table, indexes in ((AUDIT, AUDIT_INDEXES), (ATTRS, ATTRS_INDEXES)):
        inspector = sa.inspect(op.get_bind())
        if not inspector.has_table(table):
            continue
        existing = {ix["name"] for ix in inspector.get_indexes(table)}
        for name in indexes:
            if name in existing:
                op.drop_index(name, table_name=table)
        op.drop_table(table)
    if sa.inspect(op.get_bind()).has_table(ROSTER):
        op.drop_table(ROSTER)
