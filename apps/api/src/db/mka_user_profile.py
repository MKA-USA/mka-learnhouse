"""MKA fork: one-to-one profile row for Majlis/Region reporting.

Kept in a side table (not columns on `user`) so upstream's User model and
table are never modified. A user without a row has an incomplete profile.
"""

from typing import Optional

from sqlalchemy import Column, ForeignKey, Index, Integer, text
from sqlmodel import Field, SQLModel


class MkaUserProfile(SQLModel, table=True):
    __tablename__ = "mka_user_profile"
    __table_args__ = (
        # Partial on Postgres (NULL AMC IDs never collide). SQLite ignores the
        # dialect-specific clause; NULLs are already distinct there.
        Index(
            "ix_mka_user_profile_amc_id",
            "amc_id",
            unique=True,
            postgresql_where=text("amc_id IS NOT NULL"),
        ),
        Index("ix_mka_user_profile_region", "region"),
        Index("ix_mka_user_profile_majlis", "majlis"),
    )

    user_id: int = Field(
        sa_column=Column(
            Integer, ForeignKey("user.id", ondelete="CASCADE"), primary_key=True
        )
    )
    majlis: str
    region: str
    mobile: Optional[str] = None
    amc_id: Optional[str] = None
    tanzeem: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""
