"""MKA fork: per-course audience (spec 2026-10-08-mka-course-audience-design.md section 3.A).

One row per course that has an MKA audience. A course with NO row behaves exactly as upstream. ``usergroup_id`` is the
managed ``course:<uuid>`` usergroup (see ``mka_managed_group``); ``updated_by`` is a plain id (no FK to ``user``: nothing here
may block account deletion). Names/constraints MUST match ``migrations/versions/mka_20261008_course_audience.py``.
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

_JSON = JSON().with_variant(JSONB(), "postgresql")


class MkaCourseAudience(SQLModel, table=True):
    __tablename__ = "mka_course_audience"
    __table_args__ = (
        CheckConstraint("audience IN ('everyone','officeholders','custom')", name="ck_mka_course_audience_audience"),
        CheckConstraint("mode IN ('required','optin')", name="ck_mka_course_audience_mode"),
        Index("ix_mka_course_audience_org_id", "org_id"),
    )

    course_id: int = Field(sa_column=Column(Integer, ForeignKey("course.id", ondelete="CASCADE"), primary_key=True))
    org_id: int = Field(sa_column=Column(Integer, ForeignKey("organization.id", ondelete="CASCADE"), nullable=False))
    audience: str = Field(sa_column=Column(String, nullable=False))
    mode: str = Field(sa_column=Column(String, nullable=False))
    rule: dict | None = Field(default=None, sa_column=Column(_JSON, nullable=True))
    usergroup_id: int | None = Field(
        default=None, sa_column=Column(Integer, ForeignKey("usergroup.id", ondelete="SET NULL"), nullable=True)
    )
    updated_by: int | None = Field(default=None, sa_column=Column(Integer, nullable=True))
    updated_at: datetime | None = Field(default=None, sa_column=Column(DateTime(), nullable=True))
