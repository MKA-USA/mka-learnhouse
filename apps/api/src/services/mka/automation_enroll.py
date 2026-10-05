"""MKA fork: auto-enrol on Google sign-in (compliance automation spec 2026-10-05, section 2 A).

Called from the fork-owned login hook ``attributes.mka_refresh_on_login`` AFTER the attribute refresh, only when
``MKA_AUTOMATION_ENABLED && MKA_AUTOENROLL_ENABLED`` and the login is a Google sign-in. The account's address must be
PROVEN (``attributes.is_address_proven``): an unproven identity is never enrolled.

Contract
* matching: ``lower(email)`` against ``mka_compliance_expected`` (ONE indexed query; no match -> exit),
  for the org's default cycle (``compliance_scope.get_cycle``), and only for orgs the user is a member of;
* enrol into the cycle's General course and the department course of EACH of the person's roster rows (deduped;
  executive / national-only rows have no department course -> General only);
* enrolment = the learner's ``Trail`` plus one ``TrailRun`` per course, in its OWN session (never the login session).
  Idempotency does NOT lean on a unique constraint (review M1: ``uq_trailrun_trail_course_user`` exists only in the
  model; ``create_all`` never adds it to a table that predates it, and no migration runs here). Under the per-
  (user, org) lock (Postgres advisory transaction lock + in-process lock) we ``SELECT`` for an existing run and
  insert only when there is none, so the same code is correct with or without the constraint;
* courses that are not published are SKIPPED and recorded (``skipped_unpublished``), a later login or ``reconcile``
  picks them up (enrolment does not grant access to a draft);
* events go to ``mka_automation_event`` with a generated delivery id; no payload bodies, no email addresses;
* NEVER raises into the login path (fail-open for login, fail-closed for enrolment: an org's enrolment is one
  transaction that rolls back whole on error). A failed org is VISIBLE: an ``error`` event with a short reason
  (``enrol_failed:<ExceptionName>``) that ``GET /mka/automation/status`` counts (``autoenroll.errors_recent``).
"""

from __future__ import annotations

import asyncio
import logging
import weakref
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional
from uuid import uuid4

from sqlalchemy import func, text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.courses.courses import Course  # noqa: F401  (table registration for the cycle-course join)
from src.db.mka_automation import MkaAutomationEvent
from src.db.mka_compliance import MkaComplianceExpected
from src.db.trail_runs import StatusEnum, TrailRun
from src.db.trails import Trail
from src.db.user_organizations import UserOrganization
from src.services.mka import attributes as attrs
from src.services.mka import automation_config as cfg
from src.services.mka import compliance as compliance
from src.services.mka import compliance_scope as scope

logger = logging.getLogger(__name__)

EVENT = "autoenroll"
TIMEOUT_SECONDS = 10.0


@dataclass
class OrgPlan:
    org_id: int
    cycle_id: int
    enroll: list[tuple[int, str]] = field(default_factory=list)  # (course_id, course_uuid)
    skipped_unpublished: list[tuple[int, str]] = field(default_factory=list)
    reason: Optional[str] = None  # why nothing is planned for this org (no PII)


@dataclass
class Plan:
    user_id: int
    orgs: list[OrgPlan] = field(default_factory=list)
    reason: Optional[str] = None  # 'no_match' | 'unproven' | None

    @property
    def course_ids(self) -> list[int]:
        return [cid for o in self.orgs for cid, _ in o.enroll]


def _norm(email: Optional[str]) -> str:
    return (email or "").strip().lower()


