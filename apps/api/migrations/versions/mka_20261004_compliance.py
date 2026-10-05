"""MKA fork: add mka_compliance_cycle, mka_compliance_cycle_course, mka_compliance_expected

Revision ID: mka_20261004_compliance
Revises: mka_20261004_user_attributes
Create Date: 2026-10-04

Idempotent on purpose (same reason as the other mka_* migrations): the API bootstraps missing tables and the
indexes/constraints in the models' ``__table_args__`` with ``SQLModel.metadata.create_all`` at startup, so
``alembic upgrade head`` may find them already present. Every create/drop is guarded by an inspector check.
Table, index and constraint names must stay identical to ``src/db/mka_compliance.py``.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "mka_20261004_compliance"
down_revision: Union[str, None] = "mka_20261004_user_attributes"  # re-verify with `alembic heads` before merging
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CYCLE = "mka_compliance_cycle"
CYCLE_COURSE = "mka_compliance_cycle_course"
EXPECTED = "mka_compliance_expected"

CYCLE_INDEXES = {"ix_mka_compliance_cycle_org_id": ["org_id"]}
CYCLE_COURSE_INDEXES = {
    "ix_mka_compliance_cycle_course_org_id": ["org_id"],
    "ix_mka_compliance_cycle_course_course_id": ["course_id"],
    "ix_mka_compliance_cycle_course_course_uuid": ["course_uuid"],
}
EXPECTED_INDEXES = {
    "ix_mka_compliance_expected_org_cycle": ["org_id", "cycle_id"],
    "ix_mka_compliance_expected_cycle_dept_region": ["cycle_id", "department", "region"],
    "ix_mka_compliance_expected_email": ["email"],
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
    if not _has(CYCLE):
        op.create_table(
            CYCLE,
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("org_id", sa.Integer(), sa.ForeignKey("organization.id", ondelete="CASCADE"), nullable=False),
            sa.Column("label", sa.String(), nullable=False),
            sa.Column("starts_on", sa.Date(), nullable=False),
            sa.Column("deadline_on", sa.Date(), nullable=False),
            sa.UniqueConstraint("org_id", "label", name="uq_mka_compliance_cycle_org_label"),
        )
    _ensure_indexes(CYCLE, CYCLE_INDEXES)

    if not _has(CYCLE_COURSE):
        op.create_table(
            CYCLE_COURSE,
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("org_id", sa.Integer(), sa.ForeignKey("organization.id", ondelete="CASCADE"), nullable=False),
            sa.Column("cycle_id", sa.Integer(), sa.ForeignKey(f"{CYCLE}.id", ondelete="CASCADE"), nullable=False),
            sa.Column("course_id", sa.Integer(), sa.ForeignKey("course.id", ondelete="CASCADE"), nullable=False),
            sa.Column("course_uuid", sa.String(), nullable=False),
            sa.Column("kind", sa.String(), nullable=False),
            sa.Column("department", sa.String(), nullable=True),
            sa.Column("signoff_assignment_id", sa.Integer(), sa.ForeignKey("assignment.id", ondelete="SET NULL"), nullable=True),
            sa.Column("contact_check_assignment_id", sa.Integer(), sa.ForeignKey("assignment.id", ondelete="SET NULL"), nullable=True),
            sa.UniqueConstraint("cycle_id", "course_id", name="uq_mka_compliance_cycle_course"),
        )
    _ensure_indexes(CYCLE_COURSE, CYCLE_COURSE_INDEXES)

    if not _has(EXPECTED):
        op.create_table(
            EXPECTED,
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("org_id", sa.Integer(), sa.ForeignKey("organization.id", ondelete="CASCADE"), nullable=False),
            sa.Column("cycle_id", sa.Integer(), sa.ForeignKey(f"{CYCLE}.id", ondelete="CASCADE"), nullable=False),
            sa.Column("email", sa.String(), nullable=False),
            sa.Column("department", sa.String(), nullable=False, server_default=""),
            sa.Column("level", sa.String(), nullable=False),
            sa.Column("majlis", sa.String(), nullable=True),
            sa.Column("region", sa.String(), nullable=True),
            sa.Column("role_title", sa.String(), nullable=False, server_default=""),
            sa.Column("person_name", sa.String(), nullable=True),
            sa.Column("appointed_on", sa.Date(), nullable=True),
            sa.Column("source", sa.String(), nullable=True),
            sa.Column("formula_unconfirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.UniqueConstraint(
                "cycle_id", "email", "department", "level", "role_title", name="uq_mka_compliance_expected_role"
            ),
        )
    _ensure_indexes(EXPECTED, EXPECTED_INDEXES)


def downgrade() -> None:
    for table, indexes in (
        (EXPECTED, EXPECTED_INDEXES), (CYCLE_COURSE, CYCLE_COURSE_INDEXES), (CYCLE, CYCLE_INDEXES),
    ):
        if not _has(table):
            continue
        existing = _existing_indexes(table)
        for name in indexes:
            if name in existing:
                op.drop_index(name, table_name=table)
        op.drop_table(table)
