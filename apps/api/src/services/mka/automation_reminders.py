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

import hashlib
import hmac
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
    SCHEDULED_KEY_PREFIX,
    SendBudget,
    current_iso_week,
    current_mode_is_test,
    failing_addresses,
    iso_week_label,
    manual_dedupe_key,
    reminder_dedupe_key,
    reminder_rows_by_person,
    send_automation_email,
    week_window_utc,
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
        "remaining": 0, "time_budget_hit": False, "quarantined": 0,
        "skipped_cooldown": 0, "newly_quarantined": 0,
    }


def _local_midnight_utc(day: date) -> datetime:
    """Start of ``day`` in the cycle timezone as naive UTC (the send log stores naive UTC)."""
    start = datetime(day.year, day.month, day.day, tzinfo=cfg.cycle_tz())
    return start.astimezone(timezone.utc).replace(tzinfo=None)


@dataclass
class Selection:
    """Who a run would remind, in the order it would remind them (review H2) and under which key week."""

    pending: list  # e-mail addresses, least recently reminded first
    key_week: str  # ISO week label used in the dedupe key (scheduled: the window's first week)
    already: int  # people dropped because they were already reminded in this window / week
    quarantined: int = 0  # people dropped because their address keeps failing (review N1)
    fails: dict = field(default_factory=dict)  # recent failed attempts per address (for 'newly quarantined')
    cooled: int = 0  # people dropped because ANY reminder (scheduled or manual) reached them inside the cooldown (N3)
    last_sent: dict = field(default_factory=dict)


async def select_pending(
    db: AsyncSession, *, org_id: int, people: dict, today: date, now: datetime,
    manual_course_id: Optional[int] = None, window_start: Optional[date] = None,
) -> Selection:
    """People already reminded this window / week are dropped BEFORE any per-run cap or time budget is spent, and the
    rest are ordered least-recently-reminded first (then by address), so every run makes progress through the
    not-yet-reminded remainder instead of re-walking the same alphabetical head. Manual runs use the per-course
    manual key space instead and go by address."""
    week = current_iso_week(now)
    test_mode = current_mode_is_test()
    last_sent: dict = {}
    if manual_course_id is not None:  # one query: who already got THIS course's manual reminder this week
        done = await reminder_rows_by_person(
            db, org_id, key_like=manual_dedupe_key(manual_course_id, week, "%"), test_mode=test_mode
        )
        excluded_people = set(done)
        key_week = week
    else:
        key_week = iso_week_label(window_start) if window_start is not None else week
        cutoff = min(week_window_utc(week)[0], _local_midnight_utc(window_start or today))
        last_sent = await reminder_rows_by_person(db, org_id, key_like=f"{SCHEDULED_KEY_PREFIX}%", test_mode=test_mode)
        excluded_people = {e for e, last in last_sent.items() if last is not None and last >= cutoff}
    # Addresses whose sends keep failing (review N1) are quarantined; the ones with some recent failure go LAST so a few
    # bad mailboxes can never sit at the head of the queue and trip the consecutive-failure stop for everybody else.
    # Cross-kind cooldown (review N3): one reminder email of ANY kind per person per MKA_REMINDER_COOLDOWN_DAYS. A manual
    # remind never spends the scheduled weekly slot (those are the separate checks above) but it does start a cooldown,
    # so the person is not mailed again within days, and the scheduled reminder follows later in the window / week.
    cool_cut = _naive_utc(now) - timedelta(days=cfg.reminder_cooldown_days())
    # Round 3 M1: on the LAST day of a reminder window a scheduled run ignores the cooldown that comes from a MANUAL
    # reminder. The manual mail covers one course; the scheduled mail lists everything outstanding, and there is no
    # later run in this window, so nobody who is still outstanding may fall through. (Cost: that person can get two
    # emails about 3 days apart. The weekly cap, the scheduled-vs-scheduled cooldown and the quarantine still apply.)
    last_window_day = (
        manual_course_id is None and window_start is not None
        and today >= window_start + timedelta(days=cfg.reminder_window_days() - 1)
    )
    any_last = await reminder_rows_by_person(
        db, org_id, key_like=f"{SCHEDULED_KEY_PREFIX}%" if last_window_day else "%", test_mode=test_mode
    )
    cooled = {e for e, last in any_last.items() if last is not None and last > cool_cut} - excluded_people
    fails = await failing_addresses(db, org_id, test_mode=test_mode, now=now)
    limit = cfg.reminder_max_address_failures()
    quarantined = {e for e in people if e not in excluded_people and e not in cooled and fails.get(e, 0) >= limit}
    pending = sorted(
        (e for e in people if e not in excluded_people and e not in cooled and e not in quarantined),
        key=lambda e: (fails.get(e, 0) > 0, last_sent.get(e) or datetime.min, e),
    )
    already = sum(1 for e in people if e in excluded_people)
    return Selection(
        pending, key_week, already, len(quarantined), fails, sum(1 for e in people if e in cooled), last_sent
    )


