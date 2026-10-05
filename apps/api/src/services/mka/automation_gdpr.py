"""MKA fork: GDPR export / scrub / retention for the compliance-automation data (spec 2026-10-05 section 4).

Called from the fork's own ``services/users/mka_profile.py`` hooks (``profile_status(include_attributes=True)`` for
the export, ``delete_profile`` for the anonymise), so no further upstream edit is needed.

What is covered, for a user ``U`` with email set ``E`` (see :func:`known_emails`):

* ``mka_automation_event``    rows with ``user_id == U`` (or ``user_uuid`` of U);
* ``mka_automation_send_log`` rows with ``user_id == U``, plus rows keyed only by email whose ``intended_email``
                              (export) / ``intended_email`` or ``to_email`` (scrub) is in E;
* ``mka_compliance_expected`` the expected-roster rows for E (email, names). EXISTING GAP FIXED HERE: the
                              anonymise path never touched them. They are DELETED (the personal data is the email +
                              name; the roster can be re-imported from its source of truth, which will no longer
                              contain a person who asked to be erased).

Email-keyed rows are only touched in orgs the user belongs to (same rule as ``attributes.delete_attributes``).

``known_emails`` MUST run before the upstream anonymise has flushed the placeholder address and BEFORE
``delete_attributes`` removes ``email_seen``: it reads the pending ``User.email`` history from the session's
identity map. Nothing here commits (the anonymise is one transaction); :func:`purge_older_than` is a standalone job
and does commit.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import delete, or_
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm.util import identity_key
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.mka_automation import MkaAutomationEvent, MkaAutomationSendLog, utcnow
from src.db.mka_compliance import MkaComplianceExpected
from src.db.mka_user_attributes import MkaUserAttributes
from src.db.user_organizations import UserOrganization
from src.db.users import User

logger = logging.getLogger(__name__)

PLACEHOLDER_DOMAINS = ("anonymized.example.com", "anonymized.invalid")
DEFAULT_RETENTION_MONTHS = 18


def _clean(address: Optional[str]) -> Optional[str]:
    value = (address or "").strip().lower()
    if not value or "@" not in value or value.rsplit("@", 1)[-1] in PLACEHOLDER_DOMAINS:
        return None
    return value


async def _user_row(db: AsyncSession, user_id: int) -> Optional[User]:
    """The User from the identity map WITHOUT emitting SQL (a query would autoflush the pending scrub and
    wipe the attribute history we need); falls back to a normal load."""
    found = db.sync_session.identity_map.get(identity_key(User, user_id))
    return found if found is not None else await db.get(User, user_id)


async def known_emails(db: AsyncSession, user_id: int) -> set[str]:
    """Every address we may hold for the user: current/pre-anonymise ``User.email``, ``email_seen`` of the
    identity-attributes row, and the ``intended_email`` of the user's own send-log rows. Placeholders excluded."""
    emails: set[str] = set()
    user = await _user_row(db, user_id)
    if user is not None:
        history = sa_inspect(user).attrs.email.history
        for value in (*history.added, *history.unchanged, *history.deleted):
            if cleaned := _clean(value):
                emails.add(cleaned)
    seen = (await db.execute(select(MkaUserAttributes.email_seen).where(MkaUserAttributes.user_id == user_id))).scalars().all()
    emails.update(c for c in map(_clean, seen) if c)
    logged = (
        await db.execute(select(MkaAutomationSendLog.intended_email).where(MkaAutomationSendLog.user_id == user_id))
    ).scalars().all()
    emails.update(c for c in map(_clean, logged) if c)
    return emails


def _member_orgs(user_id: int):
    return select(UserOrganization.org_id).where(UserOrganization.user_id == user_id)


async def _uuid(db: AsyncSession, user_id: int) -> Optional[str]:
    user = await _user_row(db, user_id)
    return getattr(user, "user_uuid", None)


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


async def export_user_records(db: AsyncSession, user_id: int) -> dict:
    """The user's own automation + roster records for the GDPR access export (no other person's data)."""
    emails = await known_emails(db, user_id)
    orgs = _member_orgs(user_id)
    user_uuid = await _uuid(db, user_id)

    event_filter = MkaAutomationEvent.user_id == user_id
    if user_uuid:
        event_filter = or_(event_filter, MkaAutomationEvent.user_uuid == user_uuid)
    events = (await db.execute(select(MkaAutomationEvent).where(event_filter).order_by(MkaAutomationEvent.id))).scalars().all()

    log_filter = MkaAutomationSendLog.user_id == user_id
    if emails:
        log_filter = or_(
            log_filter,
            (MkaAutomationSendLog.org_id.in_(orgs)) & (MkaAutomationSendLog.intended_email.in_(emails)),  # type: ignore[attr-defined]
        )
    sends = (await db.execute(select(MkaAutomationSendLog).where(log_filter).order_by(MkaAutomationSendLog.id))).scalars().all()

    roster = []
    if emails:
        roster = (
            await db.execute(
                select(MkaComplianceExpected)
                .where(MkaComplianceExpected.org_id.in_(orgs), MkaComplianceExpected.email.in_(emails))  # type: ignore[attr-defined]
                .order_by(MkaComplianceExpected.id)
            )
        ).scalars().all()

    return {
        "events": [
            {"org_id": e.org_id, "event": e.event, "status": e.status, "delivery_id": e.delivery_id,
             "course_uuid": e.course_uuid, "assignment_uuid": e.assignment_uuid, "note": e.note,
             "received_at": _iso(e.received_at)}
            for e in events
        ],
        "send_log": [
            {"org_id": s.org_id, "kind": s.kind, "to_email": s.to_email, "intended_email": s.intended_email,
             "subject": s.subject, "status": s.status, "test_mode": s.test_mode, "cycle_id": s.cycle_id,
             "course_id": s.course_id, "created_at": _iso(s.created_at), "sent_at": _iso(s.sent_at)}
            for s in sends
        ],
        "compliance_roster": [
            {"org_id": r.org_id, "cycle_id": r.cycle_id, "email": r.email, "department": r.department,
             "level": r.level, "majlis": r.majlis, "region": r.region, "role_title": r.role_title,
             "person_name": r.person_name, "appointed_on": r.appointed_on.isoformat() if r.appointed_on else None}
            for r in roster
        ],
    }


