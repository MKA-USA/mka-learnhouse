"""MKA fork: the ONLY code path that sends compliance-automation email (spec 2026-10-05 sections 1 + 5).

Nothing else in the codebase may call ``send_email`` for automation mail; seams A/B/C call
:func:`send_automation_email`. Guarantees (each has a test in ``tests/services/mka/test_automation_send.py``):

1. **Kill switch.** A real send needs the master switch AND the per-kind feature flag. Otherwise ``disabled``:
   no log row, no transport.
2. **Test-mode redirect.** When ``MKA_AUTOMATION_TEST_RECIPIENT`` is set the recipient is replaced, the subject is
   prefixed ``[TEST -> <intended>]`` and ``test_mode`` is recorded. No caller header survives test mode (no
   Reply-To/Cc/Bcc/List-*), so no other address can be contacted. A set-but-malformed test recipient REFUSES the
   send (it must never degrade into "no test mode"). Test sends live in their own dedupe namespace (``test:``
   prefix) so a review run can never mark a real send as "already handled".
3. **Dry run** (the default). Returns what WOULD be sent. It touches neither the send log nor the transport and
   does not consult the kill switch (it has no side effects). Seams decide whether a dry run is meaningful.
4. **Claim before send.** A ``queued`` row (UNIQUE(org_id, kind, dedupe_key)) is inserted and COMMITTED before the
   transport is called. A conflict returns ``already_handled`` without sending. A previously ``failed`` row is
   re-claimed atomically (UPDATE ... WHERE status='failed'), so a later run retries failures but never
   duplicates a ``queued``/``sent`` one. A crash between claim and send leaves ``queued``; such a claim older than
   ``MKA_AUTOMATION_CLAIM_LEASE_SECONDS`` (default 900) is taken over atomically and re-sent ONCE (a fresh ``queued``
   row stays 'already handled').
   NOTE: this function COMMITS the caller's session (the claim must be durable before the email leaves).
5. **Reminder cap.** a SCHEDULED reminder (``reminder:`` key; manual ``manual:`` keys are their own allowance, one per
   person per course per week) is refused (``capped``) when the person already has
   ``MKA_AUTOMATION_WEEKLY_REMINDER_CAP`` real reminders in the ISO week. Build the reminder dedupe key with
   :func:`reminder_dedupe_key` so the unique constraint also makes the cap atomic under concurrency.
6. **Budget.** An optional :class:`SendBudget` enforces the per-run cap, a wall-clock budget
   (``MKA_AUTOMATION_RUN_TIME_BUDGET_SECONDS``), an inter-send delay and a hard stop after N consecutive failures; it is checked BEFORE claiming so an exhausted run leaves no ``queued`` rows.
7. **No PII in logs** (ids/status only); caller HTML is sent as given (templates escape), the test banner escapes.
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Awaitable, Callable, Optional

from sqlalchemy import func, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.mka_automation import SEND_KINDS, MkaAutomationSendLog, utcnow
from src.services.email import utils as email_utils
from src.services.mka import automation_config as cfg

logger = logging.getLogger(__name__)

TEST_KEY_PREFIX = "test:"
MAX_KEY_LEN = 255
MAX_SUBJECT_LEN = 300
# Addresses that must never be mailed (anonymised accounts); the upstream demo domain is checked via is_demo_email.
SUPPRESSED_DOMAINS = ("anonymized.example.com", "anonymized.invalid")

_CTRL = re.compile(r"[\x00-\x1f\x7f]")
_ISO_WEEK = re.compile(r"^(\d{4})-W(\d{2})$")
# Headers a caller may pass in a REAL send. Everything address-bearing except Reply-To is refused outright.
_ALLOWED_HEADER_PREFIXES = ("x-mka-",)
_FORBIDDEN_HEADERS = {
    "to", "cc", "bcc", "from", "sender", "return-path", "delivered-to", "envelope-to", "x-original-to",
    "disposition-notification-to", "return-receipt-to", "errors-to", "list-unsubscribe", "list-unsubscribe-post",
}


@dataclass
class SendResult:
    """``status``: sent | failed | already_handled | disabled | dry_run | suppressed | budget_exhausted | capped."""

    status: str
    intended: str
    to: Optional[str] = None
    subject: Optional[str] = None
    test_mode: bool = False
    log_id: Optional[int] = None
    error: Optional[str] = None
    reason: Optional[str] = None

    @property
    def sent(self) -> bool:
        return self.status == "sent"


class SendBudget:
    """Per-run guard: send cap, a wall-clock budget, pause between sends, stop after N consecutive failures.

    ``SendBudget()`` takes its limits from the environment at construction time; pass explicit values to
    override. ``sleep`` and ``clock`` (monotonic seconds) are injectable for tests. The clock starts at construction
    and the budget is checked BEFORE each send (with the pause that precedes it counted), so a run never starts a
    send it has no time for."""

    def __init__(
        self,
        max_sends: Optional[int] = None,
        delay_seconds: Optional[float] = None,
        max_consecutive_failures: Optional[int] = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        time_budget_seconds: Optional[float] = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_sends = cfg.run_send_cap() if max_sends is None else max_sends
        self.delay_seconds = cfg.send_delay_seconds() if delay_seconds is None else delay_seconds
        self.max_consecutive_failures = (
            cfg.max_consecutive_failures() if max_consecutive_failures is None else max_consecutive_failures
        )
        self.time_budget_seconds = cfg.run_time_budget_seconds() if time_budget_seconds is None else time_budget_seconds
        self._sleep = sleep
        self._clock = clock
        self._started = clock()
        self.attempts = 0
        self.sent = 0
        self.failed = 0
        self.consecutive_failures = 0

    @property
    def stop_reason(self) -> Optional[str]:
        if self.consecutive_failures >= self.max_consecutive_failures:
            return "too_many_consecutive_failures"
        if self.attempts >= self.max_sends:
            return "send_cap_reached"
        if self._clock() - self._started + (self.delay_seconds if self.attempts else 0.0) >= self.time_budget_seconds:
            return "time_budget_reached"
        return None

    def can_send(self) -> bool:
        return self.stop_reason is None

    async def pace(self) -> None:
        """Called before every real attempt; sleeps between attempts (never before the first)."""
        if self.attempts > 0 and self.delay_seconds > 0:
            await self._sleep(self.delay_seconds)

    def record(self, success: bool) -> None:
        self.attempts += 1
        if success:
            self.sent += 1
            self.consecutive_failures = 0
        else:
            self.failed += 1
            self.consecutive_failures += 1

    def summary(self) -> dict:
        return {"attempts": self.attempts, "sent": self.sent, "failed": self.failed, "stopped": self.stop_reason}


# ---------------------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------------------


def iso_week_label(day: date) -> str:
    iso = day.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def current_iso_week(now: Optional[datetime] = None) -> str:
    """The ISO week label of ``now`` (default: current instant) in the cycle timezone."""
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return iso_week_label(moment.astimezone(cfg.cycle_tz()).date())


def reminder_dedupe_key(email: str, iso_week: str) -> str:
    """The canonical reminder key: one per person per ISO week (so the unique constraint enforces the cap)."""
    return f"reminder:{iso_week}:{email.strip().lower()}"


def manual_dedupe_key(course_id: int, iso_week: str, email: str) -> str:
    """Manual "Remind" button key: its own key space (review M3), one per person per course per ISO week. It never
    takes the scheduled ``reminder:`` dedupe key, but it DOES count toward the weekly per-person cap (round 5)."""
    return f"manual:{int(course_id)}:{iso_week}:{email.strip().lower()}"


SCHEDULED_KEY_PREFIX = "reminder:"


def week_window_utc(iso_week: str) -> tuple[datetime, datetime]:
    m = _ISO_WEEK.match(iso_week or "")
    if not m:
        raise ValueError("iso_week must look like 2026-W45")
    monday = date.fromisocalendar(int(m.group(1)), int(m.group(2)), 1)
    tz = cfg.cycle_tz()
    start = datetime(monday.year, monday.month, monday.day, tzinfo=tz)
    end = datetime.combine(monday + timedelta(days=7), datetime.min.time(), tzinfo=tz)
    return (
        start.astimezone(timezone.utc).replace(tzinfo=None),
        end.astimezone(timezone.utc).replace(tzinfo=None),
    )


async def reminders_this_week(db: AsyncSession, org_id: int, email: str, iso_week: str) -> int:
    """Real (non-test) reminders of ANY kind (scheduled ``reminder:`` and manual-button ``manual:`` keys) queued/sent to
    ``email`` in the ISO week. Org-scoped. Spec 1.5/2C: the weekly cap is one reminder per person, manual included."""
    start, end = week_window_utc(iso_week)
    stmt = select(func.count()).select_from(MkaAutomationSendLog).where(
        MkaAutomationSendLog.org_id == org_id,
        MkaAutomationSendLog.kind == "reminder",
        MkaAutomationSendLog.intended_email == email.strip().lower(),
        MkaAutomationSendLog.test_mode == False,  # noqa: E712
        MkaAutomationSendLog.status.in_(("queued", "sent")),  # type: ignore[attr-defined]
        MkaAutomationSendLog.created_at >= start,
        MkaAutomationSendLog.created_at < end,
    )
    return int((await db.execute(stmt)).scalar_one())


async def reminded_this_week(db: AsyncSession, org_id: int, email: str, iso_week: str) -> bool:
    """True when the person has already used up this week's reminder allowance."""
    return await reminders_this_week(db, org_id, email, iso_week) >= cfg.weekly_reminder_cap()


