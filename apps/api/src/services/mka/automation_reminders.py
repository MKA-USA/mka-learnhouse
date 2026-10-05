"""MKA fork: compliance reminders, the weekly digest and the manual "Remind" button (spec 2026-10-05 section 2C).

ALL email goes through :func:`automation_send.send_automation_email` (kill switch, test-recipient redirect,
claim-before-send, weekly cap, per-run budget) and the foundation templates. Nothing here talks to the transport.

Who is reminded
---------------
Per person (deduped by e-mail, one e-mail listing everything outstanding) for every required course of the ACTIVE
cycle whose per-course status is ``not_signed_in`` / ``not_started`` / ``in_progress`` / ``overdue``.
``completed`` (every lesson done, sign-off still missing) is ALSO outstanding: the duty is the sign-off, and it is
worded as "in progress". ``attested`` is never reminded. Departments in ``MKA_REMINDER_EXCLUDED_DEPARTMENTS``
(default ``atfal``) are skipped.

Schedule
--------
``MKA_REMINDER_SCHEDULE`` (``automation_config.is_reminder_day``) evaluated on the date in the cycle timezone;
reminders also need the cycle to have started. The digest goes out on Mondays (cycle timezone).

Privacy
-------
Run reports and logs carry COUNTS only: never an address, a name or an answer. The digest names role titles only.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.mka_automation import MkaAutomationEvent
from src.db.mka_compliance import MkaComplianceCycle, MkaComplianceCycleCourse
from src.db.organizations import Organization
from src.services.email import utils as email_utils
from src.services.mka import automation_config as cfg
from src.services.mka import automation_templates as tpl
from src.services.mka import compliance as svc
from src.services.mka import compliance_scope as scope_svc
from src.services.mka.automation_gdpr import is_role_mailbox
from src.services.mka.automation_send import (
    SendBudget,
    current_iso_week,
    reminded_this_week,
    reminder_dedupe_key,
    send_automation_email,
)

logger = logging.getLogger(__name__)

# Per-course statuses that still need a nudge. ``completed`` = lessons done but no sign-off yet.
OUTSTANDING = ("not_signed_in", "not_started", "in_progress", "overdue", "completed")
_URGENCY = {"overdue": 4, "not_signed_in": 3, "not_started": 2, "in_progress": 1, "completed": 1}
MANUAL_EVENT = "manual_remind"
MANUAL_WINDOW = timedelta(hours=24)
DEFAULT_EXCLUDED_DEPARTMENTS = "atfal"


# ---------------------------------------------------------------------------------------------------------
# config / clock
# ---------------------------------------------------------------------------------------------------------


def excluded_departments() -> frozenset:
    """Department slugs that are never reminded (``MKA_REMINDER_EXCLUDED_DEPARTMENTS``, default ``atfal``)."""
    import os

    raw = os.environ.get("MKA_REMINDER_EXCLUDED_DEPARTMENTS")
    text = DEFAULT_EXCLUDED_DEPARTMENTS if raw is None else raw
    return frozenset(p.strip().lower() for p in text.split(",") if p.strip())


def current_instant() -> datetime:
    """The current instant (aware, UTC). Tests monkeypatch this."""
    return datetime.now(timezone.utc)


def cycle_today(now: datetime) -> date:
    aware = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    return aware.astimezone(cfg.cycle_tz()).date()


def _links_url(org_slug: str) -> Optional[str]:
    base = email_utils._configured_frontend_base_url()
    return f"{base}/orgs/{org_slug}/courses" if base else None


# ---------------------------------------------------------------------------------------------------------
# who is outstanding
# ---------------------------------------------------------------------------------------------------------


@dataclass
class Person:
    email: str
    user_id: Optional[int]
    role_title: str
    place: str  # Majlis, else region
    person_name: Optional[str]
    items: list = field(default_factory=list)  # (course title, template status)

    @property
    def worst(self) -> str:
        return max((s for _, s in self.items), key=lambda s: _URGENCY.get(s, 0))


def _template_status(status: str) -> str:
    return "in_progress" if status == "completed" else status


def collect_people(
    per_course: list, user_map: dict, excluded: frozenset
) -> tuple[dict, dict]:
    """``per_course``: [(course title, records)]. Returns (outstanding people by e-mail, counts)."""
    people: dict[str, Person] = {}
    counts = {"skipped_attested": 0, "skipped_excluded": 0}
    for title, records in per_course:
        for r in records:
            if (r.get("department_slug") or "").lower() in excluded:
                counts["skipped_excluded"] += 1
                continue
            status = r["status"]
            if status == "attested":
                counts["skipped_attested"] += 1
                continue
            if status not in OUTSTANDING:
                continue
            email = (r["email"] or "").strip().lower()
            if not email:
                continue
            first_title = (r.get("role_title") or "").split(" / ")[0]
            p = people.get(email)
            if p is None:
                p = people[email] = Person(
                    email, user_map.get(email), first_title, (r.get("majlis") or r.get("region") or ""),
                    r.get("person_name"),
                )
            p.items.append((title, _template_status(status)))
    return people, counts


def addressee_for(p: Person) -> str:
    """Role mailboxes are addressed by role title (+ Majlis); a personal account by first name when we know it."""
    if not is_role_mailbox(p.email):
        first = (p.person_name or "").strip().split(" ")[0] if p.person_name else ""
        if first:
            return tpl.addressee(first_name=first)
    return tpl.addressee(role_title=p.role_title, majlis=p.place)


async def _org_cycle(db: AsyncSession, org_id: int, today: date) -> Optional[MkaComplianceCycle]:
    cycle = await scope_svc.get_cycle(db, org_id, None, today.isoformat())
    return cycle


async def _course_records(db: AsyncSession, org_id: int, cycle: MkaComplianceCycle, as_of: str):
    rows = await scope_svc.cycle_courses(db, org_id, cycle.id)  # type: ignore[arg-type]
    ds = await svc.load_dataset(db, org_id, cycle, [cc for cc, _ in rows], {c.id: c for _, c in rows})
    per_course = [(course.name, svc.course_records(ds, cc, as_of)) for cc, course in rows]
    return ds, rows, per_course


# ---------------------------------------------------------------------------------------------------------
# sending a batch (shared by the cron run and the manual button)
# ---------------------------------------------------------------------------------------------------------


def _blank_counts() -> dict:
    return {
        "would_send": 0, "sent": 0, "skipped_recent": 0, "skipped_attested": 0, "skipped_excluded": 0,
        "suppressed": 0, "failed": 0, "disabled": 0, "stopped": None, "disabled_reason": None,
    }


async def _send_reminders(
    db: AsyncSession, *, org_id: int, cycle: MkaComplianceCycle, people: dict, url: str, today: date,
    dry_run: bool, budget: SendBudget, now: datetime, counts: dict,
) -> dict:
    week = current_iso_week(now)
    for email in sorted(people):
        p = people[email]
        if await reminded_this_week(db, org_id, email, week):
            counts["skipped_recent"] += 1
            continue
        mail = tpl.render_reminder(
            addressee=addressee_for(p), cycle_label=cycle.label, outstanding=p.items, deadline=cycle.deadline_on,
            today=today, url=url, contact_email=cfg.contact_email(),
        )
        result = await send_automation_email(
            db, org_id=org_id, kind="reminder", dedupe_key=reminder_dedupe_key(email, week), to_email=email,
            subject=mail.subject, html_body=mail.html, user_id=p.user_id, cycle_id=cycle.id, dry_run=dry_run,
            budget=budget, now=now,
        )
        status = result.status
        if status == "dry_run":
            counts["would_send"] += 1
        elif status == "sent":
            counts["sent"] += 1
        elif status in ("already_handled", "capped"):
            counts["skipped_recent"] += 1
        elif status in ("failed", "suppressed"):
            counts[status] += 1
        elif status == "budget_exhausted":
            counts["stopped"] = result.reason
            break
        elif status == "disabled":
            counts["disabled"] += 1
            counts["disabled_reason"] = result.reason
            break  # feature off / invalid test address: nothing will go out, stop instead of spinning
    return counts


# ---------------------------------------------------------------------------------------------------------
# digest
# ---------------------------------------------------------------------------------------------------------


@dataclass
class DigestTarget:
    email: str
    role_title: str
    place: str
    departments: set = field(default_factory=set)
    regions: set = field(default_factory=set)


def digest_targets(roster: list, excluded: frozenset) -> list[DigestTarget]:
    """Mohtamim (national, a department) and regional Qaid roster rows; scope comes from THEIR row only."""
    rules = svc.CONTACT_CHECK_RULES
    out: dict[str, DigestTarget] = {}
    for row in roster:
        dept = (row.department or "").lower()
        if dept in excluded:
            continue
        title = (row.role_title or "").lower()
        level = (row.level or "").lower()
        is_head = level == "national" and dept and any(k in title for k in rules["dept_head"]["role_keywords"])
        is_qaid = level == "regional" and bool(row.region) and any(k in title for k in rules["regional_qaid"]["role_keywords"])
        if not (is_head or is_qaid):
            continue
        t = out.setdefault(row.email.strip().lower(), DigestTarget(
            row.email.strip().lower(), row.role_title or "", row.majlis or row.region or ""))
        if is_head:
            t.departments.add(dept)
        if is_qaid:
            t.regions.add(row.region)
    return sorted(out.values(), key=lambda t: t.email)


def digest_view(target: DigestTarget, roster: list, per_course: list, user_map: dict, excluded: frozenset):
    """(counts, role titles that need a nudge) for the people in the target's scope. Role titles only."""
    people, _ = collect_people(per_course, user_map, excluded)
    attested_pool = {
        (r["email"] or "").strip().lower()
        for _, records in per_course for r in records
        if r["status"] == "attested" and (r.get("department_slug") or "").lower() not in excluded
    }
    in_scope: set = set()
    for row in roster:
        email = row.email.strip().lower()
        if email == target.email or (row.department or "").lower() in excluded:
            continue
        if (row.department or "").lower() in target.departments or (row.region and row.region in target.regions):
            in_scope.add(email)
    counts = {"attested": 0, "in_progress": 0, "not_started": 0, "not_signed_in": 0, "overdue": 0}
    nudge: list[str] = []
    for email in sorted(in_scope):
        p = people.get(email)
        if p is None:
            if email in attested_pool:
                counts["attested"] += 1
            continue
        counts[p.worst if p.worst in counts else "in_progress"] += 1
        nudge.append(tpl.addressee(role_title=p.role_title, majlis=p.place) or "Unnamed role")
    return counts, sorted(nudge)


