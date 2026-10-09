"""MKA fork: course audience (spec 2026-10-08-mka-course-audience-design.md section 3.A).

A course may carry ONE audience: ``everyone`` (all org members), ``officeholders`` (every PROVEN office holder) or ``custom``
(office holders filtered by departments / levels / roles: OR within a field, AND across fields), and a mode: ``required``
(matching people are enrolled) or ``optin`` (they can see and start it).

How access works (no upstream file is touched): for a non-``everyone`` audience a MANAGED usergroup ``course:<course_uuid>``
(``mka_managed_group``) holds the matching people and is linked to the course through the upstream ``UserGroupResource``
table; the course is set ``public=False``. Upstream access then reads "member of a linked group". ``everyone`` unlinks and
deletes that managed group and keeps ``public=False`` with no group (= any org member). Usergroups an admin linked by hand
and groups that are not in ``mka_managed_group`` are NEVER touched.

* Matching: only PROVEN (``attributes.is_address_proven``), non-stale identities match, using the trust rule of
  ``identity_sync._gate`` (multi-org accounts: the parser output, never an override/roster layer). The rule evaluator is
  ``audience_eval``.
* Enrolment (``required``): Trail + TrailRun through ``automation_enroll._enrol_org`` (idempotent). Unpublished courses
  are skipped and picked up when published (SQLAlchemy ``after_commit`` listener below: no upstream hook) or on the
  next sign-in / profile save / backfill. NEVER unenrols.
* Flag ``MKA_COURSE_AUDIENCE_ENABLED`` (default false), read at call time: off = every hook is a no-op.
* Writes go straight to the tables (the upstream usergroup services need a Request and an acting user), as identity_sync does.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, event, func
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Session
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.courses.courses import Course
from src.db.mka_course_audience import MkaCourseAudience
from src.db.mka_identity import MkaManagedGroup
from src.db.mka_user_attributes import MkaUserAttributes
from src.db.trail_runs import TrailRun
from src.db.user_organizations import UserOrganization
from src.db.usergroup_resources import UserGroupResource
from src.db.usergroup_user import UserGroupUser
from src.db.usergroups import UserGroup
from src.db.users import User
from src.services.mka import attributes as attrs
from src.services.mka import identity_sync as isync
from src.services.mka.audience_config import build_options
from src.services.mka.audience_eval import (
    compile_rule,
    evaluate_compiled,
    validate_rule,
)
from src.services.mka.automation_enroll import OrgPlan, _enrol_org

logger = logging.getLogger(__name__)

AUDIENCES = ("everyone", "officeholders", "custom")
MODES = ("required", "optin")
GROUP_DESCRIPTION = "Managed by MKA course audience"
MAX_VALUES = 100


def enabled() -> bool:
    """``MKA_COURSE_AUDIENCE_ENABLED`` (default false), read at call time."""
    return os.environ.get("MKA_COURSE_AUDIENCE_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}


def group_key(course_uuid: str) -> str:
    return f"course:{course_uuid}"


def _now() -> str:
    return str(datetime.now())


# ---------------------------------------------------------------------------------------------------------------
# validation + rule conversion
# ---------------------------------------------------------------------------------------------------------------

def vocabulary() -> dict[str, set[str]]:
    opts = build_options(attrs.get_rules())
    return {
        "departments": {d["key"] for d in opts["departments"]},
        "levels": {x["key"] for x in opts["levels"]},
        "roles": {r["key"] for r in opts["roles"]},
    }


def normalize_custom(audience: str, rule: dict | None) -> dict | None:
    """The stored ``rule`` for an audience, or ``ValueError``. Only ``custom`` has one; values are checked against the
    audience vocabulary and de-duplicated; a custom audience needs at least one value."""
    if audience not in AUDIENCES:
        raise ValueError("audience must be one of " + ", ".join(AUDIENCES))
    if audience != "custom":
        return None
    rule = rule or {}
    vocab = vocabulary()
    out: dict[str, list[str]] = {}
    for field in ("departments", "levels", "roles"):
        vals = rule.get(field) or []
        if not isinstance(vals, list) or len(vals) > MAX_VALUES or not all(isinstance(v, str) for v in vals):
            raise ValueError(f"rule.{field} must be a list of at most {MAX_VALUES} strings")
        unknown = sorted(set(vals) - vocab[field])
        if unknown:
            raise ValueError(f"rule.{field} has unknown values: {', '.join(unknown)}")
        out[field] = list(dict.fromkeys(vals))
    if not any(out.values()):
        raise ValueError("a custom audience needs at least one department, level or role")
    return out


def eval_rule(audience: str, custom: dict | None) -> dict | None:
    """The ``audience_eval`` rule for office-holder based audiences (``None`` for ``everyone``)."""
    if audience == "everyone":
        return None
    group: dict[str, Any] = {"officeholder": True}
    if audience == "custom":
        for field, key in (("departments", "department"), ("levels", "level"), ("roles", "role")):
            if (custom or {}).get(field):
                group[key] = list(custom[field])  # type: ignore[index]
    ok, rule = validate_rule({"v": 1, "mode": "show", "groups": [group]})
    if not ok:  # pragma: no cover - the inputs were validated above
        raise ValueError(str(rule))
    return rule


# ---------------------------------------------------------------------------------------------------------------
# matching
# ---------------------------------------------------------------------------------------------------------------

def _trusted_viewer(row: MkaUserAttributes | None, user: Any, n_orgs: int) -> dict | None:
    """The attributes to evaluate for a user, or None when the identity cannot be trusted (unproven / stale / no row)."""
    if row is None or not attrs.is_address_proven(row, user) or attrs.is_stale(row, user):
        return None
    source = dict(row.derived or {}) if n_orgs > 1 else dict(row.effective or {})
    return attrs.effective_public(source)


def _name(first: str | None, last: str | None) -> str:
    return f"{first or ''} {last or ''}".strip()


async def _members(db: AsyncSession, org_id: int) -> list[tuple]:
    """(user_id, name, email, trusted viewer | None) for EVERY member of the org. Reads only."""
    rows = (
        await db.execute(
            select(User, MkaUserAttributes)
            .join(UserOrganization, UserOrganization.user_id == User.id)  # type: ignore[arg-type]
            .outerjoin(MkaUserAttributes, MkaUserAttributes.user_id == User.id)  # type: ignore[arg-type]
            .where(UserOrganization.org_id == org_id)
            .order_by(User.id)  # type: ignore[arg-type]
        )
    ).all()
    org_users = select(UserOrganization.user_id).where(UserOrganization.org_id == org_id)
    counts = dict(
        (
            await db.execute(
                select(UserOrganization.user_id, func.count(func.distinct(UserOrganization.org_id)))
                .where(UserOrganization.user_id.in_(org_users))  # type: ignore[attr-defined]
                .group_by(UserOrganization.user_id)
            )
        ).all()
    )
    out, seen = [], set()
    for user, row in rows:
        if user.id in seen:
            continue
        seen.add(user.id)
        out.append((user.id, _name(user.first_name, user.last_name), user.email, _trusted_viewer(row, user, counts.get(user.id, 1))))
    return out


def _matches(audience: str, compiled: tuple | None, viewer: dict | None) -> bool:
    if audience == "everyone":
        return True
    return viewer is not None and compiled is not None and evaluate_compiled(compiled, viewer)


async def matching(db: AsyncSession, org_id: int, audience: str, custom: dict | None) -> list[tuple]:
    """Members of the org (user_id, name, email) the audience reaches."""
    rule = eval_rule(audience, custom)
    compiled = compile_rule(rule) if rule else None
    return [(uid, n, e) for uid, n, e, viewer in await _members(db, org_id) if _matches(audience, compiled, viewer)]


async def _enrolled_ids(db: AsyncSession, course_id: int) -> set[int]:
    return set((await db.execute(select(TrailRun.user_id).where(TrailRun.course_id == course_id))).scalars().all())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------------------------------------------
# managed group
# ---------------------------------------------------------------------------------------------------------------

async def _managed_group(db: AsyncSession, org_id: int, course_uuid: str) -> UserGroup | None:
    return (
        await db.execute(
            select(UserGroup)
            .join(MkaManagedGroup, MkaManagedGroup.usergroup_id == UserGroup.id)  # type: ignore[arg-type]
            .where(MkaManagedGroup.org_id == org_id, MkaManagedGroup.key == group_key(course_uuid), UserGroup.org_id == org_id)
        )
    ).scalars().first()


async def _ensure_group(db: AsyncSession, course: Course) -> UserGroup:
    group = await _managed_group(db, course.org_id, course.course_uuid)
    name = f"Course: {course.name}"[:200]
    if group is None:
        await isync._sync_pg_sequence(db, "usergroup")
        now = _now()
        group = UserGroup(
            name=name, description=GROUP_DESCRIPTION, org_id=course.org_id,
            usergroup_uuid=f"usergroup_{uuid4()}", creation_date=now, update_date=now,
        )
        db.add(group)
        await db.flush()
        await db.execute(delete(MkaManagedGroup).where(MkaManagedGroup.org_id == course.org_id, MkaManagedGroup.key == group_key(course.course_uuid)))
        db.add(MkaManagedGroup(org_id=course.org_id, key=group_key(course.course_uuid), usergroup_id=group.id))  # type: ignore[arg-type]
    elif group.name != name:
        group.name = name
        group.update_date = _now()
        db.add(group)
    link = (
        await db.execute(
            select(UserGroupResource.id).where(UserGroupResource.usergroup_id == group.id, UserGroupResource.resource_uuid == course.course_uuid)
        )
    ).first()
    if link is None:
        db.add(UserGroupResource(usergroup_id=group.id, resource_uuid=course.course_uuid, org_id=course.org_id,  # type: ignore[arg-type]
                                 creation_date=_now(), update_date=_now()))
    return group


async def _drop_group(db: AsyncSession, course: Course) -> int:
    """Unlink + delete the MANAGED course group (nothing else). Returns the number of members it held."""
    group = await _managed_group(db, course.org_id, course.course_uuid)
    if group is None:
        await db.execute(delete(MkaManagedGroup).where(MkaManagedGroup.org_id == course.org_id, MkaManagedGroup.key == group_key(course.course_uuid)))
        return 0
    held = (await db.execute(select(func.count()).select_from(UserGroupUser).where(UserGroupUser.usergroup_id == group.id))).scalar() or 0
    await db.execute(delete(UserGroupResource).where(UserGroupResource.usergroup_id == group.id, UserGroupResource.resource_uuid == course.course_uuid))
    await db.execute(delete(UserGroupUser).where(UserGroupUser.usergroup_id == group.id))
    await db.execute(delete(MkaManagedGroup).where(MkaManagedGroup.usergroup_id == group.id))
    await db.execute(delete(UserGroup).where(UserGroup.id == group.id))
    return int(held)


async def _set_members(db: AsyncSession, group: UserGroup, org_id: int, want: set[int]) -> tuple[int, int]:
    have = set((await db.execute(select(UserGroupUser.user_id).where(UserGroupUser.usergroup_id == group.id))).scalars().all())
    add, remove = want - have, have - want
    now = _now()
    for uid in sorted(add):
        db.add(UserGroupUser(usergroup_id=group.id, user_id=uid, org_id=org_id, creation_date=now, update_date=now))  # type: ignore[arg-type]
    if remove:
        await db.execute(delete(UserGroupUser).where(UserGroupUser.usergroup_id == group.id, UserGroupUser.user_id.in_(remove)))  # type: ignore[attr-defined]
    return len(add), len(remove)


# ---------------------------------------------------------------------------------------------------------------
# enrolment
# ---------------------------------------------------------------------------------------------------------------

async def _enroll(db: AsyncSession, course: Course, user_ids: list[int]) -> int:
    """Enrol users who have no trail run for the course yet. Returns the number of NEW enrolments. Per-user failures
    are logged and skipped (one bad account never blocks the rest)."""
    if not course.published or not user_ids:
        return 0
    done = await _enrolled_ids(db, course.id)  # type: ignore[arg-type]
    created = 0
    for uid in user_ids:
        if uid in done:
            continue
        try:
            created += await _enrol_org(db, uid, OrgPlan(org_id=course.org_id, cycle_id=0, enroll=[(course.id, course.course_uuid)]))  # type: ignore[list-item]
        except Exception as exc:  # noqa: BLE001
            logger.error("MKA course audience: enrolment failed for one user (rolled back): %s", type(exc).__name__)
            await db.rollback()
    return created


# ---------------------------------------------------------------------------------------------------------------
# course level
# ---------------------------------------------------------------------------------------------------------------

def _custom_of(row: MkaCourseAudience) -> dict | None:
    return row.rule if row.audience == "custom" else None


async def _converge(db: AsyncSession, course: Course, row: MkaCourseAudience) -> dict:
    """Make the course access and enrolment match its audience row. Commits. Idempotent."""
    people = await matching(db, course.org_id, row.audience, _custom_of(row))
    ids = [p[0] for p in people]
    added = removed = 0
    if row.audience == "everyone":
        removed = await _drop_group(db, course)
        row.usergroup_id = None
    else:
        group = await _ensure_group(db, course)
        added, removed = await _set_members(db, group, course.org_id, set(ids))
        row.usergroup_id = group.id
    if course.public:
        course.public = False
        course.update_date = _now()
        db.add(course)
    db.add(row)
    await db.commit()
    enrolled = await _enroll(db, course, ids) if row.mode == "required" else 0
    return {"memberships_added": added, "memberships_removed": removed, "enrolled": enrolled, "matched_count": len(ids)}


async def get(db: AsyncSession, course: Course) -> dict:
    row = await db.get(MkaCourseAudience, course.id)
    if row is None:
        return {"audience": None}
    matched = await matching(db, course.org_id, row.audience, _custom_of(row))
    return {"audience": row.audience, "mode": row.mode, "rule": _custom_of(row), "usergroup_id": row.usergroup_id,
            "matched_count": len(matched)}


async def preview(db: AsyncSession, course: Course, audience: str, mode: str, custom: dict | None) -> dict:
    """No writes."""
    people = await matching(db, course.org_id, audience, custom)
    would = 0
    if mode == "required" and course.published:
        done = await _enrolled_ids(db, course.id)  # type: ignore[arg-type]
        would = sum(1 for p in people if p[0] not in done)
    return {
        "matched_count": len(people),
        "sample": [{"user_id": uid, "name": n, "email": e} for uid, n, e in people[:10]],
        "would_enroll": would,
    }


async def apply(db: AsyncSession, course: Course, audience: str, mode: str, custom: dict | None, actor_uid: int | None) -> dict:
    await isync._pg_lock(db, f"mka-course-audience:{course.id}")
    row = await db.get(MkaCourseAudience, course.id)
    if row is None:
        row = MkaCourseAudience(course_id=course.id, org_id=course.org_id, audience=audience, mode=mode)  # type: ignore[arg-type]
    row.audience, row.mode, row.rule = audience, mode, custom
    row.updated_by, row.updated_at = actor_uid, datetime.now()
    return await _converge(db, course, row)


async def remove(db: AsyncSession, course: Course) -> dict:
    """Delete the audience row + the managed group (members lose access via it); enrolments stay."""
    row = await db.get(MkaCourseAudience, course.id)
    if row is None:
        return {"removed": False, "memberships_removed": 0}
    gone = await _drop_group(db, course)
    await db.delete(row)
    if course.public:
        course.public = False
    course.update_date = _now()
    db.add(course)
    await db.commit()
    return {"removed": True, "memberships_removed": gone}


async def reconcile_course(db: AsyncSession, course_id: int) -> dict | None:
    """Re-converge one course (publish hook / backfill). No-op when the flag is off or the course has no audience."""
    if not enabled():
        return None
    row = await db.get(MkaCourseAudience, course_id)
    course = await db.get(Course, course_id)
    if row is None or course is None:
        return None
    return await _converge(db, course, row)


async def reconcile_org(db: AsyncSession, org_id: int) -> dict:
    """Re-converge every course audience of an org (identity backfill)."""
    out = {"courses": 0, "memberships_added": 0, "memberships_removed": 0, "enrolled": 0, "errors": 0}
    if not enabled():
        return out
    ids = (await db.execute(select(MkaCourseAudience.course_id).where(MkaCourseAudience.org_id == org_id))).scalars().all()
    for cid in ids:
        try:
            res = await reconcile_course(db, cid)
        except Exception as exc:  # noqa: BLE001
            out["errors"] += 1
            logger.error("MKA course audience backfill failed for one course: %s", type(exc).__name__)
            await db.rollback()
            continue
        if res:
            out["courses"] += 1
            for k in ("memberships_added", "memberships_removed", "enrolled"):
                out[k] += res[k]
    return out


# ---------------------------------------------------------------------------------------------------------------
# per-user hook (identity sync ``_run``: sign-in, profile save, org join)
# ---------------------------------------------------------------------------------------------------------------

async def sync_user(db: AsyncSession, user_id: int, org_ids: list[int]) -> None:
    """Recompute ONE user's course-group memberships and required enrolments for every course audience in ``org_ids``.
    May raise: the caller catches. Flag off = zero writes."""
    if not enabled():
        return
    user = await db.get(User, user_id)
    if user is None:
        return
    row = await attrs.get_row(db, user_id)
    n_orgs = len(set((await db.execute(select(UserOrganization.org_id).where(UserOrganization.user_id == user_id))).scalars().all()))
    viewer = _trusted_viewer(row, user, n_orgs)
    for org_id in org_ids:
        rows = (await db.execute(select(MkaCourseAudience).where(MkaCourseAudience.org_id == org_id))).scalars().all()
        to_enroll: list[tuple[int, str]] = []
        for aud in rows:
            course = await db.get(Course, aud.course_id)
            if course is None:
                continue
            rule = eval_rule(aud.audience, _custom_of(aud))
            hit = _matches(aud.audience, compile_rule(rule) if rule else None, viewer)
            if aud.audience != "everyone" and aud.usergroup_id is not None:
                present = (
                    await db.execute(
                        select(UserGroupUser.id).where(UserGroupUser.usergroup_id == aud.usergroup_id, UserGroupUser.user_id == user_id)
                    )
                ).first() is not None
                if hit and not present:
                    db.add(UserGroupUser(usergroup_id=aud.usergroup_id, user_id=user_id, org_id=org_id, creation_date=_now(), update_date=_now()))
                elif not hit and present:
                    await db.execute(delete(UserGroupUser).where(UserGroupUser.usergroup_id == aud.usergroup_id, UserGroupUser.user_id == user_id))
            if hit and aud.mode == "required" and course.published:
                to_enroll.append((course.id, course.course_uuid))  # type: ignore[arg-type]
        await db.commit()
        if to_enroll:
            await _enrol_org(db, user_id, OrgPlan(org_id=org_id, cycle_id=0, enroll=to_enroll))


# ---------------------------------------------------------------------------------------------------------------
# publish hook: a course that becomes published gets its required audience enrolled (no upstream edit)
# ---------------------------------------------------------------------------------------------------------------

_PUBLISHED_KEY = "mka_course_audience_published"
_PENDING: set = set()  # strong refs to in-flight tasks (tests await them)


@event.listens_for(Session, "after_flush")
def _track_publish(session: Session, _ctx: Any) -> None:
    try:
        if not enabled():
            return
        for obj in session.dirty:
            if isinstance(obj, Course) and obj.published and obj.id is not None:
                hist = sa_inspect(obj).attrs.published.history
                if hist.has_changes() and not (hist.deleted and hist.deleted[0]):
                    session.info.setdefault(_PUBLISHED_KEY, set()).add(obj.id)
    except Exception:
        logger.exception("MKA course audience: publish tracking failed (ignored)")


@event.listens_for(Session, "after_rollback")
def _forget_publish(session: Session) -> None:
    session.info.pop(_PUBLISHED_KEY, None)


@event.listens_for(Session, "after_commit")
def _fire_publish(session: Session) -> None:
    ids = session.info.pop(_PUBLISHED_KEY, None)
    if not ids:
        return
    try:
        bind = session.get_bind()
        engine = getattr(bind, "engine", bind)
        task = asyncio.get_running_loop().create_task(_after_publish(AsyncEngine(engine), sorted(ids)))
        _PENDING.add(task)
        task.add_done_callback(_PENDING.discard)
    except Exception:
        logger.exception("MKA course audience: could not schedule the publish reconcile (ignored)")


async def _after_publish(engine: AsyncEngine, course_ids: list[int]) -> None:
    try:
        async with AsyncSession(bind=engine, expire_on_commit=False) as s:
            for cid in course_ids:
                try:
                    await reconcile_course(s, cid)
                except Exception as exc:  # noqa: BLE001
                    logger.error("MKA course audience: publish reconcile failed for one course: %s", type(exc).__name__)
                    await s.rollback()
    except Exception as exc:  # noqa: BLE001
        logger.error("MKA course audience: publish reconcile failed: %s", type(exc).__name__)