FAILURE_WINDOW = timedelta(days=7)
_FAILS = re.compile(r"\[fails=(\d+)\]")


def _fail_count(error: Optional[str]) -> int:
    """Failed attempts recorded on a send-log row (``error`` ends in ``[fails=N]``; a bare error counts as one)."""
    if not error:
        return 0
    m = _FAILS.search(error)
    return int(m.group(1)) if m else 1


async def _previous_failures(db: AsyncSession, org_id: int, kind: str, key: str) -> int:
    error = (
        await db.execute(
            select(MkaAutomationSendLog.error).where(
                MkaAutomationSendLog.org_id == org_id, MkaAutomationSendLog.kind == kind,
                MkaAutomationSendLog.dedupe_key == key, MkaAutomationSendLog.status == "failed",
            )
        )
    ).scalars().first()
    return _fail_count(error)


async def failing_addresses(db: AsyncSession, org_id: int, *, test_mode: bool, now: datetime) -> dict:
    """``{intended_email: failed attempts in the last 7 days}`` for reminder sends (scheduled and manual) in the
    current mode. Used to quarantine addresses that keep being rejected and to order the others first (review N1)."""
    since = (now.astimezone(timezone.utc).replace(tzinfo=None) if now.tzinfo else now) - FAILURE_WINDOW
    stmt = select(MkaAutomationSendLog.intended_email, MkaAutomationSendLog.error).where(
        MkaAutomationSendLog.org_id == org_id, MkaAutomationSendLog.kind == "reminder",
        MkaAutomationSendLog.status == "failed", MkaAutomationSendLog.test_mode == test_mode,
        MkaAutomationSendLog.created_at >= since,
    )
    out: dict = {}
    for email, error in (await db.execute(stmt)).all():
        out[email] = out.get(email, 0) + _fail_count(error)
    return out