async def _send_digests(
    db: AsyncSession, *, org: Organization, cycle: MkaComplianceCycle, ds, per_course: list, url: str,
    dry_run: bool, budget: SendBudget, now: datetime, excluded: frozenset,
) -> dict:
    counts = {"would_send": 0, "sent": 0, "skipped_recent": 0, "skipped_nothing_outstanding": 0, "failed": 0,
              "suppressed": 0, "disabled": 0, "stopped": None, "disabled_reason": None}
    week = current_iso_week(now)
    for target in digest_targets(ds.roster, excluded):
        view, nudge = digest_view(target, ds.roster, per_course, ds.user_map, excluded)
        if not nudge:
            counts["skipped_nothing_outstanding"] += 1
            continue
        scope_label = " / ".join(
            sorted([svc.dept_name(d) for d in target.departments] + [f"{r} region" for r in target.regions])
        )
        mail = tpl.render_digest(
            addressee=tpl.addressee(role_title=target.role_title, majlis=target.place), cycle_label=cycle.label,
            scope_label=scope_label, counts=view, needs_nudge=nudge, url=url, contact_email=cfg.contact_email(),
        )
        result = await send_automation_email(
            db, org_id=org.id, kind="digest", dedupe_key=f"digest:{week}:{target.email}", to_email=target.email,  # type: ignore[arg-type]
            subject=mail.subject, html_body=mail.html, user_id=ds.user_map.get(target.email), cycle_id=cycle.id,
            dry_run=dry_run, budget=budget, now=now,
        )
        status = result.status
        if status == "dry_run":
            counts["would_send"] += 1
        elif status == "sent":
            counts["sent"] += 1
        elif status in ("already_handled", "capped"):
            counts["skipped_recent"] += 1
        elif status in ("failed", "suppressed"):
            counts[status] += 1
        elif status == "budget_exhausted":
            counts["stopped"] = result.reason
            break
        elif status == "disabled":
            counts["disabled"] += 1
            counts["disabled_reason"] = result.reason
            break
    return counts


