"""AI moderation flags (advisory review aids, staff-only).

One row per (org, content, content-version). Deliberately stores NO content
text: only ids, normalized scores, short generic reasons and a truncated hash of
the scored text (so an edit re-scores but identical text is not scored twice).
"""

from typing import Literal, Optional

from pydantic import BaseModel
from sqlalchemy import JSON, Column, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlmodel import Field, SQLModel

CONTENT_TYPES = ("discussion", "discussion_comment", "assignment_submission", "user_profile")
FLAG_STATUSES = ("open", "reviewed", "dismissed")
FLAG_SEVERITIES = ("medium", "high")

ContentType = Literal["discussion", "discussion_comment", "assignment_submission", "user_profile"]
FlagStatus = Literal["open", "reviewed", "dismissed"]


class ModerationFlag(SQLModel, table=True):
    __tablename__ = "moderation_flag"
    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "content_type",
            "content_uuid",
            "content_hash",
            name="uq_moderation_flag_content_version",
        ),
        Index("ix_moderation_flag_org_status", "org_id", "status"),
        {"extend_existing": True},
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    flag_uuid: str = Field(default="", sa_column=Column(String(100), unique=True, index=True, nullable=False))
    org_id: int = Field(
        sa_column=Column(Integer, ForeignKey("organization.id", ondelete="CASCADE"), index=True, nullable=False)
    )
    content_type: str = Field(sa_column=Column(String(32), nullable=False))
    content_uuid: str = Field(sa_column=Column(String(100), index=True, nullable=False))
    # Truncated SHA-256 of the scored text. Never the text itself.
    content_hash: str = Field(sa_column=Column(String(64), nullable=False))
    author_user_id: int = Field(
        sa_column=Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), index=True, nullable=False)
    )
    kind: str = Field(sa_column=Column(String(32), nullable=False))
    scores: dict = Field(default_factory=dict, sa_column=Column(JSON))
    reasons: list = Field(default_factory=list, sa_column=Column(JSON))
    severity: str = Field(default="medium", sa_column=Column(String(16), nullable=False))
    status: str = Field(default="open", sa_column=Column(String(16), nullable=False, index=True))
    # Plain id (no FK): reviewer deletion must neither cascade away the flag nor
    # block demo teardown; a dangling id simply renders as "unknown reviewer".
    reviewed_by: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=True))
    reviewed_at: Optional[str] = Field(default=None, sa_column=Column(String(40), nullable=True))
    created_at: str = Field(default="", sa_column=Column(String(40), nullable=False))


# ---------------------------------------------------------------------------
# API models (frozen contract consumed by the dashboard)
# ---------------------------------------------------------------------------


class FlagScores(BaseModel):
    pii: float = 0.0
    toxicity: float = 0.0
    spam: float = 0.0
    academic_integrity: Optional[float] = None


class FlagRead(BaseModel):
    flag_uuid: str
    org_id: int
    content_type: str
    content_uuid: str
    author_user_uuid: Optional[str] = None
    kind: str
    severity: str
    scores: FlagScores
    reasons: list[str]
    status: str
    reviewed_by_user_uuid: Optional[str] = None
    reviewed_at: Optional[str] = None
    created_at: str
    # Org-relative app path (e.g. "/community/<uuid>/discussion/<uuid>"); the
    # client prefixes the org. None when the content no longer resolves.
    content_link: Optional[str] = None


class FlagListResponse(BaseModel):
    items: list[FlagRead]
    total: int


class FlagItemsResponse(BaseModel):
    items: list[FlagRead]


class FlagStatusUpdate(BaseModel):
    status: FlagStatus


class AIModerationSettingsUpdate(BaseModel):
    enabled: bool
    surfaces: Optional[list[ContentType]] = None


class AIModerationSettingsRead(BaseModel):
    enabled: bool
    surfaces: list[str]
    # False when the platform operator has not enabled/keyed Jev, so the org
    # toggle has no effect yet.
    provider_available: bool