def current_mode_is_test() -> bool:
    """True when a send right now would go to the test recipient (a malformed test address counts: it refuses sends)."""
    try:
        return cfg.test_recipient() is not None
    except cfg.InvalidTestRecipient:
        return True


async def reminder_rows_by_person(
    db: AsyncSession, org_id: int, *, key_like: str, test_mode: bool, since: Optional[datetime] = None
) -> dict:
    """``{intended_email: latest created_at}`` of reminder log rows in the CURRENT mode (real or test) whose dedupe
    key matches ``key_like`` (a SQL LIKE pattern WITHOUT the ``test:`` prefix) and which are ``queued``/``sent``/
    ``suppressed`` (``failed`` rows are retried, so they are not 'done'). One query for the whole roster, used to
    pick who still needs a reminder BEFORE any per-run cap is applied."""
    stmt = (
        select(MkaAutomationSendLog.intended_email, func.max(MkaAutomationSendLog.created_at))
        .where(
            MkaAutomationSendLog.org_id == org_id,
            MkaAutomationSendLog.kind == "reminder",
            MkaAutomationSendLog.test_mode == test_mode,
            MkaAutomationSendLog.dedupe_key.like(f"{TEST_KEY_PREFIX if test_mode else ''}{key_like}"),  # type: ignore[attr-defined]
            MkaAutomationSendLog.status.in_(("queued", "sent", "suppressed")),  # type: ignore[attr-defined]
        )
        .group_by(MkaAutomationSendLog.intended_email)
    )
    if since is not None:
        stmt = stmt.where(MkaAutomationSendLog.created_at >= since)
    return {email: last for email, last in (await db.execute(stmt)).all()}


