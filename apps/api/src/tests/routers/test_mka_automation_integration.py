"""MKA fork: cross-seam sequences for the compliance automation (spec 2026-10-05): auto-enrol (A) -> signed webhook
receipt (B) -> reminders (C), the kill switches, and GDPR across all of them.

Fork-only. The transport is ALWAYS mocked, every send address is ``example.invalid`` (the GDPR case uses an mkausa.org
STRING only because the identity parser is domain-bound; nothing is ever sent there), and the webhook secret is a
local test value."""
# ruff: noqa: F811  (pytest fixtures imported from the seam B module are re-used as test arguments)

from datetime import datetime, timezone
from datetime import date as _date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlmodel import select

from src.db.mka_automation import MkaAutomationSendLog
from src.db.mka_compliance import MkaComplianceExpected
from src.db.trail_runs import TrailRun
from src.db.users import User
from src.services.mka import automation_enroll as enroll
from src.services.mka import automation_reminders as rem
from src.services.mka import compliance as svc
from src.tests.routers.mka_compliance_world import add_attributes, add_user, attest, expected
from src.tests.routers.test_mka_automation_receipts import (  # noqa: F401  (fixtures + helpers shared with seam B)
    CRON,
    EX,
    L1,
    SECRET,
    SWEEP,
    TESTER,
    TODAY,
    UNPROVEN,
    WEBHOOK,
    body_of,
    clean_env,
    events,
    logs,
    make_client,
    on,
    payload,
    post,
    transport,
    world,
)
from src.tests.services.test_mka_automation_gdpr import anonymise

RUN = "/api/v1/mka/automation/reminders/run"
MON = datetime(2026, 11, 16, 15, 0, tzinfo=timezone.utc)  # a Monday inside the cycle (2026-11-01 .. 2026-12-01)
CRON_HEADERS = {"X-MKA-Cron-Secret": CRON}
ROLE_ADDR = "nazim.tabligh.albany@example.invalid"