async def scrub_user_records(db: AsyncSession, user_id: int) -> dict:
    """GDPR anonymise: delete the user's event/send-log rows and expected-roster rows. Does NOT commit.

    Call BEFORE ``delete_attributes`` (it removes ``email_seen``) and before the pending ``User.email``
    placeholder is flushed. Returns row counts (never the data)."""
    emails = await known_emails(db, user_id)
    orgs = _member_orgs(user_id)
    user_uuid = await _uuid(db, user_id)
    counts = {"events": 0, "send_log": 0, "compliance_roster": 0}

    event_filter = MkaAutomationEvent.user_id == user_id
    if user_uuid:
        event_filter = or_(event_filter, MkaAutomationEvent.user_uuid == user_uuid)
    counts["events"] = (await db.execute(delete(MkaAutomationEvent).where(event_filter))).rowcount or 0

    log_filter = MkaAutomationSendLog.user_id == user_id
    if emails:
        log_filter = or_(
            log_filter,
            (MkaAutomationSendLog.org_id.in_(orgs))  # type: ignore[attr-defined]
            & or_(MkaAutomationSendLog.intended_email.in_(emails), MkaAutomationSendLog.to_email.in_(emails)),  # type: ignore[attr-defined]
        )
    counts["send_log"] = (await db.execute(delete(MkaAutomationSendLog).where(log_filter))).rowcount or 0

    if emails:
        counts["compliance_roster"] = (
            await db.execute(
                delete(MkaComplianceExpected).where(
                    MkaComplianceExpected.org_id.in_(orgs),  # type: ignore[attr-defined]
                    MkaComplianceExpected.email.in_(emails),  # type: ignore[attr-defined]
                )
            )
        ).rowcount or 0
    logger.info("automation GDPR scrub user=%s %s", user_id, counts)
    return counts


def _months_ago(now: datetime, months: int) -> datetime:
    year, month = divmod(now.year * 12 + (now.month - 1) - months, 12)
    month += 1
    day = now.day
    while True:  # clamp to the last valid day of the target month (Mar 31 minus 1 month -> Feb 28)
        try:
            return now.replace(year=year, month=month, day=day)
        except ValueError:
            day -= 1


async def purge_older_than(
    db: AsyncSession, months: int = DEFAULT_RETENTION_MONTHS, *, now: Optional[datetime] = None
) -> dict:
    """Retention: delete send-log rows (``created_at``) and events (``received_at``) older than ``months``.

    Also covers rows keyed only by email. Commits. ``months`` must be >= 1 (a 0/negative value would purge
    everything and is refused). ``now`` is naive UTC, injectable for tests."""
    if not isinstance(months, int) or isinstance(months, bool) or months < 1:
        raise ValueError("months must be an integer >= 1")
    moment = now or utcnow()
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc).replace(tzinfo=None)
    cutoff = _months_ago(moment, months)
    sends = (await db.execute(delete(MkaAutomationSendLog).where(MkaAutomationSendLog.created_at < cutoff))).rowcount or 0
    events = (await db.execute(delete(MkaAutomationEvent).where(MkaAutomationEvent.received_at < cutoff))).rowcount or 0
    await db.commit()
    logger.info("automation retention purge cutoff=%s send_log=%s events=%s", cutoff.date(), sends, events)
    return {"cutoff": cutoff, "send_log": sends, "events": events}


async def purge_test_rows(db: AsyncSession, org_id: int) -> int:
    """Operator helper: forget the test-mode send-log rows of an org (to re-run a review send). Commits."""
    n = (
        await db.execute(
            delete(MkaAutomationSendLog).where(
                MkaAutomationSendLog.org_id == org_id, MkaAutomationSendLog.test_mode == True  # noqa: E712
            )
        )
    ).rowcount or 0
    await db.commit()
    return n


__all__ = ["known_emails", "export_user_records", "scrub_user_records", "purge_older_than", "purge_test_rows"]