async def plan_autoenroll(db: AsyncSession, user: Any, today: Optional[str] = None) -> Plan:
    """Read-only: what would ``autoenroll_user`` do for ``user`` (anything with ``id`` and ``email``).
    The FIRST statement is the single indexed roster lookup; a non-roster user costs exactly that one query."""
    plan = Plan(user_id=user.id)
    email = _norm(user.email)
    if not email:
        plan.reason = "no_match"
        return plan
    roster = list(
        (
            await db.execute(
                select(MkaComplianceExpected).where(MkaComplianceExpected.email == email)
            )
        ).scalars().all()
    )
    if not roster:
        plan.reason = "no_match"
        return plan
    # Identity proof only after a roster hit, so the common no-match login stays at one query.
    row = await attrs.get_row(db, user.id)
    if not attrs.is_address_proven(row, user):
        plan.reason = "unproven"
        return plan

    day = today or compliance.today()
    by_org: dict[int, list[MkaComplianceExpected]] = {}
    for r in roster:
        by_org.setdefault(r.org_id, []).append(r)
    for org_id in sorted(by_org):
        member = (
            await db.execute(
                select(UserOrganization.user_id).where(
                    UserOrganization.user_id == user.id, UserOrganization.org_id == org_id
                )
            )
        ).first()
        if member is None:
            plan.orgs.append(OrgPlan(org_id=org_id, cycle_id=0, reason="not_member"))
            continue
        cycle = await scope.get_cycle(db, org_id, None, day)
        if cycle is None or cycle.id is None:
            plan.orgs.append(OrgPlan(org_id=org_id, cycle_id=0, reason="no_cycle"))
            continue
        rows = [r for r in by_org[org_id] if r.cycle_id == cycle.id]
        if not rows:
            plan.orgs.append(OrgPlan(org_id=org_id, cycle_id=cycle.id, reason="not_on_active_roster"))
            continue
        departments = {(r.department or "").lower() for r in rows} - {""}
        op = OrgPlan(org_id=org_id, cycle_id=cycle.id)
        seen: set[int] = set()
        for link, course in await scope.cycle_courses(db, org_id, cycle.id):
            wanted = link.kind == "general" or (
                link.kind == "department" and (link.department or "").lower() in departments
            )
            if not wanted or course.id in seen:
                continue
            seen.add(course.id)
            (op.enroll if course.published else op.skipped_unpublished).append((course.id, course.course_uuid))
        plan.orgs.append(op)
    return plan


# ---------------------------------------------------------------------------------------------------------------
# execution
# ---------------------------------------------------------------------------------------------------------------

# In-process striped locks: serialise the Trail + TrailRun get-or-create within one API process on every database (the
# Postgres advisory lock below covers other processes/replicas; SQLite has none). An asyncio.Lock binds to the event
# loop that first has to WAIT on it, so the stripes are kept per running loop (one loop in production; one per test).
_LOCKS: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, list[asyncio.Lock]]" = weakref.WeakKeyDictionary()
_STRIPES = 64


def _lock_for(user_id: int, org_id: int) -> asyncio.Lock:
    stripes = _LOCKS.setdefault(asyncio.get_running_loop(), [asyncio.Lock() for _ in range(_STRIPES)])
    return stripes[hash((user_id, org_id)) % _STRIPES]


async def _enrol_org(s: AsyncSession, user_id: int, op: OrgPlan) -> int:
    async with _lock_for(user_id, op.org_id):
        return await _enrol_org_locked(s, user_id, op)


async def _enrol_org_locked(s: AsyncSession, user_id: int, op: OrgPlan) -> int:
    """Ensure Trail + TrailRun rows for one org in ONE transaction. Returns the number of NEW enrolments."""
    if s.get_bind().dialect.name == "postgresql":
        await s.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"mka-enrol:{user_id}:{op.org_id}"}
        )
    trail = (
        await s.execute(
            select(Trail).where(Trail.user_id == user_id, Trail.org_id == op.org_id).order_by(Trail.id)  # type: ignore[arg-type]
        )
    ).scalars().first()
    now = str(datetime.now())
    if trail is None:
        trail = Trail(org_id=op.org_id, user_id=user_id, trail_uuid=f"trail_{uuid4()}", creation_date=now, update_date=now)
        s.add(trail)
        await s.flush()
    created = 0
    for course_id, _uuid in op.enroll:
        existing = (
            await s.execute(
                select(TrailRun.id).where(
                    TrailRun.trail_id == trail.id, TrailRun.course_id == course_id, TrailRun.user_id == user_id  # type: ignore[arg-type]
                ).limit(1)
            )
        ).first()
        if existing is not None:  # already enrolled (earlier login, or the learner enrolled themselves)
            continue
        s.add(
            TrailRun(
                trail_id=trail.id, course_id=course_id, org_id=op.org_id, user_id=user_id,  # type: ignore[arg-type]
                status=StatusEnum.STATUS_IN_PROGRESS, data={}, creation_date=now, update_date=now,
            )
        )
        created += 1
    await s.flush()
    await s.commit()
    return created


