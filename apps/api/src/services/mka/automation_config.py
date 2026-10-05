"""MKA fork: configuration for the compliance automation (spec 2026-10-05 section 1).

Every value is read from the environment at CALL time (never import time) so tests and operators can flip a
switch without a restart of the import graph, and so a stale module-level copy can never keep a kill switch "on".

Fail-safe rules:
* all flags default to OFF; the per-feature flags only count while the master switch is on;
* a malformed number / schedule falls back to the safe default and logs a warning (never the raw secret);
* a malformed ``MKA_AUTOMATION_TEST_RECIPIENT`` is NOT treated as "unset" (that would silently turn test mode
  into real sends): :func:`test_recipient` raises :class:`InvalidTestRecipient` and the sender refuses to send.
"""

from __future__ import annotations

import logging
import math
import os
import re
from dataclasses import dataclass
from datetime import date, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

_TRUE = {"1", "true", "yes", "on"}

# One address: no whitespace, no list separators, no angle brackets/quotes, so no header injection either.
_ADDRESS_RE = re.compile(r"^[^@\s,;<>\"'\\]+@[^@\s,;<>\"'\\]+\.[^@\s,;<>\"'\\]+$")

KIND_FEATURE = {"receipt": "receipts", "allset": "receipts", "reminder": "reminders", "digest": "reminders"}
FEATURES = ("autoenroll", "receipts", "reminders")
_FEATURE_ENV = {
    "autoenroll": "MKA_AUTOENROLL_ENABLED",
    "receipts": "MKA_RECEIPTS_ENABLED",
    "reminders": "MKA_REMINDERS_ENABLED",
}


class InvalidTestRecipient(ValueError):
    """``MKA_AUTOMATION_TEST_RECIPIENT`` is set but is not a single plain address."""


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def _flag(name: str) -> bool:
    return _env(name).lower() in _TRUE


def automation_enabled() -> bool:
    """The master kill switch (default off)."""
    return _flag("MKA_AUTOMATION_ENABLED")


def feature_enabled(feature: str) -> bool:
    """A feature is on only when the master switch AND its own flag are on. Unknown feature: off."""
    env = _FEATURE_ENV.get(feature)
    return bool(env) and automation_enabled() and _flag(env)  # type: ignore[arg-type]


def autoenroll_enabled() -> bool:
    return feature_enabled("autoenroll")


def receipts_enabled() -> bool:
    return feature_enabled("receipts")


def reminders_enabled() -> bool:
    return feature_enabled("reminders")


def feature_for_kind(kind: str) -> Optional[str]:
    """Which feature flag governs a send-log ``kind`` (None for an unknown kind: never sendable)."""
    return KIND_FEATURE.get(kind)


def valid_address(value: str) -> bool:
    return bool(_ADDRESS_RE.match(value))


def test_recipient() -> Optional[str]:
    """The lower-cased test-redirect address, ``None`` when unset/empty. Raises when set but malformed."""
    raw = os.environ.get("MKA_AUTOMATION_TEST_RECIPIENT")
    if raw is None or raw == "":
        return None
    value = raw.strip().lower()
    if not valid_address(value):
        raise InvalidTestRecipient("MKA_AUTOMATION_TEST_RECIPIENT is not a single valid address")
    return value


test_recipient.__test__ = False  # type: ignore[attr-defined]  # not a pytest test despite the name


def webhook_secret() -> str:
    return _env("MKA_AUTOMATION_WEBHOOK_SECRET")


def cron_secret() -> str:
    return _env("MKA_AUTOMATION_CRON_SECRET")


def contact_email() -> str:
    """Who recipients are told to contact; '' when unset or malformed (never interpolate an unchecked value)."""
    value = _env("MKA_AUTOMATION_CONTACT_EMAIL")
    if value and not valid_address(value):
        logger.warning("MKA_AUTOMATION_CONTACT_EMAIL is not a single valid address; ignoring it")
        return ""
    return value


# ---------------------------------------------------------------------------------------------------------
# numbers
# ---------------------------------------------------------------------------------------------------------