async def has_real_send(db: AsyncSession, org_id: int, kind: str, dedupe_key: str) -> bool:
    """A non-test log row exists for the key (queued/sent). Test-mode rows never count as 'done'."""
    stmt = select(MkaAutomationSendLog.id).where(
        MkaAutomationSendLog.org_id == org_id,
        MkaAutomationSendLog.kind == kind,
        MkaAutomationSendLog.dedupe_key == dedupe_key,
        MkaAutomationSendLog.test_mode == False,  # noqa: E712
        MkaAutomationSendLog.status.in_(("queued", "sent")),  # type: ignore[attr-defined]
    )
    return (await db.execute(stmt)).first() is not None


def _clean_subject(subject: str) -> str:
    return _CTRL.sub(" ", subject).strip()[:MAX_SUBJECT_LEN]


def _is_suppressed(address: str) -> bool:
    from src.services.demo.flags import is_demo_email

    return is_demo_email(address) or address.rsplit("@", 1)[-1] in SUPPRESSED_DOMAINS


def _safe_headers(headers: Optional[dict], test_mode: bool, contact: str) -> dict:
    """Validate caller headers; in test mode return none at all (so no address can be contacted)."""
    out: dict = {}
    for name, value in (headers or {}).items():
        key = str(name).strip().lower()
        text = str(value)
        if _CTRL.search(str(name)) or _CTRL.search(text):
            raise ValueError("header contains control characters")
        if key in _FORBIDDEN_HEADERS or key.startswith("resent-"):
            raise ValueError(f"header {name!r} is not allowed on automation mail")
        if key == "reply-to":
            if not cfg.valid_address(text.strip()):
                raise ValueError("Reply-To must be a single valid address")
            out["Reply-To"] = text.strip()
        elif key.startswith(_ALLOWED_HEADER_PREFIXES):
            out[str(name).strip()] = text
        else:
            raise ValueError(f"header {name!r} is not allowed on automation mail")
    if test_mode:
        return {}
    if "Reply-To" not in out and contact:
        out["Reply-To"] = contact
    return out


def _test_banner(intended: str) -> str:
    return (
        '<div style="border:1px solid #c0392b;padding:8px;margin-bottom:12px;font:13px sans-serif">'
        f"TEST MODE: this message would have gone to {html.escape(intended)}.</div>"
    )


STALE_CLAIM_MARK = "reclaimed_stale_queued"