# ---------------------------------------------------------------------------------------------------------
# the cron run
# ---------------------------------------------------------------------------------------------------------


async def run_org(
    db: AsyncSession, org: Organization, *, dry_run: bool, kind: str, now: datetime, budget: SendBudget
) -> dict:
    today = cycle_today(now)
    out: dict = {"org_id": org.id, "today": today.isoformat(), "cycle": None}
    cycle = await _org_cycle(db, org.id, today)  # type: ignore[arg-type]
    if cycle is None or cycle.starts_on > today:
        reason = "no_cycle" if cycle is None else "cycle_not_started"
        for k in ("reminder", "digest"):
            if kind in (k, "all"):
                out[k] = {"ran": False, "reason": reason}
        return out
    out["cycle"] = cycle.label
    reminder_day = cfg.is_reminder_day(today, cycle.deadline_on, cfg.reminder_schedule())
    digest_day = today.weekday() == 0
    want_reminder = kind in ("reminder", "all")
    want_digest = kind in ("digest", "all")
    if want_reminder and not reminder_day:
        out["reminder"] = {"ran": False, "reason": "not_a_reminder_day"}
        want_reminder = False
    if want_digest and not digest_day:
        out["digest"] = {"ran": False, "reason": "not_a_monday"}
        want_digest = False
    if not (want_reminder or want_digest):
        return out
    if not dry_run and not cfg.reminders_enabled():  # a real send needs the master switch AND the feature flag
        for k, wanted in (("reminder", want_reminder), ("digest", want_digest)):
            if wanted:
                out[k] = {"ran": False, "reason": "feature_off"}
        return out
    url = _links_url(org.slug)
    if not url:
        for k, wanted in (("reminder", want_reminder), ("digest", want_digest)):
            if wanted:
                out[k] = {"ran": False, "reason": "no_frontend_url"}
        logger.error("reminders: no frontend base URL configured (org=%s)", org.id)
        return out

    excluded = excluded_departments()
    ds, _rows, per_course = await _course_records(db, org.id, cycle, today.isoformat())  # type: ignore[arg-type]
    if want_reminder:
        people, counts = collect_people(per_course, ds.user_map, excluded)
        counts = {**_blank_counts(), **counts}
        counts = await _send_reminders(
            db, org_id=org.id, cycle=cycle, people=people, url=url, today=today, dry_run=dry_run, budget=budget,
            now=now, counts=counts,
        )
        out["reminder"] = {"ran": True, "candidates": len(people), **counts}
    if want_digest:
        res = await _send_digests(
            db, org=org, cycle=cycle, ds=ds, per_course=per_course, url=url, dry_run=dry_run, budget=budget,
            now=now, excluded=excluded,
        )
        out["digest"] = {"ran": True, **res}
    return out


