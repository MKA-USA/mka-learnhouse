"""MKA fork: native compliance analytics tables (spec 2026-10-04 section 2).

Every table carries ``org_id`` (a review of the attributes work found an org-less table; do not repeat it):
the import API and every read filter on it and the service additionally cross-checks that a referenced course
belongs to the same org. Names/indexes here MUST match ``migrations/versions/mka_20261004_compliance.py``.

* ``mka_compliance_cycle``        one compliance cycle (e.g. "2026-27") per org, label unique per org.
* ``mka_compliance_cycle_course`` the courses that make up a cycle (one general + one per department), plus
                                  the sign-off (attestation) and contact-check assignments.
* ``mka_compliance_expected``     the EXPECTED roster: who is supposed to complete the cycle. It exists so that
                                  people who never signed in (no user row, no enrolment) are visible.
                                  Rows join to ``user`` by ``lower(email)``; a person may hold several roles.
"""

from datetime import date
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    false,
)
from sqlmodel import Field, SQLModel


class MkaComplianceCycle(SQLModel, table=True):
    __tablename__ = "mka_compliance_cycle"
    __table_args__ = (
        UniqueConstraint("org_id", "label", name="uq_mka_compliance_cycle_org_label"),
        Index("ix_mka_compliance_cycle_org_id", "org_id"),
    )

    id: Optional[int] = Field(default=None, sa_column=Column(Integer, primary_key=True, autoincrement=True))
    org_id: int = Field(sa_column=Column(Integer, ForeignKey("organization.id", ondelete="CASCADE"), nullable=False))
    label: str = Field(sa_column=Column(String, nullable=False))
    starts_on: date = Field(sa_column=Column(Date, nullable=False))
    deadline_on: date = Field(sa_column=Column(Date, nullable=False))


class MkaComplianceCycleCourse(SQLModel, table=True):
    __tablename__ = "mka_compliance_cycle_course"
    __table_args__ = (
        UniqueConstraint("cycle_id", "course_id", name="uq_mka_compliance_cycle_course"),
        Index("ix_mka_compliance_cycle_course_org_id", "org_id"),
        Index("ix_mka_compliance_cycle_course_course_id", "course_id"),
        Index("ix_mka_compliance_cycle_course_course_uuid", "course_uuid"),
    )

    id: Optional[int] = Field(default=None, sa_column=Column(Integer, primary_key=True, autoincrement=True))
    org_id: int = Field(sa_column=Column(Integer, ForeignKey("organization.id", ondelete="CASCADE"), nullable=False))
    cycle_id: int = Field(
        sa_column=Column(Integer, ForeignKey("mka_compliance_cycle.id", ondelete="CASCADE"), nullable=False)
    )
    course_id: int = Field(sa_column=Column(Integer, ForeignKey("course.id", ondelete="CASCADE"), nullable=False))
    course_uuid: str = Field(sa_column=Column(String, nullable=False))
    kind: str = Field(sa_column=Column(String, nullable=False))  # 'general' | 'department'
    department: Optional[str] = Field(default=None, sa_column=Column(String, nullable=True))
    signoff_assignment_id: Optional[int] = Field(
        default=None, sa_column=Column(Integer, ForeignKey("assignment.id", ondelete="SET NULL"), nullable=True)
    )
    contact_check_assignment_id: Optional[int] = Field(
        default=None, sa_column=Column(Integer, ForeignKey("assignment.id", ondelete="SET NULL"), nullable=True)
    )


class MkaComplianceExpected(SQLModel, table=True):
    __tablename__ = "mka_compliance_expected"
    __table_args__ = (
        UniqueConstraint(
            "cycle_id", "email", "department", "level", "role_title", name="uq_mka_compliance_expected_role"
        ),
        Index("ix_mka_compliance_expected_org_cycle", "org_id", "cycle_id"),
        Index("ix_mka_compliance_expected_cycle_dept_region", "cycle_id", "department", "region"),
        Index("ix_mka_compliance_expected_email", "email"),
    )

    id: Optional[int] = Field(default=None, sa_column=Column(Integer, primary_key=True, autoincrement=True))
    org_id: int = Field(sa_column=Column(Integer, ForeignKey("organization.id", ondelete="CASCADE"), nullable=False))
    cycle_id: int = Field(
        sa_column=Column(Integer, ForeignKey("mka_compliance_cycle.id", ondelete="CASCADE"), nullable=False)
    )
    email: str = Field(sa_column=Column(String, nullable=False))  # lower-cased
    # '' = executive (general course only); never NULL so the unique key works on every database.
    department: str = Field(default="", sa_column=Column(String, nullable=False, server_default=""))
    level: str = Field(sa_column=Column(String, nullable=False))  # 'national' | 'regional' | 'local'
    majlis: Optional[str] = Field(default=None, sa_column=Column(String, nullable=True))
    region: Optional[str] = Field(default=None, sa_column=Column(String, nullable=True))
    role_title: str = Field(default="", sa_column=Column(String, nullable=False, server_default=""))
    person_name: Optional[str] = Field(default=None, sa_column=Column(String, nullable=True))
    appointed_on: Optional[date] = Field(default=None, sa_column=Column(Date, nullable=True))
    source: Optional[str] = Field(default=None, sa_column=Column(String, nullable=True))
    formula_unconfirmed: bool = Field(
        default=False, sa_column=Column(Boolean, nullable=False, server_default=false(), default=False)
    )
