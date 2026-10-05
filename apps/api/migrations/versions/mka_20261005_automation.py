"""MKA fork: add mka_automation_event, mka_automation_send_log

Revision ID: mka_20261005_automation
Revises: mka_20261004_compliance
Create Date: 2026-10-05

Idempotent on purpose (same reason as the other mka_* migrations): the API bootstraps missing tables and the
indexes/constraints in the models' ``__table_args__`` with ``SQLModel.metadata.create_all`` at startup, so
``alembic upgrade head`` may find them already present. Every create/drop is guarded by an inspector check.
Table, index and constraint names must stay identical to ``src/db/mka_automation.py``.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "mka_20261005_automation"
down_revision: Union[str, None] = "mka_20261004_compliance"  # re-verify with `alembic heads` before merging
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EVENT = "mka_automation_event"
SEND_LOG = "mka_automation_send_log"

EVENT_INDEXES = {
    "ix_mka_automation_event_org_event_received": ["org_id", "event", "received_at"],
    "ix_mka_automation_event_user_id": ["user_id"],
    "ix_mka_automation_event_org_assignment_user": ["org_id", "assignment_uuid", "user_id"],
    "ix_mka_automation_event_received_at": ["received_at"],
}
SEND_LOG_INDEXES = {
    "ix_mka_automation_send_log_cap": ["org_id", "kind", "intended_email", "created_at"],
    "ix_mka_automation_send_log_org_kind_created": ["org_id", "kind", "created_at"],
    "ix_mka_automation_send_log_user_id": ["user_id"],
    "ix_mka_automation_send_log_intended_email": ["intended_email"],
    "ix_mka_automation_send_log_created_at": ["created_at"],
}


def _existing_indexes(table: str) -> set:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table):
        return set()
    return {ix["name"] for ix in inspector.get_indexes(table)}


def _ensure_indexes(table: str, wanted: dict) -> None:
    existing = _existing_indexes(table)
    for name, columns in wanted.items():
        if name not in existing:
            op.create_index(name, table, columns)


def _has(table: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table)


def upgrade() -> None:
    if not _has(EVENT):
        op.create_table(
            EVENT,
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("org_id", sa.Integer(), sa.ForeignKey("organization.id", ondelete="CASCADE"), nullable=False),
            sa.Column("delivery_id", sa.String(), nullable=True),
            sa.Column("event", sa.String(), nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=True),
            sa.Column("user_uuid", sa.String(), nullable=True),
            sa.Column("course_uuid", sa.String(), nullable=True),
            sa.Column("assignment_uuid", sa.String(), nullable=True),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("received_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("org_id", "delivery_id", name="uq_mka_automation_event_org_delivery"),
        )
    _ensure_indexes(EVENT, EVENT_INDEXES)

    if not _has(SEND_LOG):
        op.create_table(
            SEND_LOG,
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("org_id", sa.Integer(), sa.ForeignKey("organization.id", ondelete="CASCADE"), nullable=False),
            sa.Column("kind", sa.String(), nullable=False),
            sa.Column("dedupe_key", sa.String(), nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=True),
            sa.Column("to_email", sa.String(), nullable=False),
            sa.Column("intended_email", sa.String(), nullable=False),
            sa.Column("subject", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("test_mode", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("cycle_id", sa.Integer(), nullable=True),
            sa.Column("course_id", sa.Integer(), nullable=True),
            sa.Column("error", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("sent_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("org_id", "kind", "dedupe_key", name="uq_mka_automation_send_log_dedupe"),
        )
    _ensure_indexes(SEND_LOG, SEND_LOG_INDEXES)


def downgrade() -> None:
    for table, indexes in ((SEND_LOG, SEND_LOG_INDEXES), (EVENT, EVENT_INDEXES)):
        if not _has(table):
            continue
        existing = _existing_indexes(table)
        for name in indexes:
            if name in existing:
                op.drop_index(name, table_name=table)
        op.drop_table(table)