async def _event_exists(s: AsyncSession, org_id: int, user_id: int, status: str, course_uuid: Optional[str], note: Optional[str]) -> bool:
    q = select(func.count()).select_from(MkaAutomationEvent).where(
        MkaAutomationEvent.org_id == org_id, MkaAutomationEvent.user_id == user_id,
        MkaAutomationEvent.event == EVENT, MkaAutomationEvent.status == status,
        MkaAutomationEvent.course_uuid == course_uuid if course_uuid else MkaAutomationEvent.course_uuid.is_(None),  # type: ignore[union-attr]
    )
    if note:
        q = q.where(MkaAutomationEvent.note == note)
    return bool((await s.execute(q)).scalar() or 0)


async def _record(s: AsyncSession, org_id: int, user_id: int, status: str, *, course_uuid: Optional[str] = None,
                  note: Optional[str] = None, dedupe: bool = False) -> None:
    """Best-effort internal event (generated delivery id, no payload, no addresses). ``dedupe`` keeps a repeating
    condition (draft course, not a member) from adding one row per login."""
    if dedupe and await _event_exists(s, org_id, user_id, status, course_uuid, note):
        return
    s.add(MkaAutomationEvent(org_id=org_id, delivery_id=f"{EVENT}:{uuid4()}", event=EVENT, user_id=user_id,
                             course_uuid=course_uuid, status=status, note=note))
    await s.commit()


async def autoenroll_user(db_factory: Callable[[], AsyncSession], user: Any, today: Optional[str] = None) -> Plan:
    """Auto-enrol ``user`` (anything with ``id`` and ``email``; the hook passes a plain snapshot). NEVER raises.
    ``db_factory()`` must return a NEW session (async context manager) separate from the login session."""
    empty = Plan(user_id=getattr(user, "id", 0), reason="disabled")
    try:
        if not cfg.autoenroll_enabled():
            return empty
        return await asyncio.wait_for(_run(db_factory, user, today), timeout=TIMEOUT_SECONDS)
    except Exception as exc:  # noqa: BLE001 - fail-open for LOGIN by design (also covers the timeout)
        logger.error("MKA auto-enrol failed (login unaffected): %s", type(exc).__name__)  # no traceback: SQL params can hold PII
        return Plan(user_id=getattr(user, "id", 0), reason="error")


async def _run(db_factory: Callable[[], AsyncSession], user: Any, today: Optional[str]) -> Plan:
    async with db_factory() as s:
        plan = await plan_autoenroll(s, user, today)
        if plan.reason is not None:
            return plan
        # Reads above opened an implicit transaction; end it before the write transactions.
        await s.rollback()
        for op in plan.orgs:
            try:
                if op.reason:
                    await _record(s, op.org_id, user.id, "ignored", note=op.reason, dedupe=True)
                    continue
                created = await _enrol_org(s, user.id, op) if op.enroll else 0
                for _cid, uuid_ in op.skipped_unpublished:
                    await _record(s, op.org_id, user.id, "skipped_unpublished", course_uuid=uuid_, dedupe=True)
                if created:
                    await _record(s, op.org_id, user.id, "processed", note=f"enrolled:{created}")
            except Exception as exc:  # noqa: BLE001 - fail-closed for enrolment: this org's transaction rolls back whole
                reason = type(exc).__name__
                logger.error("MKA auto-enrol failed for one org (rolled back): %s", reason)
                op.enroll = []
                op.reason = "error"
                try:
                    await s.rollback()
                    # visible to operators: counted by GET /mka/automation/status (a class name only: no PII)
                    await _record(s, op.org_id, user.id, "error", note=f"enrol_failed:{reason}"[:120])
                except Exception as rec_exc:  # noqa: BLE001
                    logger.error("MKA auto-enrol could not record the failure: %s", type(rec_exc).__name__)
        return plan
