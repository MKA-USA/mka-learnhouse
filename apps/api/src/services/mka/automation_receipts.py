"""MKA fork: sign-off receipts (seam B of the compliance automation, spec 2026-10-05 section 2B).

Everything here is keyed on the DATABASE, never on the webhook payload:

* the org comes from the assignment / course row (a payload ``org_id`` is only compared, never used);
* the recipient is the ACCOUNT's email, resolved from ``user_uuid`` (payload email / names are never read);
* the user must be a member of that org AND match the cycle's expected roster with a PROVEN address
  (``attributes.is_address_proven``), exactly like the compliance matching;
* a sign-off receipt needs a real submitted ``AssignmentUserSubmission`` row (so a forged-but-signed delivery cannot
  mail anybody);
* no answers are read or stored; events keep ids and a short reason code only.

The webhook and the sweep share :func:`deliver_signoff`, so both use the same dedupe keys:
``receipt:{assignment_uuid}:{user_id}`` and ``allset:{cycle_id}:{user_id}``. All mail goes through
``send_automation_email`` (test-mode redirect, claim-before-send).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import quote

from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.courses.assignments import Assignment, AssignmentUserSubmission
from src.db.courses.courses import Course
from src.db.mka_automation import MkaAutomationEvent, MkaAutomationSendLog
from src.db.mka_compliance import MkaComplianceCycle, MkaComplianceCycleCourse, MkaComplianceExpected
from src.db.mka_user_attributes import MkaUserAttributes
from src.db.organizations import Organization
from src.db.user_organizations import UserOrganization
from src.db.users import User
from src.services.email import utils as email_utils
from src.services.mka import attributes as attrs
from src.services.mka import automation_config as cfg
from src.services.mka import automation_templates as templates
from src.services.mka import compliance_scoring as cs
from src.services.mka.automation_send import (
    SendBudget,
    SendResult,
    send_automation_email,
    stale_claim_cutoff,
    stale_queued_condition,
)
from src.services.mka.compliance import SUBMITTED_STATES

logger = logging.getLogger(__name__)

HANDLED_EVENTS = ("assignment_submitted", "course_completed")
_DELIVERY_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
MAX_AGE = timedelta(minutes=10)
MAX_FUTURE_SKEW = timedelta(seconds=60)
MAX_SWEEP_DAYS = 60


def receipt_key(assignment_uuid: str, user_id: int) -> str:
    return f"receipt:{assignment_uuid}:{user_id}"


def allset_key(cycle_id: int, user_id: int) -> str:
    return f"allset:{cycle_id}:{user_id}"


# ---------------------------------------------------------------------------------------------------------
# payload (after signature verification)
# ---------------------------------------------------------------------------------------------------------


class BadPayload(ValueError):
    """Signed but unusable body (malformed, missing/old timestamp). The message is never echoed to the caller."""


@dataclass(frozen=True)
class Delivery:
    event: str
    delivery_id: str
    timestamp: datetime
    payload_org_id: Optional[int]
    user_uuid: Optional[str]
    assignment_uuid: Optional[str]
    course_uuid: Optional[str]


def _str(value: object, limit: int = 128) -> Optional[str]:
    return value[:limit] if isinstance(value, str) and value else None


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise BadPayload("timestamp")
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BadPayload("timestamp") from exc
    return moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment.astimezone(timezone.utc)


def parse_delivery(body: object, now: Optional[datetime] = None) -> Delivery:
    """Validate the (already authenticated) JSON body. Raises :class:`BadPayload`."""
    if not isinstance(body, dict):
        raise BadPayload("shape")
    event = body.get("event")
    delivery_id = body.get("delivery_id")
    if not isinstance(event, str) or not event or len(event) > 64:
        raise BadPayload("event")
    if not isinstance(delivery_id, str) or not _DELIVERY_ID.match(delivery_id):
        raise BadPayload("delivery_id")
    moment = _parse_timestamp(body.get("timestamp"))
    current = now or datetime.now(timezone.utc)
    if current - moment > MAX_AGE or moment - current > MAX_FUTURE_SKEW:
        raise BadPayload("replay_window")
    data = body.get("data") if isinstance(body.get("data"), dict) else {}
    user = data.get("user") if isinstance(data.get("user"), dict) else {}
    assignment = data.get("assignment") if isinstance(data.get("assignment"), dict) else {}
    course = data.get("course") if isinstance(data.get("course"), dict) else {}
    org = body.get("org_id")
    return Delivery(
        event=event,
        delivery_id=delivery_id,
        timestamp=moment,
        payload_org_id=org if isinstance(org, int) and not isinstance(org, bool) else None,
        user_uuid=_str(user.get("user_uuid")),
        assignment_uuid=_str(assignment.get("assignment_uuid")),
        course_uuid=_str(course.get("course_uuid")),
    )


# ---------------------------------------------------------------------------------------------------------
# eligibility + state (all DB)
# ---------------------------------------------------------------------------------------------------------


@dataclass
class Context:
    org: Organization
    cycle: MkaComplianceCycle
    user: User
    link: MkaComplianceCycleCourse  # the link whose sign-off was submitted
    rows: list  # the person's roster rows in the cycle
    required: list  # (link, Course) the person must sign off
    signed: dict = field(default_factory=dict)  # signoff assignment id -> naive-UTC datetime of the submission


def _parse_db_time(*values: object) -> Optional[datetime]:
    for value in values:
        if isinstance(value, datetime):
            return value if value.tzinfo is None else value.astimezone(timezone.utc).replace(tzinfo=None)
        if isinstance(value, str) and value:
            try:
                parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            except ValueError:
                continue
            return parsed if parsed.tzinfo is None else parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return None


async def _proven_roster_rows(db: AsyncSession, org_id: int, cycle_id: int, user: User) -> list:
    """The user's expected-roster rows for the cycle, only when this account's address is PROVEN."""
    row = (await db.execute(select(MkaUserAttributes).where(MkaUserAttributes.user_id == user.id))).scalars().first()
    if not attrs.is_address_proven(row, user):
        return []
    email = attrs.normalize_email(user.email)
    return list(
        (
            await db.execute(
                select(MkaComplianceExpected)
                .where(
                    MkaComplianceExpected.org_id == org_id,
                    MkaComplianceExpected.cycle_id == cycle_id,
                    MkaComplianceExpected.email == email,
                )
                .order_by(MkaComplianceExpected.id)  # type: ignore[arg-type]
            )
        ).scalars().all()
    )


async def _is_member(db: AsyncSession, org_id: int, user_id: int) -> bool:
    found = (
        await db.execute(
            select(UserOrganization.user_id).where(UserOrganization.org_id == org_id, UserOrganization.user_id == user_id)
        )
    ).first()
    return found is not None


async def build_context(
    db: AsyncSession, org_id: int, link: MkaComplianceCycleCourse, user: User
) -> tuple[Optional[Context], str]:
    """(context, reason). ``context`` is None when the person must NOT get mail; ``reason`` is a short code."""
    if link.org_id != org_id:
        return None, "org_mismatch"
    org = (await db.execute(select(Organization).where(Organization.id == org_id))).scalars().first()
    cycle = (
        await db.execute(
            select(MkaComplianceCycle).where(MkaComplianceCycle.id == link.cycle_id, MkaComplianceCycle.org_id == org_id)
        )
    ).scalars().first()
    if org is None or cycle is None:
        return None, "cycle_not_found"
    if not await _is_member(db, org_id, user.id):  # type: ignore[arg-type]
        return None, "not_org_member"
    rows = await _proven_roster_rows(db, org_id, cycle.id, user)  # type: ignore[arg-type]
    if not rows:
        return None, "not_on_roster_or_unproven"

    pairs = (
        await db.execute(
            select(MkaComplianceCycleCourse, Course)
            .join(Course, Course.id == MkaComplianceCycleCourse.course_id)
            .where(
                MkaComplianceCycleCourse.cycle_id == cycle.id,
                MkaComplianceCycleCourse.org_id == org_id,
                Course.org_id == org_id,
            )
            .order_by(MkaComplianceCycleCourse.kind, MkaComplianceCycleCourse.department, MkaComplianceCycleCourse.id)  # type: ignore[arg-type]
        )
    ).all()
    my_depts = {r.department for r in rows if r.department}
    required = [
        (cc, course)
        for cc, course in pairs
        if cc.signoff_assignment_id and (cc.kind == "general" or (cc.kind == "department" and cc.department in my_depts))
    ]
    if link.id not in {cc.id for cc, _ in required}:
        return None, "course_not_required_of_user"

    signoff_ids = [cc.signoff_assignment_id for cc, _ in required]
    subs = (
        await db.execute(
            select(AssignmentUserSubmission)
            .join(Assignment, Assignment.id == AssignmentUserSubmission.assignment_id)
            .where(
                AssignmentUserSubmission.user_id == user.id,
                AssignmentUserSubmission.assignment_id.in_(signoff_ids),  # type: ignore[attr-defined]
                AssignmentUserSubmission.submission_status.in_(SUBMITTED_STATES),  # type: ignore[attr-defined]
                Assignment.org_id == org_id,
            )
        )
    ).scalars().all()
    signed = {s.assignment_id: _parse_db_time(s.update_date, s.creation_date) for s in subs}
    return Context(org, cycle, user, link, rows, required, signed), "ok"


def is_all_set(ctx: Context) -> bool:
    """Every row of the person is ``attested`` under the compliance rule ``attested_requires=both``.

    Reuses ``compliance_scoring.stage_of`` per roster row (general + that row's department course)."""
    config = cs.with_config({"attested_requires": "both"})
    by_kind_dept = {(cc.kind, cc.department or ""): cc for cc, _ in ctx.required}
    general = by_kind_dept.get(("general", ""))

    def progress(cc: Optional[MkaComplianceCycleCourse]) -> Optional[dict]:
        if cc is None:
            return None
        at = ctx.signed.get(cc.signoff_assignment_id)
        return {
            "enrolled": True, "lessons_done": 0, "lessons_total": 0, "completed_at": None,
            "attested_at": at.isoformat() if at else None, "last_activity_at": None, "trailrun_status": None,
        }

    for row in ctx.rows:
        dept = by_kind_dept.get(("department", row.department)) if row.department else None
        record = {
            "signed_in": True, "department_slug": row.department, "general": progress(general),
            "dept_course": progress(dept), "dept_required": dept is not None, "general_required": general is not None,
        }
        if cs.stage_of(record, config) != "attested":
            return False
    return True


def remaining_titles(ctx: Context) -> list[str]:
    return [course.name for cc, course in ctx.required if cc.signoff_assignment_id not in ctx.signed]


async def _course_url(db: AsyncSession, org: Organization, course_uuid: str) -> str:
    base = await email_utils.get_org_signup_base_url(org.slug, None, db, org.id)
    if not base:
        raise RuntimeError("no frontend base URL is configured")
    bare = course_uuid[len("course_"):] if course_uuid.startswith("course_") else course_uuid
    return f"{base.rstrip('/')}/course/{quote(bare, safe='')}"


# ---------------------------------------------------------------------------------------------------------
# send
# ---------------------------------------------------------------------------------------------------------


@dataclass
class Outcome:
    """What one submission produced: ``skipped`` is a reason code (no mail), ``results`` the SendResults."""

    skipped: Optional[str] = None
    results: list = field(default_factory=list)


def _addressee(ctx: Context) -> str:
    first = (ctx.user.first_name or "").strip()
    row = ctx.rows[0]
    return templates.addressee(first_name=first or None, role_title=row.role_title, majlis=row.majlis)


async def deliver_signoff(
    db: AsyncSession,
    org_id: int,
    link: MkaComplianceCycleCourse,
    user: User,
    assignment: Assignment,
    *,
    dry_run: bool,
    budget: Optional[SendBudget] = None,
    now: Optional[datetime] = None,
    receipt_done: bool = False,
    allset_done: bool = False,
) -> Outcome:
    """Receipt (and, when it completes the person, the all-set message) for one sign-off. Idempotent.

    ``*_done`` lets the sweep skip a message it already knows is handled (so a dry run does not preview it)."""
    ctx, reason = await build_context(db, org_id, link, user)
    if ctx is None:
        return Outcome(skipped=reason)
    signed_at = ctx.signed.get(link.signoff_assignment_id)
    if signed_at is None:
        return Outcome(skipped="no_submission")
    course = next(c for cc, c in ctx.required if cc.id == link.id)
    try:
        url = await _course_url(db, ctx.org, course.course_uuid)
    except Exception:
        logger.error("receipt skipped: no frontend base URL org=%s", org_id)
        return Outcome(skipped="no_base_url")
    contact = cfg.contact_email() or None
    who = _addressee(ctx)
    results: list = []

    if not receipt_done:
        rendered = templates.render_receipt(
            addressee=who, course_title=course.name, signed_at=signed_at, cycle_label=ctx.cycle.label,
            remaining=remaining_titles(ctx), course_url=url, contact_email=contact,
        )
        results.append(
            await send_automation_email(
                db, org_id=org_id, kind="receipt", dedupe_key=receipt_key(assignment.assignment_uuid, user.id),  # type: ignore[arg-type]
                to_email=user.email, subject=rendered.subject, html_body=rendered.html, user_id=user.id,
                cycle_id=ctx.cycle.id, course_id=course.id, dry_run=dry_run, budget=budget, now=now,
            )
        )
    if not allset_done and is_all_set(ctx):
        done = templates.render_allset(addressee=who, cycle_label=ctx.cycle.label, url=url, contact_email=contact)
        results.append(
            await send_automation_email(
                db, org_id=org_id, kind="allset", dedupe_key=allset_key(ctx.cycle.id, user.id),  # type: ignore[arg-type]
                to_email=user.email, subject=done.subject, html_body=done.html, user_id=user.id,
                cycle_id=ctx.cycle.id, course_id=course.id, dry_run=dry_run, budget=budget, now=now,
            )
        )
    return Outcome(results=results)


# ---------------------------------------------------------------------------------------------------------
# webhook processing
# ---------------------------------------------------------------------------------------------------------


async def _organization_exists(db: AsyncSession, org_id: Optional[int]) -> bool:
    if org_id is None:
        return False
    return (await db.execute(select(Organization.id).where(Organization.id == org_id))).first() is not None


async def _resolve_entities(db: AsyncSession, d: Delivery):
    """(org_id from the DB entity or None, assignment, course). Never from the payload org."""
    assignment = course = None
    if d.event == "assignment_submitted" and d.assignment_uuid:
        assignment = (
            await db.execute(select(Assignment).where(Assignment.assignment_uuid == d.assignment_uuid))
        ).scalars().first()
        if assignment is not None:
            return assignment.org_id, assignment, None
    if d.event == "course_completed" and d.course_uuid:
        course = (await db.execute(select(Course).where(Course.course_uuid == d.course_uuid))).scalars().first()
        if course is not None:
            return course.org_id, None, course
    return None, None, None


async def _claim_event(db: AsyncSession, org_id: int, d: Delivery, user_uuid, course_uuid, assignment_uuid):
    row = MkaAutomationEvent(
        org_id=org_id, delivery_id=d.delivery_id, event=d.event[:64], user_uuid=user_uuid,
        course_uuid=course_uuid, assignment_uuid=assignment_uuid, status="received",
    )
    try:
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError:
        return None
    await db.commit()
    return row


async def _finish_event(db: AsyncSession, row: MkaAutomationEvent, status: str, note: Optional[str], user_id=None) -> None:
    row.status = status
    row.note = note[:200] if note else None
    if user_id is not None:
        row.user_id = user_id
    db.add(row)
    await db.commit()


def _summarise(outcome: Outcome) -> str:
    if outcome.skipped:
        return outcome.skipped
    return ",".join(r.status for r in outcome.results)


async def handle_delivery(db: AsyncSession, d: Delivery) -> dict:
    """Process ONE authenticated, fresh delivery. Returns ``{"status": ...}`` for the HTTP response."""
    org_id, assignment, course = await _resolve_entities(db, d)
    recorded_against_hint = False
    if org_id is None:  # unknown / unhandled entity: record it under the payload org, only if that org exists
        if await _organization_exists(db, d.payload_org_id):
            org_id, recorded_against_hint = d.payload_org_id, True
        else:
            return {"status": "ignored"}

    event_row = await _claim_event(db, org_id, d, d.user_uuid, d.course_uuid, d.assignment_uuid)  # type: ignore[arg-type]
    if event_row is None:
        return {"status": "duplicate"}

    try:
        if d.event not in HANDLED_EVENTS:
            await _finish_event(db, event_row, "ignored", "unhandled_event")
            return {"status": "ignored"}
        if recorded_against_hint:
            await _finish_event(db, event_row, "ignored", "unknown_entity")
            return {"status": "ignored"}
        if d.payload_org_id is not None and d.payload_org_id != org_id:
            await _finish_event(db, event_row, "ignored", "org_mismatch")
            return {"status": "ignored"}
        if not d.user_uuid:
            await _finish_event(db, event_row, "ignored", "no_user")
            return {"status": "ignored"}
        user = (await db.execute(select(User).where(User.user_uuid == d.user_uuid))).scalars().first()
        if user is None:
            await _finish_event(db, event_row, "ignored", "unknown_user")
            return {"status": "ignored"}

        if d.event == "assignment_submitted":
            return await _on_assignment_submitted(db, event_row, org_id, assignment, user)  # type: ignore[arg-type]
        return await _on_course_completed(db, event_row, org_id, course, user)  # type: ignore[arg-type]
    except Exception as exc:  # never 5xx into LearnHouse for a processing fault: the sweep recovers it
        await db.rollback()
        logger.exception("receipt processing failed org=%s event=%s", org_id, event_row.id)
        try:
            await _finish_event(db, event_row, "error", type(exc).__name__)
        except Exception:
            await db.rollback()
        return {"status": "error"}


async def _links_for_assignment(db: AsyncSession, org_id: int, assignment_id: int):
    return list(
        (
            await db.execute(
                select(MkaComplianceCycleCourse).where(
                    MkaComplianceCycleCourse.org_id == org_id,
                    (MkaComplianceCycleCourse.signoff_assignment_id == assignment_id)
                    | (MkaComplianceCycleCourse.contact_check_assignment_id == assignment_id),
                )
            )
        ).scalars().all()
    )


async def _on_assignment_submitted(db, event_row, org_id: int, assignment: Assignment, user: User) -> dict:
    links = await _links_for_assignment(db, org_id, assignment.id)  # type: ignore[arg-type]
    if not links:
        await _finish_event(db, event_row, "ignored", "not_cycle_assignment", user.id)
        return {"status": "ignored"}
    signoffs = [link for link in links if link.signoff_assignment_id == assignment.id]
    if not signoffs:  # contact-check only: recorded, no receipt (spec 2B names sign-offs only)
        await _finish_event(db, event_row, "processed", "contact_check_no_receipt", user.id)
        return {"status": "processed"}
    notes: list[str] = []
    for link in signoffs:
        outcome = await deliver_signoff(db, org_id, link, user, assignment, dry_run=False)
        notes.append(_summarise(outcome))
    await _finish_event(db, event_row, "processed", ";".join(notes), user.id)
    return {"status": "processed"}


async def _on_course_completed(db, event_row, org_id: int, course: Course, user: User) -> dict:
    links = list(
        (
            await db.execute(
                select(MkaComplianceCycleCourse).where(
                    MkaComplianceCycleCourse.org_id == org_id, MkaComplianceCycleCourse.course_id == course.id
                )
            )
        ).scalars().all()
    )
    if not links:
        await _finish_event(db, event_row, "ignored", "not_cycle_course", user.id)
        return {"status": "ignored"}
    # Completion alone is not a sign-off and sends nothing by itself; but if the learner's sign-off exists and its own
    # webhook was dropped, deliver that (idempotent, same dedupe keys as the sweep).
    notes: list[str] = []
    for link in links:
        if not link.signoff_assignment_id:
            continue
        assignment = (
            await db.execute(
                select(Assignment).where(Assignment.id == link.signoff_assignment_id, Assignment.org_id == org_id)
            )
        ).scalars().first()
        if assignment is None:
            continue
        outcome = await deliver_signoff(db, org_id, link, user, assignment, dry_run=False)
        notes.append(_summarise(outcome))
    await _finish_event(db, event_row, "processed", ";".join(notes) or "course_completed_recorded", user.id)
    return {"status": "processed"}


# ---------------------------------------------------------------------------------------------------------
# sweep
# ---------------------------------------------------------------------------------------------------------


async def _handled(db: AsyncSession, org_id: int, kind: str, key: str, now: Optional[datetime] = None) -> bool:
    """A row for the key exists in the CURRENT mode namespace (test mode uses ``test:``) and is not ``failed``.
    A ``queued`` claim past its lease (a crash between claim and send, review M2) is NOT handled: the sweep offers it to
    ``send_automation_email`` again, which takes it over atomically and re-sends once."""
    try:
        effective = f"test:{key}" if cfg.test_recipient() else key
    except cfg.InvalidTestRecipient:
        return True  # sends are refused anyway
    moment = now or datetime.now(timezone.utc)
    stale = stale_queued_condition(stale_claim_cutoff(moment.astimezone(timezone.utc).replace(tzinfo=None)))
    found = (
        await db.execute(
            select(MkaAutomationSendLog.id).where(
                MkaAutomationSendLog.org_id == org_id,
                MkaAutomationSendLog.kind == kind,
                MkaAutomationSendLog.dedupe_key == effective,
                MkaAutomationSendLog.status.in_(("queued", "sent", "suppressed")),  # type: ignore[attr-defined]
                ~stale,
            )
        )
    ).first()
    return found is not None


async def run_sweep(
    db: AsyncSession,
    *,
    dry_run: bool,
    days: int,
    budget: Optional[SendBudget] = None,
    org_id: Optional[int] = None,
    now: Optional[datetime] = None,
) -> dict:
    """Send receipts that the webhook never delivered. Counts only: no addresses, names or subjects."""
    days = max(1, min(int(days), MAX_SWEEP_DAYS))
    current = now or datetime.now(timezone.utc)
    cutoff = str((current.astimezone(timezone.utc) - timedelta(days=days)).replace(tzinfo=None))
    budget = budget or SendBudget()
    counts: dict[str, int] = {}

    def bump(name: str) -> None:
        counts[name] = counts.get(name, 0) + 1

    org_ids = [org_id] if org_id is not None else [
        o for (o,) in (await db.execute(select(MkaComplianceCycleCourse.org_id).distinct())).all()
    ]
    candidates = 0
    for oid in sorted(org_ids):
        links = list(
            (
                await db.execute(
                    select(MkaComplianceCycleCourse).where(
                        MkaComplianceCycleCourse.org_id == oid, MkaComplianceCycleCourse.signoff_assignment_id.is_not(None)  # type: ignore[union-attr]
                    )
                )
            ).scalars().all()
        )
        by_assignment = {link.signoff_assignment_id: link for link in links}
        if not by_assignment:
            continue
        rows = (
            await db.execute(
                select(AssignmentUserSubmission, Assignment, User)
                .join(Assignment, Assignment.id == AssignmentUserSubmission.assignment_id)
                .join(User, User.id == AssignmentUserSubmission.user_id)
                .where(
                    Assignment.org_id == oid,
                    AssignmentUserSubmission.assignment_id.in_(list(by_assignment)),  # type: ignore[attr-defined]
                    AssignmentUserSubmission.submission_status.in_(SUBMITTED_STATES),  # type: ignore[attr-defined]
                    AssignmentUserSubmission.update_date >= cutoff,
                )
                .order_by(AssignmentUserSubmission.update_date, AssignmentUserSubmission.id)  # type: ignore[arg-type]
            )
        ).all()
        for sub, assignment, user in rows:
            link = by_assignment[sub.assignment_id]
            candidates += 1
            receipt_done = await _handled(db, oid, "receipt", receipt_key(assignment.assignment_uuid, user.id), current)  # type: ignore[arg-type]
            allset_done = await _handled(db, oid, "allset", allset_key(link.cycle_id, user.id), current)  # type: ignore[arg-type]
            if receipt_done and allset_done:
                bump("already_handled")
                continue
            if not budget.can_send() and not dry_run:
                bump("budget_exhausted")
                continue
            outcome = await deliver_signoff(
                db, oid, link, user, assignment, dry_run=dry_run, budget=budget, now=now,
                receipt_done=receipt_done, allset_done=allset_done,
            )
            if outcome.skipped:
                bump(f"skipped_{outcome.skipped}")
                continue
            if not outcome.results:  # e.g. receipt already sent and the person is not complete yet
                bump("already_handled")
            for result in outcome.results:
                bump(result.status)
    return {
        "dry_run": dry_run, "days": days, "candidates": candidates, "results": dict(sorted(counts.items())),
        "budget": budget.summary(),
    }


__all__ = [
    "BadPayload", "Delivery", "HANDLED_EVENTS", "Outcome", "SendResult", "allset_key", "deliver_signoff",
    "handle_delivery", "parse_delivery", "receipt_key", "run_sweep",
]
