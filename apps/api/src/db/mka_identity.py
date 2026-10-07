"""MKA fork: identity-sync bindings (spec 2026-10-07 section 3.A).

The binding is by KEY, never by name: an admin may rename a managed group or role in the UI and the sync keeps working.
Every table carries ``org_id`` (NOT NULL, FK organization ON DELETE CASCADE). No table references ``user`` (nothing here
is per-person), so the demo-teardown / GDPR FK policies are unaffected. Names/indexes MUST match
``migrations/versions/mka_20261007_identity_sync.py``.

* ``mka_managed_role``  (org_id, key='mohtamim') -> the org role the sync manages, plus the rights version applied.
* ``mka_managed_group`` (org_id, key)            -> the usergroup the sync manages (``majlis:albany`` ...).
* ``mka_identity_sync_state`` one row per org: when the last APPLIED backfill ran and its counts.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

_JSON = JSON().with_variant(JSONB(), "postgresql")


class MkaManagedRole(SQLModel, table=True):
    __tablename__ = "mka_managed_role"

    org_id: int = Field(
        sa_column=Column(Integer, ForeignKey("organization.id", ondelete="CASCADE"), primary_key=True)
    )
    key: str = Field(sa_column=Column(String, primary_key=True))
    role_id: int = Field(sa_column=Column(Integer, ForeignKey("role.id", ondelete="CASCADE"), nullable=False))
    rights_version: int = Field(sa_column=Column(Integer, nullable=False))


class MkaManagedGroup(SQLModel, table=True):
    __tablename__ = "mka_managed_group"

    org_id: int = Field(
        sa_column=Column(Integer, ForeignKey("organization.id", ondelete="CASCADE"), primary_key=True)
    )
    key: str = Field(sa_column=Column(String, primary_key=True))
    usergroup_id: int = Field(
        sa_column=Column(Integer, ForeignKey("usergroup.id", ondelete="CASCADE"), nullable=False)
    )


class MkaIdentitySyncState(SQLModel, table=True):
    __tablename__ = "mka_identity_sync_state"

    org_id: int = Field(
        sa_column=Column(Integer, ForeignKey("organization.id", ondelete="CASCADE"), primary_key=True)
    )
    last_sync_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(), nullable=True))
    last_counts: Optional[dict] = Field(default=None, sa_column=Column(_JSON, nullable=True))