async def run_all(db: AsyncSession, *, dry_run: bool, kind: str, now: Optional[datetime] = None) -> dict:
    """Run for every org that has a compliance cycle. One shared budget: the caps are per RUN, not per org."""
    moment = now or current_instant()
    budget = SendBudget()
    org_ids = (await db.execute(select(MkaComplianceCycle.org_id).distinct())).scalars().all()
    reports = []
    for org_id in sorted(org_ids):
        org = await db.get(Organization, org_id)
        if org is None:
            continue
        try:
            reports.append(await run_org(db, org, dry_run=dry_run, kind=kind, now=moment, budget=budget))
        except Exception as exc:  # one broken org must not stop the others; never log its data
            await db.rollback()
            logger.error("reminders: org=%s failed (%s)", org_id, type(exc).__name__)
            reports.append({"org_id": org_id, "error": type(exc).__name__})
    return {"dry_run": dry_run, "kind": kind, "test_mode": cfg.status_snapshot()["test_mode"], "orgs": reports}


# ---------------------------------------------------------------------------------------------------------
# the manual "Remind" button
# ---------------------------------------------------------------------------------------------------------


class ManualRemindBlocked(Exception):
    """Raised for the 24 h limit (429) and a disabled feature (409)."""

    def __init__(self, status_code: int, detail: str, retry_after: Optional[int] = None):
        super().__init__(detail)
        self.status_code, self.detail, self.retry_after = status_code, detail, retry_after


