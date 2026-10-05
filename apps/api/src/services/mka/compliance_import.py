"""MKA fork: import of compliance cycles / courses / the expected roster (spec section 2).

Callers (router) have ALREADY resolved an org admin (session) or an org API token; ``org_id`` here is that
org. Nothing in this module trusts a client-supplied org: every lookup filters by ``org_id`` and a course or
assignment from another org is reported as an ordinary per-row error ("not found in this organization").

Contracts
* idempotent: re-posting the same payload creates nothing new and changes nothing;
* one bad row never aborts the batch: every row gets ``ok`` / ``error``;
* the cycle payload accepts the provisioner's ``out/cycle-courses.json`` shape unchanged (extra keys such as
  ``generatedAt`` / ``activities`` are ignored).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.courses.assignments import Assignment
from src.db.courses.courses import Course
from src.db.mka_compliance import (
    MkaComplianceCycle,
    MkaComplianceCycleCourse,
    MkaComplianceExpected,
)
from src.services.mka.identity_parser import LEVELS

MAX_EXPECTED_ROWS = 2000
MAX_COURSE_ROWS = 100
KINDS = ("general", "department")
# starts_on is not part of the provisioner file; when a NEW cycle arrives without one we assume a 30-day
# cycle ending at the deadline (UNCONFIRMED) and keep whatever is stored on later imports.
DEFAULT_CYCLE_LENGTH_DAYS = 30


async def _commit(db: AsyncSession) -> None:
    """A concurrent import hitting the same unique key is a 409, not a 500 (the transaction is atomic)."""
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Conflicting concurrent import; retry")


def _parse_date(value: Any, field: str) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            pass
    raise ValueError(f"{field} must be a YYYY-MM-DD date")


def _text(value: Any, field: str, max_len: int, required: bool = False) -> Optional[str]:
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise ValueError(f"{field} is required")
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    value = value.strip()
    if len(value) > max_len:
        raise ValueError(f"{field} must be at most {max_len} characters")
    return value


def normalize_department(value: Any) -> str:
    """lower-case key; '' = executive (no department)."""
    return (_text(value, "department", 64) or "").lower()


# ---------------------------------------------------------------------------------------------------------
# cycle + its courses
# ---------------------------------------------------------------------------------------------------------

async def _find_course(db: AsyncSession, org_id: int, course_uuid: str) -> Optional[Course]:
    return (
        await db.execute(select(Course).where(
            Course.course_uuid.in_([course_uuid, f"course_{course_uuid}"]),  # type: ignore[attr-defined]
            Course.org_id == org_id,
        ))
    ).scalars().first()


async def _find_assignment(db: AsyncSession, org_id: int, course: Course, assignment_uuid: str) -> Optional[Assignment]:
    return (
        await db.execute(
            select(Assignment).where(
                Assignment.assignment_uuid == assignment_uuid,
                Assignment.org_id == org_id,
                Assignment.course_id == course.id,
            )
        )
    ).scalars().first()


async def upsert_cycle(db: AsyncSession, org_id: int, payload: dict) -> dict:
    """Upsert the cycle (by label) and its courses. Cycle-level problems raise 422; course-level problems are
    reported per course."""
    try:
        label = _text(payload.get("cycle") or payload.get("label"), "cycle", 100, required=True)
        deadline = _parse_date(payload.get("deadline") or payload.get("deadline_on"), "deadline")
        starts_raw = payload.get("starts_on")
        starts = _parse_date(starts_raw, "starts_on") if starts_raw not in (None, "") else None
        if starts is not None and starts > deadline:
            raise ValueError("starts_on must not be after the deadline")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    courses = payload.get("courses")
    if not isinstance(courses, list):
        raise HTTPException(status_code=422, detail="courses must be a list")
    if len(courses) > MAX_COURSE_ROWS:
        raise HTTPException(status_code=422, detail=f"At most {MAX_COURSE_ROWS} courses per request")

    cycle = (
        await db.execute(
            select(MkaComplianceCycle).where(MkaComplianceCycle.org_id == org_id, MkaComplianceCycle.label == label)
        )
    ).scalars().first()
    cycle_action = "updated"
    if cycle is None:
        cycle = MkaComplianceCycle(
            org_id=org_id, label=label, deadline_on=deadline,
            starts_on=starts or (deadline - timedelta(days=DEFAULT_CYCLE_LENGTH_DAYS)),
        )
        db.add(cycle)
        await db.flush()
        cycle_action = "created"
    else:
        cycle.deadline_on = deadline
        if starts is not None:
            cycle.starts_on = starts
        if cycle.starts_on > cycle.deadline_on:
            await db.rollback()
            raise HTTPException(status_code=422, detail="starts_on must not be after the deadline")
        db.add(cycle)

    existing = {
        cc.course_id: cc
        for cc in (
            await db.execute(
                select(MkaComplianceCycleCourse).where(
                    MkaComplianceCycleCourse.cycle_id == cycle.id, MkaComplianceCycleCourse.org_id == org_id
                )
            )
        ).scalars().all()
    }

    results: list[dict] = []
    for idx, raw in enumerate(courses):
        res: dict = {"row": idx, "course_uuid": raw.get("course_uuid") if isinstance(raw, dict) else None, "ok": False}
        results.append(res)
        try:
            if not isinstance(raw, dict):
                raise ValueError("course entry must be an object")
            kind = _text(raw.get("kind"), "kind", 20, required=True)
            if kind not in KINDS:
                raise ValueError("kind must be 'general' or 'department'")
            department = normalize_department(raw.get("department")) or None
            if kind == "department" and not department:
                raise ValueError("department is required for a department course")
            if kind == "general":
                department = None
            course_uuid = _text(raw.get("course_uuid"), "course_uuid", 200, required=True)
            course = await _find_course(db, org_id, course_uuid)  # type: ignore[arg-type]
            if course is None:
                raise ValueError("Course not found in this organization")

            def assignment_ref(key: str):
                """(present, uuid|None): absent key keeps the stored value, explicit null clears it."""
                if key not in raw:
                    return False, None
                node = raw[key]
                if node is None:
                    return True, None
                if not isinstance(node, dict):
                    raise ValueError(f"{key} must be an object or null")
                return True, _text(node.get("assignment_uuid"), f"{key}.assignment_uuid", 200, required=True)

            resolved: dict[str, Optional[int]] = {}
            for key, column in (("signoff", "signoff_assignment_id"), ("contact_check", "contact_check_assignment_id")):
                present, a_uuid = assignment_ref(key)
                if not present:
                    continue
                if a_uuid is None:
                    resolved[column] = None
                    continue
                assignment = await _find_assignment(db, org_id, course, a_uuid)
                if assignment is None:
                    raise ValueError(f"{key} assignment not found in this course")
                resolved[column] = assignment.id

            clash = next(
                (o for o in existing.values()
                 if o.course_id != course.id and o.kind == kind and (o.department or None) == department),
                None,
            )
            if clash is not None:
                raise ValueError(f"the cycle already has a {kind} course for {department or 'general'}")
            link = existing.get(course.id)  # type: ignore[arg-type]
            if link is None:
                link = MkaComplianceCycleCourse(
                    org_id=org_id, cycle_id=cycle.id, course_id=course.id, course_uuid=course.course_uuid,  # type: ignore[arg-type]
                    kind=kind, department=department,
                    signoff_assignment_id=resolved.get("signoff_assignment_id"),
                    contact_check_assignment_id=resolved.get("contact_check_assignment_id"),
                )
                db.add(link)
                existing[course.id] = link  # type: ignore[index]
                res["action"] = "created"
            else:
                link.kind, link.department = kind, department
                for column, value in resolved.items():
                    setattr(link, column, value)
                db.add(link)
                res["action"] = "updated"
            res["ok"] = True
        except ValueError as exc:
            res["error"] = str(exc)
    await _commit(db)
    return {
        "cycle": {
            "id": cycle.id, "label": cycle.label,
            "starts_on": cycle.starts_on.isoformat(), "deadline_on": cycle.deadline_on.isoformat(),
            "action": cycle_action,
        },
        "courses": results,
        "ok": sum(1 for r in results if r["ok"]),
        "failed": sum(1 for r in results if not r["ok"]),
    }


# ---------------------------------------------------------------------------------------------------------
# expected roster
# ---------------------------------------------------------------------------------------------------------

async def require_cycle(db: AsyncSession, org_id: int, *, cycle_id: Optional[int], label: Optional[str]) -> MkaComplianceCycle:
    stmt = select(MkaComplianceCycle).where(MkaComplianceCycle.org_id == org_id)
    if cycle_id is not None:
        stmt = stmt.where(MkaComplianceCycle.id == cycle_id)
    elif label:
        stmt = stmt.where(MkaComplianceCycle.label == label)
    else:
        raise HTTPException(status_code=422, detail="cycle_id or cycle (label) is required")
    cycle = (await db.execute(stmt)).scalars().first()
    if cycle is None:
        raise HTTPException(status_code=404, detail="Cycle not found")
    return cycle


def validate_expected_row(raw: Any) -> dict:
    """Normalised fields for one expected-roster row; ValueError with a readable message otherwise."""
    if not isinstance(raw, dict):
        raise ValueError("row must be an object")
    email = (_text(raw.get("email"), "email", 320, required=True) or "").lower()
    if "@" not in email or email.startswith("@") or email.endswith("@") or " " in email:
        raise ValueError("email is not valid")
    level = _text(raw.get("level"), "level", 20, required=True)
    if level not in LEVELS:
        raise ValueError("level must be national, regional or local")
    appointed = raw.get("appointed_on")
    flag = raw.get("formula_unconfirmed", False)
    if not isinstance(flag, bool):
        raise ValueError("formula_unconfirmed must be true or false")
    return {
        "email": email,
        "department": normalize_department(raw.get("department")),
        "level": level,
        "majlis": _text(raw.get("majlis"), "majlis", 100),
        "region": _text(raw.get("region"), "region", 100),
        "role_title": _text(raw.get("role_title"), "role_title", 200) or "",
        "person_name": _text(raw.get("person_name"), "person_name", 200),
        "appointed_on": _parse_date(appointed, "appointed_on") if appointed not in (None, "") else None,
        "source": _text(raw.get("source"), "source", 100),
        "formula_unconfirmed": flag,
    }


_KEY = ("email", "department", "level", "role_title")
_VALUE_FIELDS = ("majlis", "region", "person_name", "appointed_on", "source", "formula_unconfirmed")


async def import_expected(
    db: AsyncSession, org_id: int, cycle: MkaComplianceCycle, rows: list[Any], dry_run: bool = False
) -> dict:
    existing = {
        (r.email, r.department, r.level, r.role_title): r
        for r in (
            await db.execute(
                select(MkaComplianceExpected).where(
                    MkaComplianceExpected.cycle_id == cycle.id, MkaComplianceExpected.org_id == org_id
                )
            )
        ).scalars().all()
    }
    created = updated = unchanged = 0
    errors: list[dict] = []
    seen: dict[tuple, dict] = {}
    for idx, raw in enumerate(rows):
        try:
            clean = validate_expected_row(raw)
        except ValueError as exc:
            errors.append({"row": idx, "error": str(exc)})
            continue
        seen[tuple(clean[k] for k in _KEY)] = clean  # a later duplicate within the batch wins
    for key, clean in seen.items():
        row = existing.get(key)
        if row is None:
            created += 1
            if not dry_run:
                db.add(MkaComplianceExpected(org_id=org_id, cycle_id=cycle.id, **clean))  # type: ignore[arg-type]
            continue
        changed = [f for f in _VALUE_FIELDS if getattr(row, f) != clean[f]]
        if not changed:
            unchanged += 1
            continue
        updated += 1
        if not dry_run:
            for f in changed:
                setattr(row, f, clean[f])
            db.add(row)
    unmatched: list[str] = []
    if seen:
        have = {
            d for (d,) in (
                await db.execute(
                    select(MkaComplianceCycleCourse.department).where(
                        MkaComplianceCycleCourse.cycle_id == cycle.id,
                        MkaComplianceCycleCourse.org_id == org_id,
                        MkaComplianceCycleCourse.kind == "department",
                    )
                )
            ).all()
        }
        unmatched = sorted({c["department"] for c in seen.values() if c["department"] and c["department"] not in have})
    if not dry_run:
        await _commit(db)
    return {
        "cycle_id": cycle.id, "received": len(rows), "created": created, "updated": updated,
        "unchanged": unchanged, "failed": len(errors), "errors": errors, "dry_run": dry_run,
        "departments_without_course": unmatched,
    }


async def clear_expected(db: AsyncSession, org_id: int, cycle: MkaComplianceCycle) -> int:
    count = len(
        (
            await db.execute(
                select(MkaComplianceExpected.id).where(
                    MkaComplianceExpected.cycle_id == cycle.id, MkaComplianceExpected.org_id == org_id
                )
            )
        ).all()
    )
    await db.execute(
        delete(MkaComplianceExpected).where(
            MkaComplianceExpected.cycle_id == cycle.id, MkaComplianceExpected.org_id == org_id  # type: ignore[arg-type]
        )
    )
    await db.commit()
    return count
