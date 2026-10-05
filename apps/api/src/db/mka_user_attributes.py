"""MKA fork: server-derived identity attributes (spec A1-A2).

Separate from ``mka_user_profile`` (self-reported, user-editable): these rows
are derived from the verified Google email plus admin/roster overrides and are
NEVER writable by the user.

``derived`` is the raw parser output; ``eff_*`` columns are the denormalised
EFFECTIVE attributes (admin override > roster override > parser) kept so that
admin filtering/pagination and audience counts run in SQL. They are rewritten
by ``services/mka/attributes.py`` whenever any input changes.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    false,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

# NOTE: actor/override_by/updated_by are plain integers (no FK): a SET NULL FK to user would break the
# demo-teardown FK policy test, and the GDPR path (delete_attributes) nulls them explicitly.
_JSON = JSON().with_variant(JSONB(), "postgresql")
# Nullable JSON columns: Python None must be SQL NULL (not JSON null) so IS NULL filters work.
_JSON_NULL = JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql")


class MkaUserAttributes(SQLModel, table=True):
    __tablename__ = "mka_user_attributes"
    __table_args__ = (
        Index("ix_mka_user_attributes_eff_status", "eff_status"),
        Index("ix_mka_user_attributes_eff_level", "eff_level"),
        Index("ix_mka_user_attributes_eff_department", "eff_department"),
        Index("ix_mka_user_attributes_eff_region", "eff_region"),
        Index("ix_mka_user_attributes_eff_majlis", "eff_majlis"),
        Index("ix_mka_user_attributes_email_seen", "email_seen"),
    )

    user_id: int = Field(
        sa_column=Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), primary_key=True)
    )
    email_seen: str = Field(sa_column=Column(String, nullable=False))
    derived: dict = Field(sa_column=Column(_JSON, nullable=False))
    rules_version: str = Field(sa_column=Column(String, nullable=False))
    derived_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    override: Optional[dict] = Field(default=None, sa_column=Column(_JSON_NULL, nullable=True))
    override_reason: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    override_by: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, nullable=True),
    )
    override_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    # True when the last login refresh failed: reads fail closed until a refresh succeeds.
    stale: bool = Field(default=False, sa_column=Column(Boolean, nullable=False, server_default=false(), default=False))
    # Denormalised effective attributes (see module docstring).
    effective: dict = Field(default_factory=dict, sa_column=Column(_JSON, nullable=False))
    eff_status: Optional[str] = Field(default=None, sa_column=Column(String, nullable=True))
    eff_is_officeholder: Optional[bool] = Field(default=None, sa_column=Column(Boolean, nullable=True))
    eff_level: Optional[str] = Field(default=None, sa_column=Column(String, nullable=True))
    eff_department: Optional[str] = Field(default=None, sa_column=Column(String, nullable=True))
    eff_role: Optional[str] = Field(default=None, sa_column=Column(String, nullable=True))
    eff_majlis: Optional[str] = Field(default=None, sa_column=Column(String, nullable=True))
    eff_region: Optional[str] = Field(default=None, sa_column=Column(String, nullable=True))


class MkaUserAttributesAudit(SQLModel, table=True):
    """Append-only: the service only ever INSERTs here."""

    __tablename__ = "mka_user_attributes_audit"
    __table_args__ = (Index("ix_mka_user_attributes_audit_user_id", "user_id"),)

    id: Optional[int] = Field(default=None, sa_column=Column(Integer, primary_key=True, autoincrement=True))
    user_id: int = Field(
        sa_column=Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    )
    # NULL = system (login hook, bulk recompute, companion token)
    actor_user_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, nullable=True),
    )
    # 'derive' | 'recompute' | 'override_set' | 'override_clear' | 'roster_apply'
    action: str = Field(sa_column=Column(String, nullable=False))
    before: Optional[dict] = Field(default=None, sa_column=Column(_JSON_NULL, nullable=True))
    after: Optional[dict] = Field(default=None, sa_column=Column(_JSON_NULL, nullable=True))
    reason: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=False)
    )


class MkaRosterOverride(SQLModel, table=True):
    """Per-(org, email) override that can be seeded before the user exists."""

    __tablename__ = "mka_roster_override"

    # Per-org: an org admin/token can only ever see or write its own org's rows.
    org_id: int = Field(
        sa_column=Column(Integer, ForeignKey("organization.id", ondelete="CASCADE"), primary_key=True)
    )
    email: str = Field(sa_column=Column(String, primary_key=True))  # lower-cased
    attributes: dict = Field(sa_column=Column(_JSON, nullable=False))
    source: str = Field(sa_column=Column(String, nullable=False))  # 'admin' | 'companion'
    note: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    updated_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    updated_by: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, nullable=True),
    )