async def _send_reminders(
    db: AsyncSession, *, org_id: int, cycle: MkaComplianceCycle, people: dict, url: str, today: date,
    dry_run: bool, budget: SendBudget, now: datetime, counts: dict, manual_course_id: Optional[int] = None,
    window_start: Optional[date] = None, selection: Optional[Selection] = None,
) -> dict:
    """Send (or preview) the reminders for ``people`` (see :func:`select_pending` for who and in which order).

    When the budget stops the run ``remaining`` says how many are left and ``time_budget_hit`` whether it was the
    clock. ``window_start`` (scheduled runs) is the scheduled date whose reminder window we are in: its ISO week is the
    dedupe-key week, so a window that straddles two ISO weeks still reminds each person once. ``manual_course_id``
    (the Remind button) switches to the per-course manual key space. ``selection`` lets the caller pass the exact
    list it already showed / verified: nobody outside it is ever mailed."""
    sel = selection or await select_pending(
        db, org_id=org_id, people=people, today=today, now=now, manual_course_id=manual_course_id,
        window_start=window_start,
    )
    week = current_iso_week(now)
    pending = sel.pending
    counts["skipped_recent"] += sel.already + sel.cooled
    counts["skipped_cooldown"] += sel.cooled
    counts["quarantined"] += sel.quarantined
    for index, email in enumerate(pending):
        p = people[email]
        dedupe_key = (
            reminder_dedupe_key(email, sel.key_week) if manual_course_id is None
            else manual_dedupe_key(manual_course_id, week, email)
        )
        mail = tpl.render_reminder(
            addressee=addressee_for(p), cycle_label=cycle.label, outstanding=p.items, deadline=cycle.deadline_on,
            today=today, url=url, contact_email=cfg.contact_email(),
        )
        result = await send_automation_email(
            db, org_id=org_id, kind="reminder", dedupe_key=dedupe_key, to_email=email,
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
            before = sel.fails.get(email, 0)
            if status == "failed" and before < cfg.reminder_max_address_failures() <= before + 1:
                counts["newly_quarantined"] += 1  # this very attempt pushed the address over the limit
        elif status == "budget_exhausted":
            counts["stopped"] = result.reason
            counts["remaining"] += len(pending) - index
            counts["time_budget_hit"] = counts["time_budget_hit"] or result.reason == "time_budget_reached"
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


def digest_view(
    target: DigestTarget, roster: list, per_course: list, user_map: dict, excluded: frozenset,
    failing: frozenset = frozenset(),
):
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
        label = tpl.addressee(role_title=p.role_title, majlis=p.place) or "Unnamed role"
        # reminders to this mailbox keep failing: the supervisor has to reach the person another way (review N1)
        nudge.append(f"{label} (address failing)" if email in failing else label)
    return counts, sorted(nudge)


async def _send_digests(
    db: AsyncSession, *, org: Organization, cycle: MkaComplianceCycle, ds, per_course: list, url: str,
    dry_run: bool, budget: SendBudget, now: datetime, excluded: frozenset,
) -> dict:
    counts = {"would_send": 0, "sent": 0, "skipped_recent": 0, "skipped_nothing_outstanding": 0, "failed": 0,
              "suppressed": 0, "disabled": 0, "stopped": None, "disabled_reason": None, "remaining": 0,
              "time_budget_hit": False}
    targets = digest_targets(ds.roster, excluded)
    fails = await failing_addresses(db, org.id, test_mode=current_mode_is_test(), now=now)  # type: ignore[arg-type]
    failing = frozenset(e for e, n in fails.items() if n >= cfg.reminder_max_address_failures())
    week = current_iso_week(now)
    for index, target in enumerate(targets):
        view, nudge = digest_view(target, ds.roster, per_course, ds.user_map, excluded, failing)
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
            counts["remaining"] += len(targets) - index
            counts["time_budget_hit"] = counts["time_budget_hit"] or result.reason == "time_budget_reached"
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
    # a scheduled date opens a reminder WINDOW (MKA_REMINDER_WINDOW_DAYS): a run on any day inside it continues with
    # the people not yet reminded; outside every window the run does nothing
    window_start = cfg.reminder_window_start(today, cycle.deadline_on, cfg.reminder_schedule(), cfg.reminder_window_days())
    reminder_day = window_start is not None
    digest_day = today.weekday() == 0
    want_reminder = kind in ("reminder", "all")
    want_digest = kind in ("digest", "all")
    if want_reminder and not reminder_day:
        out["reminder"] = {"ran": False, "reason": "not_a_reminder_day"}
        want_reminder = False
    elif want_reminder and window_start is not None and window_start > cycle.deadline_on + timedelta(
        weeks=cfg.reminder_overdue_weeks()
    ):
        # Round 2 L2: overdue reminders stop N weeks after the deadline; from then on the person only shows up in the
        # Monday digest to the Mohtamim / regional Qaid (counts and list), which keeps going.
        out["reminder"] = {"ran": False, "reason": "overdue_period_over"}
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
            now=now, counts=counts, window_start=window_start,
        )
        out["reminder"] = {
            "ran": True, "window_start": window_start.isoformat() if window_start else None,
            "last_window_day": bool(
                window_start and today >= window_start + timedelta(days=cfg.reminder_window_days() - 1)
            ),
            "candidates": len(people), **counts,
        }
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
    totals = {"sent": 0, "would_send": 0, "skipped_recent": 0, "failed": 0, "remaining": 0, "quarantined": 0,
              "newly_quarantined": 0, "disabled": 0}
    disabled_reason = None
    last_window_day = False
    time_budget_hit = False
    reasons: set = set()
    for report in reports:
        for part in ("reminder", "digest"):
            block = report.get(part) or {}
            if block.get("stopped"):
                reasons.add(block["stopped"])
            for key in totals:
                totals[key] += int(block.get(key) or 0)
            time_budget_hit = time_budget_hit or bool(block.get("time_budget_hit"))
            disabled_reason = disabled_reason or block.get("disabled_reason")
            last_window_day = last_window_day or bool(block.get("last_window_day"))
    return {
        "dry_run": dry_run, "kind": kind, "test_mode": cfg.status_snapshot()["test_mode"], **totals,
        "time_budget_hit": time_budget_hit, "disabled_reason": disabled_reason, "last_window_day": last_window_day,
        # WHY the run stopped early, for the caller (the workflow words its summary from this; a failure stop is not a cap)
        "stopped": next((r for r in ("too_many_consecutive_failures", "time_budget_reached", "send_cap_reached") if r in reasons), None),
        "orgs": reports,
    }


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