def stale_claim_cutoff(now: datetime) -> datetime:
    """``queued`` rows created before this are presumed crashed (``MKA_AUTOMATION_CLAIM_LEASE_SECONDS``)."""
    return now - timedelta(seconds=cfg.claim_lease_seconds())


def stale_queued_condition(cutoff: datetime):
    """SQL condition: a ``queued`` claim past its lease that has not been re-claimed before (at most one retry)."""
    return (
        (MkaAutomationSendLog.status == "queued")
        & (MkaAutomationSendLog.created_at < cutoff)
        & (MkaAutomationSendLog.error.is_(None))  # type: ignore[union-attr]
    )


async def _claim(db: AsyncSession, row: MkaAutomationSendLog) -> Optional[MkaAutomationSendLog]:
    """Insert the claim, or atomically re-claim a ``failed`` row or a STALE ``queued`` one (review M2). ``None`` =
    someone else owns the key. A stale claim (older than the lease) is the footprint of a crash between claim and send;
    it is taken over once, atomically (``UPDATE ... WHERE status='queued' AND created_at < cutoff``, so of two racing
    runs exactly one wins) and marked so a second crash is not retried forever. A FRESH ``queued`` row is somebody
    else's send in flight: ``already_handled``."""
    try:
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError:
        identity = (
            MkaAutomationSendLog.org_id == row.org_id,
            MkaAutomationSendLog.kind == row.kind,
            MkaAutomationSendLog.dedupe_key == row.dedupe_key,
        )
        fresh_values = dict(
            to_email=row.to_email, intended_email=row.intended_email, subject=row.subject, test_mode=row.test_mode,
            user_id=row.user_id, cycle_id=row.cycle_id, course_id=row.course_id, created_at=row.created_at, sent_at=None,
        )
        reclaim = await db.execute(
            update(MkaAutomationSendLog)
            .where(*identity, MkaAutomationSendLog.status == "failed")
            .values(status=row.status, error=None, **fresh_values)
        )
        if reclaim.rowcount != 1:
            reclaim = await db.execute(
                update(MkaAutomationSendLog)
                .where(*identity, stale_queued_condition(stale_claim_cutoff(row.created_at)))
                .values(status=row.status, error=STALE_CLAIM_MARK, **fresh_values)
            )
        if reclaim.rowcount != 1:  # fresh queued / sent / suppressed: already handled (the savepoint rolled the insert back)
            return None
        existing = (await db.execute(select(MkaAutomationSendLog).where(*identity))).scalars().one()
        await db.commit()
        return existing
    await db.commit()
    return row


async def _finish(db: AsyncSession, log_id: int, **values) -> None:
    await db.execute(update(MkaAutomationSendLog).where(MkaAutomationSendLog.id == log_id).values(**values))
    await db.commit()


# ---------------------------------------------------------------------------------------------------------
# the one send function
# ---------------------------------------------------------------------------------------------------------