def _int(name: str, default: int, minimum: int) -> int:
    raw = _env(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("%s is not an integer; using the default %s", name, default)
        return default
    if value < minimum:
        logger.warning("%s must be >= %s; using the default %s", name, minimum, default)
        return default
    return value


def _float(name: str, default: float, minimum: float, maximum: float) -> float:
    raw = _env(name)
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        logger.warning("%s is not a number; using the default %s", name, default)
        return default
    if not math.isfinite(value) or value < minimum or value > maximum:
        logger.warning("%s must be between %s and %s; using the default %s", name, minimum, maximum, default)
        return default
    return value


def run_send_cap() -> int:
    """Max sends per run (default 400; 0 is a legitimate hard stop)."""
    return _int("MKA_AUTOMATION_RUN_SEND_CAP", 400, 0)


def send_delay_seconds() -> float:
    """Pause between consecutive sends in one run (default 0.25 s, max 30 s)."""
    return _float("MKA_AUTOMATION_SEND_DELAY_SECONDS", 0.25, 0.0, 30.0)


def max_consecutive_failures() -> int:
    """Hard-stop a run after this many consecutive send failures (default 5, minimum 1)."""
    return _int("MKA_AUTOMATION_MAX_CONSECUTIVE_FAILURES", 5, 1)


def weekly_reminder_cap() -> int:
    """Max reminders per person per ISO week (default 1, minimum 1)."""
    return _int("MKA_AUTOMATION_WEEKLY_REMINDER_CAP", 1, 1)


def run_time_budget_seconds() -> float:
    """Wall-clock budget of one reminder run (default 90 s). The run stops sending once it is spent, so the HTTP
    call returns well inside the caller's timeout; the caller simply calls again for the rest."""
    return _float("MKA_AUTOMATION_RUN_TIME_BUDGET_SECONDS", 90.0, 0.0, 3600.0)


def reminder_window_days() -> int:
    """How many days (the scheduled date included) a reminder date stays open for catching up (default 4)."""
    return min(_int("MKA_REMINDER_WINDOW_DAYS", 4, 1), 7)


def reminder_max_address_failures() -> int:
    """An address with this many failed reminder sends in the last 7 days is quarantined (not selected) until the
    failures age out (default 3)."""
    return _int("MKA_REMINDER_MAX_ADDRESS_FAILURES", 3, 1)


def claim_lease_seconds() -> int:
    """A ``queued`` send-log claim older than this is presumed crashed and may be re-claimed once (default 900)."""
    return _int("MKA_AUTOMATION_CLAIM_LEASE_SECONDS", 900, 1)


def cycle_tz() -> ZoneInfo | timezone:
    """The cycle timezone: ``MKA_COMPLIANCE_TZ`` (default America/New_York), UTC when the name is unknown."""
    name = _env("MKA_COMPLIANCE_TZ") or "America/New_York"
    try:
        return ZoneInfo(name)
    except Exception:  # unknown zone name: same fallback as compliance.today()
        return ZoneInfo("UTC")


# ---------------------------------------------------------------------------------------------------------
# reminder schedule
# ---------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ReminderSchedule:
    """``days``: recurring (month, day); ``dates``: one-off full dates; ``weekly_after_deadline``: every 7 days
    after the cycle deadline (deadline + 7, +14, ...) while overdue."""

    days: tuple = ()
    dates: tuple = ()
    weekly_after_deadline: bool = False


DEFAULT_SCHEDULE_TEXT = "11-08,11-15,11-22,11-28,weekly"
DEFAULT_SCHEDULE = ReminderSchedule(days=((11, 8), (11, 15), (11, 22), (11, 28)), weekly_after_deadline=True)

_MMDD = re.compile(r"^(\d{2})-(\d{2})$")
_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_schedule(text: str) -> ReminderSchedule:
    """``MM-DD`` (every year) / ``YYYY-MM-DD`` (that day only) / ``weekly`` tokens, comma separated.

    Raises ValueError on anything else (empty tokens, impossible dates, unknown words)."""
    days: set = set()
    dates: set = set()
    weekly = False
    tokens = [t.strip() for t in text.split(",")]
    if not tokens or any(not t for t in tokens):
        raise ValueError("empty schedule token")
    for token in tokens:
        if token.lower() == "weekly":
            weekly = True
        elif m := _MMDD.match(token):
            month, day = int(m.group(1)), int(m.group(2))
            date(2000, month, day)  # 2000 is a leap year: 02-29 allowed as a recurring day
            days.add((month, day))
        elif m := _ISO.match(token):
            dates.add(date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
        else:
            raise ValueError("unrecognised schedule token")
    return ReminderSchedule(days=tuple(sorted(days)), dates=tuple(sorted(dates)), weekly_after_deadline=weekly)


def reminder_schedule() -> ReminderSchedule:
    raw = os.environ.get("MKA_REMINDER_SCHEDULE")
    if raw is None or not raw.strip():
        return DEFAULT_SCHEDULE
    try:
        return parse_schedule(raw)
    except ValueError:
        logger.warning("MKA_REMINDER_SCHEDULE is invalid; using the default schedule (%s)", DEFAULT_SCHEDULE_TEXT)
        return DEFAULT_SCHEDULE


def is_reminder_day(today: date, deadline: Optional[date], schedule: ReminderSchedule) -> bool:
    if (today.month, today.day) in schedule.days or today in schedule.dates:
        return True
    if schedule.weekly_after_deadline and deadline is not None:
        overdue_days = (today - deadline).days
        return overdue_days > 0 and overdue_days % 7 == 0
    return False


def reminder_window_start(
    today: date, deadline: Optional[date], schedule: ReminderSchedule, window_days: int
) -> Optional[date]:
    """The scheduled reminder date that has ``today`` inside its window (the window is the date itself plus the
    following ``window_days - 1`` days), the latest one when several qualify; ``None`` outside every window."""
    for back in range(max(window_days, 1)):
        day = today - timedelta(days=back)
        if is_reminder_day(day, deadline, schedule):
            return day
    return None


# ---------------------------------------------------------------------------------------------------------
# status (no secrets, no full addresses)
# ---------------------------------------------------------------------------------------------------------


def _mask(address: str) -> str:
    local, _, domain = address.partition("@")
    return f"{local[:1]}***@{domain}"


def status_snapshot() -> dict:
    invalid = False
    masked: Optional[str] = None
    try:
        recipient = test_recipient()
        masked = _mask(recipient) if recipient else None
        test_mode = recipient is not None
    except InvalidTestRecipient:
        invalid, test_mode = True, True  # misconfigured: sends are refused, which is test-mode-safe
    return {
        "enabled": automation_enabled(),
        "features": {f: feature_enabled(f) for f in FEATURES},
        "test_mode": test_mode,
        "test_recipient_masked": masked,
        "test_recipient_invalid": invalid,
        "webhook_secret_configured": bool(webhook_secret()),
        "cron_secret_configured": bool(cron_secret()),
        "run_send_cap": run_send_cap(),
        "run_time_budget_seconds": run_time_budget_seconds(),
        "reminder_window_days": reminder_window_days(),
        "claim_lease_seconds": claim_lease_seconds(),
        "reminder_max_address_failures": reminder_max_address_failures(),
        "weekly_reminder_cap": weekly_reminder_cap(),
    }
