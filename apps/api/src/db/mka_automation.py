"""MKA fork: compliance automation tables (spec 2026-10-05 section 3).

Every table carries ``org_id`` (NOT NULL, FK organization ON DELETE CASCADE): a review found an org-less table
once; do not repeat it. ``user_id`` FKs cascade on user hard-delete (the demo-teardown FK policy requires it and
it keeps GDPR hard-deletes complete). Names/indexes MUST match ``migrations/versions/mka_20261005_automation.py``.

* ``mka_automation_event``    inbound webhook deliveries + internal events (auto-enrol). Replay/dup protection is
                              UNIQUE(org_id, delivery_id). NEVER stores answers or payload bodies.
* ``mka_automation_send_log`` one row per outgoing email, inserted ``queued`` BEFORE sending (claim-before-send);
                              UNIQUE(org_id, kind, dedupe_key) makes retries/replays/concurrent runs idempotent.

Timestamps are naive UTC (``datetime.now(timezone.utc).replace(tzinfo=None)``).
``cycle_id`` / ``course_id`` are plain integers (no FK): the log is an audit trail and must outlive a deleted
course or cycle.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, false
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


EVENT_STATUSES = ("received", "processed", "ignored", "skipped_unpublished", "error")
SEND_KINDS = ("receipt", "allset", "reminder", "digest")
SEND_STATUSES = ("queued", "sent", "failed", "suppressed")


class MkaAutomationEvent(SQLModel, table=True):
    __tablename__ = "mka_automation_event"
    __table_args__ = (
        # NULL delivery ids (internal events) never collide on any supported database.
        UniqueConstraint("org_id", "delivery_id", name="uq_mka_automation_event_org_delivery"),
        Index("ix_mka_automation_event_org_event_received", "org_id", "event", "received_at"),
        Index("ix_mka_automation_event_user_id", "user_id"),
        Index("ix_mka_automation_event_org_assignment_user", "org_id", "assignment_uuid", "user_id"),
        Index("ix_mka_automation_event_received_at", "received_at"),
    )

    id: Optional[int] = Field(default=None, sa_column=Column(Integer, primary_key=True, autoincrement=True))
    org_id: int = Field(sa_column=Column(Integer, ForeignKey("organization.id", ondelete="CASCADE"), nullable=False))
    delivery_id: Optional[str] = Field(default=None, sa_column=Column(String, nullable=True))
    event: str = Field(sa_column=Column(String, nullable=False))
    user_id: Optional[int] = Field(
        default=None, sa_column=Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=True)
    )
    user_uuid: Optional[str] = Field(default=None, sa_column=Column(String, nullable=True))
    course_uuid: Optional[str] = Field(default=None, sa_column=Column(String, nullable=True))
    assignment_uuid: Optional[str] = Field(default=None, sa_column=Column(String, nullable=True))
    status: str = Field(default="received", sa_column=Column(String, nullable=False))
    note: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    received_at: datetime = Field(default_factory=utcnow, sa_column=Column(DateTime, nullable=False))


class MkaAutomationSendLog(SQLModel, table=True):
    __tablename__ = "mka_automation_send_log"
    __table_args__ = (
        UniqueConstraint("org_id", "kind", "dedupe_key", name="uq_mka_automation_send_log_dedupe"),
        # weekly-cap query: (org, kind, person, time window)
        Index("ix_mka_automation_send_log_cap", "org_id", "kind", "intended_email", "created_at"),
        # sweep queries ("which sign-offs have no receipt row") and per-run reporting
        Index("ix_mka_automation_send_log_org_kind_created", "org_id", "kind", "created_at"),
        Index("ix_mka_automation_send_log_user_id", "user_id"),
        Index("ix_mka_automation_send_log_intended_email", "intended_email"),
        Index("ix_mka_automation_send_log_created_at", "created_at"),
    )

    id: Optional[int] = Field(default=None, sa_column=Column(Integer, primary_key=True, autoincrement=True))
    org_id: int = Field(sa_column=Column(Integer, ForeignKey("organization.id", ondelete="CASCADE"), nullable=False))
    kind: str = Field(sa_column=Column(String, nullable=False))
    dedupe_key: str = Field(sa_column=Column(String, nullable=False))
    user_id: Optional[int] = Field(
        default=None, sa_column=Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=True)
    )
    to_email: str = Field(sa_column=Column(String, nullable=False))  # who was actually mailed (the test address in test mode)
    intended_email: str = Field(sa_column=Column(String, nullable=False))  # who it was meant for (lower-cased)
    subject: str = Field(sa_column=Column(String, nullable=False))
    status: str = Field(default="queued", sa_column=Column(String, nullable=False))
    test_mode: bool = Field(
        default=False, sa_column=Column(Boolean, nullable=False, server_default=false(), default=False)
    )
    cycle_id: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=True))
    course_id: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=True))
    error: Optional[str] = Field(default=None, sa_column=Column(String, nullable=True))
    created_at: datetime = Field(default_factory=utcnow, sa_column=Column(DateTime, nullable=False))
    sent_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime, nullable=True))
