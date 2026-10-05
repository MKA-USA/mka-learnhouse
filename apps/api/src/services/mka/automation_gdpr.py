"""MKA fork: GDPR export / scrub / retention for the compliance-automation data (spec 2026-10-05 section 4).

Called from the fork's own ``services/users/mka_profile.py`` hooks (``profile_status(include_attributes=True)`` for
the export, ``delete_profile`` for the anonymise), so no further upstream edit is needed.

IDENTITY RULE: an email address is only ever used as a key if it is PROVEN to belong to the user
(``attributes.is_address_proven``: fresh attributes row, Workspace ``verified_hd`` of that exact address, and the
address was the account's email). Never raw ``User.email`` history, never ``intended_email``: an unproven address
could be someone else's mailbox (a user can change their email to an address they do not own), and exporting or
erasing on it would expose or destroy another person's records. No proof -> nothing email-keyed is touched.

* ``mka_automation_event`` / ``mka_automation_send_log``: rows with ``user_id == U`` ONLY. Email-only rows (never
  signed-in role mailboxes) describe an office, not a person; the 18-month retention purge handles them.
* ``mka_compliance_expected``: rows for the user's PROVEN address, in orgs the user belongs to. For an org ROLE
  mailbox (the identity parser matches a role) the office row is KEPT (the next holder inherits it) and only the
  personal fields (``person_name``, ``appointed_on``) are nulled; for a personal address the row is DELETED.
  (Existing gap fixed: the anonymise path never touched these rows.)

``known_emails`` MUST run before the upstream anonymise flushes the placeholder address and BEFORE
``delete_attributes`` removes ``email_seen`` (it reads the pending ``User.email`` history from the identity map).
Nothing here commits except :func:`purge_older_than` / :func:`purge_test_rows` (standalone jobs).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Optional

from sqlalchemy import delete, or_, update
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm.util import identity_key
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.services.mka import attributes as attr_svc
from src.services.mka.identity_parser import parse_identity
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


def _account_email_before_anonymise(user: User) -> Optional[str]:
    history = sa_inspect(user).attrs.email.history
    if history.deleted:  # the upstream anonymise has set a placeholder but not flushed yet
        return history.deleted[0]
    return user.email


async def known_emails(db: AsyncSession, user_id: int) -> set[str]:
    """The addresses PROVEN to belong to the user (0 or 1): the attributes row's ``email_seen`` when
    ``is_address_proven`` holds for the account's email as it was before any pending anonymise."""
    user = await _user_row(db, user_id)
    if user is None:
        return set()
    original = _account_email_before_anonymise(user)  # read BEFORE any query below autoflushes the placeholder
    row = (await db.execute(select(MkaUserAttributes).where(MkaUserAttributes.user_id == user_id))).scalars().first()
    if row is None or not _clean(original):
        return set()
    if not attr_svc.is_address_proven(row, SimpleNamespace(email=original)):  # type: ignore[arg-type]
        return set()
    cleaned = _clean(row.email_seen)
    return {cleaned} if cleaned else set()


def is_role_mailbox(email: str) -> bool:
    """True when the identity parser reads the address as an office (a role), i.e. it outlives its holder."""
    parsed = parse_identity(email, attr_svc.get_rules())
    return parsed.status in ("matched", "partial", "ambiguous") and bool(parsed.role)


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

    sends = (
        await db.execute(select(MkaAutomationSendLog).where(MkaAutomationSendLog.user_id == user_id).order_by(MkaAutomationSendLog.id))
    ).scalars().all()

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
            # a test-mode row's to_email is the REVIEWER's address, not the data subject's: never export it (review L6)
            {"org_id": s.org_id, "kind": s.kind, "to_email": None if s.test_mode else s.to_email,
             "intended_email": s.intended_email,
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

    counts["send_log"] = (
        await db.execute(delete(MkaAutomationSendLog).where(MkaAutomationSendLog.user_id == user_id))
    ).rowcount or 0

    for email in emails:  # 0 or 1 PROVEN address
        in_scope = (MkaComplianceExpected.org_id.in_(orgs), MkaComplianceExpected.email == email)  # type: ignore[attr-defined]
        if is_role_mailbox(email):  # the office stays for the next holder; only the person goes
            counts["compliance_roster"] += (
                await db.execute(update(MkaComplianceExpected).where(*in_scope).values(person_name=None, appointed_on=None))
            ).rowcount or 0
        else:
            counts["compliance_roster"] += (await db.execute(delete(MkaComplianceExpected).where(*in_scope))).rowcount or 0
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