@pytest.fixture
def factory(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
def all_on(monkeypatch, on):  # noqa: F811
    monkeypatch.setenv("MKA_AUTOENROLL_ENABLED", "true")
    monkeypatch.setenv("MKA_REMINDERS_ENABLED", "true")
    monkeypatch.setenv("LEARNHOUSE_PLATFORM_URL", "https://ilm.example.invalid")
    monkeypatch.setenv("MKA_REMINDER_SCHEDULE", "11-16")
    monkeypatch.setattr(enroll.compliance, "today", lambda: "2026-11-16")
    monkeypatch.setattr(svc, "today", lambda: "2026-11-16")
    monkeypatch.setattr(rem, "current_instant", lambda: MON)


async def user_row(db, uid):
    return (await db.execute(select(User).where(User.id == uid))).scalars().one()


async def enrolled(db, uid):
    return sorted(r.course_id for r in (await db.execute(select(TrailRun).where(TrailRun.user_id == uid))).scalars().all())


async def sendlog(db):
    return list((await db.execute(select(MkaAutomationSendLog).order_by(MkaAutomationSendLog.id))).scalars().all())


async def run(c, *, dry, kind="reminder"):
    r = await c.post(RUN, params={"dry_run": "true" if dry else "false", "kind": kind}, headers=CRON_HEADERS)
    assert r.status_code == 200, r.text
    return r.json()


def org1(report):
    return next(o for o in report["orgs"] if o["org_id"] == 1)


# ---------------------------------------------------------------------------------------------------------
# (a) enrol -> sign-off -> signed webhook -> one receipt -> replay/sweep silent -> 'all set'
# ---------------------------------------------------------------------------------------------------------


async def test_a_enrol_then_signoff_receipt_replay_sweep_then_all_set(db, world, transport, all_on, factory, monkeypatch):
    monkeypatch.setenv("MKA_AUTOMATION_TEST_RECIPIENT", TESTER)
    u = await user_row(db, 31)  # Google sign-in, proven, tabligh local on the roster

    await enroll.autoenroll_user(factory, u)
    assert await enrolled(db, 31) == [101, 102]  # General + Tabligh (both published), nothing else
    await enroll.autoenroll_user(factory, u)  # a second login changes nothing
    assert await enrolled(db, 31) == [101, 102]

    await attest(db, 31, 5001, TODAY)  # sign-off of the General course
    async with make_client(db) as c:
        first = payload(delivery="dlv_int_1")
        assert (await post(c, first)).status_code == 200
        assert [m["to"] for m in transport.calls] == [TESTER]  # the TEST RECIPIENT, never the learner
        assert L1 not in repr(transport.calls[0]["to"])

        await post(c, first)  # the same delivery replayed
        assert len(transport.calls) == 1

        assert (await c.post(SWEEP, headers={"X-MKA-Cron-Secret": CRON})).status_code == 200
        assert len(transport.calls) == 1  # the sweep finds nothing more to deliver

        await attest(db, 31, 5002, TODAY)  # second course's sign-off
        second = payload(assignment="assignment_5002", course="course_tabligh", delivery="dlv_int_2")
        assert (await post(c, second)).status_code == 200
        # the contact-check (5003) is not a sign-off, so the receipt for 5002 AND the one 'all set' follow
        kinds = sorted(r.kind for r in await sendlog(db) if r.kind in ("receipt", "allset"))
        assert kinds.count("allset") == 1 and kinds.count("receipt") == 2
        assert {m["to"] for m in transport.calls} == {TESTER}

        n = len(transport.calls)
        await post(c, second)
        await c.post(SWEEP, headers={"X-MKA-Cron-Secret": CRON})
        assert len(transport.calls) == n  # replay and sweep stay silent, still exactly one 'all set'
    assert [r.kind for r in await sendlog(db)].count("allset") == 1
    assert all(r.test_mode for r in await sendlog(db))


# ---------------------------------------------------------------------------------------------------------
# (b) reminders: dry-run lists, attestation removes, real run is test-addressed and weekly-capped
# ---------------------------------------------------------------------------------------------------------


async def test_b_reminders_dry_run_real_run_and_weekly_cap(db, world, transport, all_on, monkeypatch):
    monkeypatch.setenv("MKA_AUTOMATION_TEST_RECIPIENT", TESTER)
    async with make_client(db) as c:
        before = org1(await run(c, dry=True))["reminder"]
        assert before["ran"] and before["candidates"] == 3 and before["would_send"] == 3  # L1, EX, UNPROVEN
        assert transport.calls == [] and await sendlog(db) == []  # a preview writes and sends nothing

        for asg in (5001, 5002, 5003):  # L1 completes everything required of them
            await attest(db, 31, asg, "2026-11-16")
        after = org1(await run(c, dry=True))["reminder"]
        assert after["candidates"] == 2 and after["skipped_attested"] >= 1

        assert (await run(c, dry=False))["test_mode"] is True
        sent = transport.calls
        assert sent and {m["to"] for m in sent} == {TESTER}
        rows = [r for r in await sendlog(db) if r.kind == "reminder"]
        assert rows and all(r.test_mode and r.to_email == TESTER for r in rows)
        assert L1 not in {r.intended_email for r in rows}  # no reminder for the person who attested
        assert {EX, UNPROVEN} <= {r.intended_email for r in rows}
        assert len({r.dedupe_key for r in rows}) == len(rows)

        n_calls, n_rows = len(sent), len(rows)
        again = org1(await run(c, dry=False))["reminder"]  # same ISO week
        assert again["sent"] == 0
        assert len(transport.calls) == n_calls
        assert len([r for r in await sendlog(db) if r.kind == "reminder"]) == n_rows


# ---------------------------------------------------------------------------------------------------------
# (c) identity: unproven accounts and role-address take-overs are never enrolled, receipted or reminded as the role
# ---------------------------------------------------------------------------------------------------------


async def test_c_unproven_and_email_changed_to_a_role_address(db, world, transport, all_on, factory, monkeypatch):
    # user 33: on the roster but never proven; user 35: proven as someone else, then changed the account e-mail to an
    # office mailbox that IS on the roster.
    await add_user(db, 1, 35, "attacker35@example.invalid")
    await add_attributes(db, 35, "attacker35@example.invalid")
    me = await user_row(db, 35)
    me.email = ROLE_ADDR
    db.add(me)
    db.add(expected(1, world["cycle"].id, ROLE_ADDR, "tabligh", "local", "Albany", "Northeast", "Nazim Tabligh", "Real Nazim"))
    await db.commit()

    for uid in (33, 35):
        await enroll.autoenroll_user(factory, await user_row(db, uid))
        assert await enrolled(db, uid) == []
        await attest(db, uid, 5001, TODAY)

    async with make_client(db) as c:
        for uid, delivery in ((33, "dlv_c33"), (35, "dlv_c35")):
            await post(c, payload(user_uuid=f"user_{uid}", delivery=delivery))
        assert transport.calls == []  # no receipt, to anyone
        assert [r for r in await sendlog(db) if r.kind in ("receipt", "allset")] == []

        monkeypatch.delenv("MKA_AUTOMATION_TEST_RECIPIENT", raising=False)
        monkeypatch.setenv("MKA_AUTOMATION_TEST_RECIPIENT", TESTER)
        await run(c, dry=False)
    rows = await sendlog(db)
    assert {m["to"] for m in transport.calls} == {TESTER}
    # the office mailbox may be reminded as an OFFICE, but never attributed to the account that grabbed the address
    assert all(r.user_id != 35 for r in rows)
    assert all(r.user_id != 33 for r in rows if r.kind in ("receipt", "allset"))
    # the deliveries are recorded as handled-with-nothing-to-do, not as receipts
    notes = {e.user_id: e.note for e in await events(db) if e.user_id in (33, 35)}
    assert notes == {33: "not_on_roster_or_unproven", 35: "not_on_roster_or_unproven"}


# ---------------------------------------------------------------------------------------------------------
# (d) kill switches
# ---------------------------------------------------------------------------------------------------------


async def test_d_master_switch_off_is_a_noop_but_the_webhook_still_verifies_signatures(
    db, world, transport, all_on, factory, monkeypatch
):
    monkeypatch.delenv("MKA_AUTOMATION_ENABLED")  # every per-feature flag stays on; the master switch is off
    await attest(db, 31, 5001, TODAY)

    await enroll.autoenroll_user(factory, await user_row(db, 31))
    assert await enrolled(db, 31) == []

    async with make_client(db) as c:
        good = await post(c, payload(delivery="dlv_d1"))
        assert good.status_code == 200 and transport.calls == []
        assert (await post(c, payload(delivery="dlv_d2"), secret="wrong")).status_code == 401  # still authenticated
        tampered = body_of(payload(delivery="dlv_d3")).replace(b"user_31", b"user_32")
        assert (await c.post(WEBHOOK, content=tampered, headers={"X-Webhook-Signature": "deadbeef"})).status_code == 401

        assert (await c.post(SWEEP, headers={"X-MKA-Cron-Secret": CRON})).status_code == 200
        assert transport.calls == []
        report = await run(c, dry=False, kind="all")
        assert transport.calls == []
        assert org1(report)["reminder"].get("ran") in (False, None) or org1(report)["reminder"].get("sent", 0) == 0
    assert [r for r in await sendlog(db)] == []
    assert [e for e in await events(db) if e.status == "processed"] == []


async def test_d_each_feature_flag_alone_silences_its_own_seam(db, world, transport, all_on, factory, monkeypatch):
    monkeypatch.setenv("MKA_AUTOMATION_TEST_RECIPIENT", TESTER)
    monkeypatch.setenv("MKA_RECEIPTS_ENABLED", "false")
    monkeypatch.setenv("MKA_REMINDERS_ENABLED", "false")
    monkeypatch.setenv("MKA_AUTOENROLL_ENABLED", "false")
    await attest(db, 31, 5001, TODAY)
    await enroll.autoenroll_user(factory, await user_row(db, 31))
    assert await enrolled(db, 31) == []
    async with make_client(db) as c:
        assert (await post(c, payload(delivery="dlv_d9"))).status_code == 200
        await run(c, dry=False)
    assert transport.calls == []


# ---------------------------------------------------------------------------------------------------------
# (e) GDPR across the three seams
# ---------------------------------------------------------------------------------------------------------


async def test_e_anonymise_scrubs_events_and_send_log_and_keeps_the_office_row(db, org, world, transport, all_on, factory):
    office = "tabligh.albany@mkausa.org"  # parsed as an office (role mailbox); a string only, nothing is sent to it
    await add_user(db, org.id, 50, office)
    await add_attributes(db, 50, office)
    db.add(MkaComplianceExpected(org_id=org.id, cycle_id=world["cycle"].id, email=office, department="tabligh",
                                 level="local", majlis="Albany", region="Northeast", role_title="Nazim Tabligh",
                                 person_name="Outgoing Nazim", appointed_on=_date(2026, 11, 1)))
    await db.commit()
    await enroll.autoenroll_user(factory, await user_row(db, 50))
    assert await enrolled(db, 50) == [101, 102]
    await attest(db, 50, 5001, TODAY)
    await attest(db, 31, 5001, TODAY)
    async with make_client(db) as c:
        assert (await post(c, payload(user_uuid="user_50", delivery="dlv_e50"))).status_code == 200
        assert (await post(c, payload(delivery="dlv_e31"))).status_code == 200  # a bystander (user 31)

    mine_rows = [r for r in await sendlog(db) if r.user_id == 50]
    assert mine_rows and [e for e in await events(db) if e.user_id == 50]  # there IS something to scrub

    await anonymise(db, org, 50)

    assert [e for e in await events(db) if e.user_id == 50 or e.user_uuid == "user_50"] == []
    assert [r for r in await sendlog(db) if r.user_id == 50] == []
    assert [r for r in await sendlog(db) if r.user_id == 31]  # others are untouched
    assert [e for e in await events(db) if e.user_id == 31]
    (office_row,) = (await db.execute(select(MkaComplianceExpected).where(MkaComplianceExpected.email == office))).scalars().all()
    assert office_row.person_name is None and office_row.appointed_on is None  # the person is gone ...
    assert (office_row.role_title, office_row.department, office_row.majlis) == ("Nazim Tabligh", "tabligh", "Albany")  # ... the office stays