def preview_digest(*, org_id: int, cycle_id: int, course_uuid: str, day: date, test_mode: bool, recipients: list) -> str:
    """Stable fingerprint of WHO a manual remind would mail (review M4): the sorted recipient addresses plus org, cycle,
    course, day and mode, keyed with the server secret so the browser cannot forge one or test guesses against it.
    The real send recomputes it and refuses when it differs, so it never reaches anyone the dialog did not show."""
    from src.security.security import SECRET_KEY  # lazy: the security module reads the configuration at import

    material = "\n".join(
        [f"org:{org_id}", f"cycle:{cycle_id}", f"course:{course_uuid}", f"day:{day.isoformat()}", f"test:{int(test_mode)}"]
        + sorted(recipients)
    )
    return hmac.new(str(SECRET_KEY).encode(), material.encode(), hashlib.sha256).hexdigest()[:40]


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
    expected_digest: Optional[str] = None,
) -> dict:
    """Remind everyone still outstanding on ONE course. The caller has already resolved scope (404 otherwise)."""
    moment = now or current_instant()
    naive_now = _naive_utc(moment)
    # Review H1: a manual remind only ever acts on the CURRENT, already-started cycle, resolved HERE with the same
    # default-cycle rule as the cron run. The cycle the client asked for is only checked against it, never trusted.
    today = cycle_today(moment)
    current = await _org_cycle(db, org.id, today)  # type: ignore[arg-type]
    if cycle.starts_on > today:
        raise ManualRemindBlocked(409, "Reminders only apply to the current cycle, and this one has not started yet")
    if current is None or current.id != cycle.id:
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
    # Review M4: the list is decided ONCE, here. The digest of that list is what a preview returns and what a real send
    # must present; the send then goes to exactly this list and to nobody else.
    selection = await select_pending(
        db, org_id=org.id, people=people, today=today, now=moment, manual_course_id=link.course_id  # type: ignore[arg-type]
    )
    digest = preview_digest(
        org_id=org.id, cycle_id=cycle.id, course_uuid=link.course_uuid, day=today,  # type: ignore[arg-type]
        test_mode=current_mode_is_test(), recipients=selection.pending,
    )
    if not dry_run:
        if not expected_digest:
            raise ManualRemindBlocked(422, "Preview the list first: a real send needs the preview_digest it returned")
        if not hmac.compare_digest(expected_digest, digest):
            raise ManualRemindBlocked(409, "The list of recipients changed since the preview. Please review it again.")

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
        budget=SendBudget(), now=moment, counts=counts, manual_course_id=link.course_id, selection=selection,
    )
    if event_id is not None:
        event = await db.get(MkaAutomationEvent, event_id)
        nothing_went = counts["sent"] + counts["failed"] + counts["suppressed"] == 0 and counts["disabled"] > 0
        partial = counts["remaining"] > 0  # the budget stopped the run: do not hold the 24 h slot, run it again
        if event is not None:
            event.status = "ignored" if (nothing_went or partial) else "processed"
            event.note = (
                f"sent={counts['sent']} failed={counts['failed']} skipped_recent={counts['skipped_recent']}"
                + (f" partial remaining={counts['remaining']}" if partial else "")
            )
            await db.commit()
        if nothing_went:
            raise ManualRemindBlocked(409, "Reminders are not switched on")
    return {
        "dry_run": dry_run, "enabled": cfg.reminders_enabled(), "test_mode": cfg.status_snapshot()["test_mode"],
        "candidates": len(people), **{k: v for k, v in counts.items() if k != "disabled_reason"},
        "preview_digest": digest if dry_run else None, "cooldown_days": cfg.reminder_cooldown_days(),
    }
