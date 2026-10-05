"""MKA fork: review M2, a ``queued`` claim left behind by a crash must not mean permanent silent loss.

A claim older than ``MKA_AUTOMATION_CLAIM_LEASE_SECONDS`` (default 900) is taken over atomically and re-sent once; a
fresh claim is somebody else's send in flight. The transport is mocked; addresses are ``example.invalid``."""

import asyncio
from datetime import datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlmodel import select

from src.db.mka_automation import MkaAutomationSendLog
from src.services.mka import automation_config as cfg
from src.services.mka import automation_send as send
from src.services.mka.automation_send import send_automation_email
from src.tests.services.mka.test_automation_send import (  # noqa: F401
    REAL, env, kw, on, rows, transport,
)

T0 = datetime(2026, 11, 10, 12, 0)  # naive UTC


class Crash(BaseException):
    """A process dying mid-send: not an Exception, so the send function's own error handling never sees it."""


def queued(org, created_at, error=None, key="receipt:a1:7"):
    return MkaAutomationSendLog(org_id=org.id, kind="receipt", dedupe_key=key, to_email=REAL, intended_email=REAL,
                                subject="s", status="queued", created_at=created_at, error=error)


def test_the_lease_defaults_to_15_minutes_and_is_configurable(monkeypatch):
    assert cfg.claim_lease_seconds() == 900
    monkeypatch.setenv("MKA_AUTOMATION_CLAIM_LEASE_SECONDS", "60")
    assert cfg.claim_lease_seconds() == 60
    monkeypatch.setenv("MKA_AUTOMATION_CLAIM_LEASE_SECONDS", "0")
    assert cfg.claim_lease_seconds() == 900


async def test_a_stale_queued_claim_is_reclaimed_and_sent_once(db, org, transport, on):  # noqa: F811
    db.add(queued(org, T0 - timedelta(minutes=20)))
    await db.commit()
    res = await send_automation_email(db, **kw(org), now=T0)
    assert res.status == "sent" and len(transport.calls) == 1
    (row,) = await rows(db)
    assert row.status == "sent" and row.created_at == T0 and row.sent_at is not None
    again = await send_automation_email(db, **kw(org), now=T0 + timedelta(hours=3))
    assert again.status == "already_handled" and len(transport.calls) == 1  # sent rows are final


async def test_a_fresh_queued_claim_is_somebody_elses_send_in_flight(db, org, transport, on):  # noqa: F811
    db.add(queued(org, T0 - timedelta(minutes=14)))  # inside the 15 minute lease
    await db.commit()
    assert (await send_automation_email(db, **kw(org), now=T0)).status == "already_handled"
    assert transport.calls == []
    (row,) = await rows(db)
    assert row.status == "queued" and row.created_at == T0 - timedelta(minutes=14)


async def test_the_lease_is_configurable(db, org, transport, on, monkeypatch):  # noqa: F811
    monkeypatch.setenv("MKA_AUTOMATION_CLAIM_LEASE_SECONDS", "60")
    db.add(queued(org, T0 - timedelta(minutes=2)))
    await db.commit()
    assert (await send_automation_email(db, **kw(org), now=T0)).status == "sent"


async def test_a_claim_that_was_already_taken_over_once_is_not_retried_forever(db, org, transport, on):  # noqa: F811
    db.add(queued(org, T0 - timedelta(hours=2), error=send.STALE_CLAIM_MARK))  # reclaimed once, crashed again
    await db.commit()
    assert (await send_automation_email(db, **kw(org), now=T0)).status == "already_handled"
    assert transport.calls == []


async def test_crash_between_claim_and_send_then_recovery(db, org, transport, on, monkeypatch):  # noqa: F811
    def die(*a, **k):
        raise Crash()

    monkeypatch.setattr(send.email_utils, "send_email", die)
    with pytest.raises(Crash):
        await send_automation_email(db, **kw(org), now=T0)  # the claim is committed, the mail never leaves
    (row,) = await rows(db)
    assert row.status == "queued" and row.created_at == T0

    monkeypatch.setattr(send.email_utils, "send_email", transport)
    soon = await send_automation_email(db, **kw(org), now=T0 + timedelta(minutes=5))  # still inside the lease
    assert soon.status == "already_handled" and transport.calls == []
    later = await send_automation_email(db, **kw(org), now=T0 + timedelta(minutes=16))  # lease over: recovered
    assert later.status == "sent" and len(transport.calls) == 1
    (row,) = await rows(db)
    assert row.status == "sent" and row.error == send.STALE_CLAIM_MARK  # the audit trail says it was a takeover


async def test_only_one_of_two_racing_reclaims_wins(db, org, engine, transport, on):  # noqa: F811
    db.add(queued(org, T0 - timedelta(minutes=30)))
    await db.commit()
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def attempt():
        async with factory() as s:
            return (await send_automation_email(s, **kw(org), now=T0)).status

    results = await asyncio.gather(attempt(), attempt(), attempt())
    assert sorted(results) == ["already_handled", "already_handled", "sent"]
    assert len(transport.calls) == 1
    assert len(await rows(db)) == 1


async def test_the_reclaim_is_one_conditional_update(db, org, on):  # noqa: F811
    """Sequential proof of the atomicity the race above relies on: the first takeover refreshes the claim time, so a
    second takeover of the same row finds nothing past its lease."""
    db.add(queued(org, T0 - timedelta(minutes=30)))
    await db.commit()

    def fresh():
        return MkaAutomationSendLog(org_id=org.id, kind="receipt", dedupe_key="receipt:a1:7", to_email=REAL,
                                    intended_email=REAL, subject="s", status="queued", created_at=T0)

    first = await send._claim(db, fresh())
    second = await send._claim(db, fresh())
    assert first is not None and second is None


async def test_other_rows_are_never_touched_by_a_reclaim(db, org, transport, on):  # noqa: F811
    db.add_all([queued(org, T0 - timedelta(hours=1), key="receipt:other:1"), queued(org, T0 - timedelta(hours=1))])
    await db.commit()
    await send_automation_email(db, **kw(org), now=T0)
    other = (await db.execute(select(MkaAutomationSendLog).where(MkaAutomationSendLog.dedupe_key == "receipt:other:1"))).scalars().one()
    assert other.status == "queued" and other.error is None