async def _last_manual(db: AsyncSession, org_id: int, course_uuid: str, since: datetime, before_id: Optional[int] = None):
    stmt = select(func.max(MkaAutomationEvent.received_at)).where(
        MkaAutomationEvent.org_id == org_id,
        MkaAutomationEvent.event == MANUAL_EVENT,
        MkaAutomationEvent.course_uuid == course_uuid,
        MkaAutomationEvent.status.in_(("received", "processed")),  # type: ignore[attr-defined]
        MkaAutomationEvent.received_at > since,
    )
    if before_id is not None:
        stmt = stmt.where(MkaAutomationEvent.id < before_id)
    return (await db.execute(stmt)).scalar_one()


def _naive_utc(now: datetime) -> datetime:
    return now.astimezone(timezone.utc).replace(tzinfo=None) if now.tzinfo else now


async def remind_course(
    db: AsyncSession,
    *,
    org: Organization,
    cycle: MkaComplianceCycle,
    link: MkaComplianceCycleCourse,
    course,
    viewer_id: int,
    dry_run: bool,
    now: Optional[datetime] = None,
) -> dict:
    """Remind everyone still outstanding on ONE course. The caller has already resolved scope (404 otherwise)."""
    moment = now or current_instant()
    naive_now = _naive_utc(moment)
    # Review H1: a manual remind only ever acts on the CURRENT, already-started cycle, resolved HERE with the same
    # default-cycle rule as the cron run. The cycle the client asked for is only checked against it, never trusted.
    today = cycle_today(moment)
    current = await _org_cycle(db, org.id, today)  # type: ignore[arg-type]
    if current is None or current.id != cycle.id or cycle.starts_on > today:
        raise ManualRemindBlocked(409, "Reminders only apply to the current cycle")
    last = await _last_manual(db, org.id, link.course_uuid, naive_now - MANUAL_WINDOW)  # type: ignore[arg-type]
    if last is not None:
        wait = int((last + MANUAL_WINDOW - naive_now).total_seconds())
        raise ManualRemindBlocked(429, "This course was already reminded in the last 24 hours", max(wait, 1))
    if not dry_run and not cfg.reminders_enabled():
        raise ManualRemindBlocked(409, "Reminders are not switched on")
    url = _links_url(org.slug)
    if not url:
        raise ManualRemindBlocked(409, "Reminders are not configured")

    ds = await svc.load_dataset(db, org.id, cycle, [link], {course.id: course})  # type: ignore[arg-type]
    records = svc.course_records(ds, link, today.isoformat())
    people, counts = collect_people([(course.name, records)], ds.user_map, excluded_departments())
    counts = {**_blank_counts(), **counts}

    event_id: Optional[int] = None
    if not dry_run:
        event = MkaAutomationEvent(
            org_id=org.id, event=MANUAL_EVENT, user_id=viewer_id, course_uuid=link.course_uuid, status="received",
            received_at=naive_now,
        )
        db.add(event)
        await db.commit()
        event_id = event.id
        # TOCTOU: two clicks can both pass the check above; the earlier row wins, the later one backs out.
        if await _last_manual(db, org.id, link.course_uuid, naive_now - MANUAL_WINDOW, before_id=event_id) is not None:  # type: ignore[arg-type]
            event.status = "ignored"
            await db.commit()
            raise ManualRemindBlocked(429, "This course was already reminded in the last 24 hours", 86400)

    counts = await _send_reminders(
        db, org_id=org.id, cycle=cycle, people=people, url=url, today=today, dry_run=dry_run,
        budget=SendBudget(), now=moment, counts=counts,
    )
    if event_id is not None:
        event = await db.get(MkaAutomationEvent, event_id)
        nothing_went = counts["sent"] + counts["failed"] + counts["suppressed"] == 0 and counts["disabled"] > 0
        if event is not None:
            event.status = "ignored" if nothing_went else "processed"
            event.note = f"sent={counts['sent']} failed={counts['failed']} skipped_recent={counts['skipped_recent']}"
            await db.commit()
        if nothing_went:
            raise ManualRemindBlocked(409, "Reminders are not switched on")
    return {
        "dry_run": dry_run, "enabled": cfg.reminders_enabled(), "test_mode": cfg.status_snapshot()["test_mode"],
        "candidates": len(people), **{k: v for k, v in counts.items() if k != "disabled_reason"},
    }