async def send_automation_email(
    db: AsyncSession,
    *,
    org_id: int,
    kind: str,
    dedupe_key: str,
    to_email: str,
    subject: str,
    html_body: str,
    user_id: Optional[int] = None,
    cycle_id: Optional[int] = None,
    course_id: Optional[int] = None,
    headers: Optional[dict] = None,
    sender_name: Optional[str] = None,
    dry_run: bool = True,
    budget: Optional[SendBudget] = None,
    now: Optional[datetime] = None,
) -> SendResult:
    """Send (or preview) ONE automation email. See the module docstring for the guarantees.

    ``now`` is the current instant (naive = UTC); tests inject it, production leaves it ``None``.

    ``dry_run`` defaults to True: a real send needs an explicit ``dry_run=False``."""
    if kind not in SEND_KINDS:
        raise ValueError(f"unknown kind {kind!r}")
    key = (dedupe_key or "").strip()
    if not key or len(key) > MAX_KEY_LEN or _CTRL.search(key) or key.startswith(TEST_KEY_PREFIX):
        raise ValueError("invalid dedupe_key")
    intended = (to_email or "").strip().lower()
    if not cfg.valid_address(intended):
        raise ValueError("invalid recipient address")
    clean_subject = _clean_subject(subject)
    if not clean_subject:
        raise ValueError("empty subject")

    try:
        redirect = cfg.test_recipient()
    except cfg.InvalidTestRecipient:
        logger.error("automation send refused: MKA_AUTOMATION_TEST_RECIPIENT is set but invalid (kind=%s)", kind)
        return SendResult("disabled", intended, reason="invalid_test_recipient")
    test_mode = redirect is not None
    effective_to = redirect if test_mode else intended
    effective_subject = _clean_subject(f"[TEST → {intended}] {clean_subject}") if test_mode else clean_subject
    body = (_test_banner(intended) + html_body) if test_mode else html_body
    effective_key = f"{TEST_KEY_PREFIX}{key}" if test_mode else key
    out_headers = _safe_headers(headers, test_mode, cfg.contact_email())

    def result(status: str, **kw) -> SendResult:
        return SendResult(status, intended, to=effective_to, subject=effective_subject, test_mode=test_mode, **kw)

    if dry_run:
        return result("dry_run")

    feature = cfg.feature_for_kind(kind)
    if feature is None or not cfg.feature_enabled(feature):
        return result("disabled", reason="feature_off")

    if budget is not None and not budget.can_send():
        return result("budget_exhausted", reason=budget.stop_reason)

    suppressed = _is_suppressed(intended)
    if kind == "reminder" and key.startswith((SCHEDULED_KEY_PREFIX, "manual:")) and not suppressed and not test_mode:
        week = current_iso_week(now)
        if await reminded_this_week(db, org_id, intended, week):
            return result("capped", reason="weekly_reminder_cap")

    created = utcnow() if now is None else (
        now.astimezone(timezone.utc).replace(tzinfo=None) if now.tzinfo else now
    )
    row = MkaAutomationSendLog(
        org_id=org_id, kind=kind, dedupe_key=effective_key, user_id=user_id, to_email=effective_to,
        intended_email=intended, subject=effective_subject, status="suppressed" if suppressed else "queued",
        test_mode=test_mode, cycle_id=cycle_id, course_id=course_id, created_at=created,
    )
    previous_failures = await _previous_failures(db, org_id, kind, effective_key) if not suppressed else 0
    claimed = await _claim(db, row)
    if claimed is None:
        return result("already_handled")
    log_id = claimed.id
    if suppressed:
        logger.info("automation send suppressed kind=%s org=%s log=%s", kind, org_id, log_id)
        return result("suppressed", log_id=log_id)

    if budget is not None:
        await budget.pace()
    try:
        await asyncio.to_thread(
            email_utils.send_email, effective_to, effective_subject, body, out_headers or None, sender_name
        )
    except Exception as exc:  # transport failure: record it, never leak the message (may contain addresses)
        code = getattr(exc, "status_code", None)
        error = f"{type(exc).__name__}" + (f" {code}" if code else "")
        await _finish(db, log_id, status="failed", error=f"{error[:150]} [fails={previous_failures + 1}]")
        if budget is not None:
            budget.record(False)
        logger.warning("automation send failed kind=%s org=%s log=%s error=%s", kind, org_id, log_id, error)
        return result("failed", log_id=log_id, error=error)

    try:
        await _finish(db, log_id, status="sent", sent_at=utcnow())
    except Exception as exc:  # the mail left; leave the row 'queued' (it is re-sent only after the lease, review M2)
        logger.error("automation send log update failed after delivery log=%s error=%s", log_id, type(exc).__name__)
    if budget is not None:
        budget.record(True)
    logger.info("automation send ok kind=%s org=%s log=%s test=%s", kind, org_id, log_id, test_mode)
    return result("sent", log_id=log_id)
