"""MKA fork: regression tests for the independent review of the combined automation branch (H1, M3, M4).

Each test here FAILED before its fix (the fix commits say which). Fixtures come from the seam C router tests; the
transport is mocked and every address is ``example.invalid``."""

from datetime import date, timedelta

import pytest
from sqlmodel import select

from src.db.mka_automation import MkaAutomationEvent, MkaAutomationSendLog
from src.db.mka_compliance import MkaComplianceCycle, MkaComplianceCycleCourse, MkaComplianceExpected
from src.services.mka import automation_reminders as rem
from src.tests.routers.test_mka_automation_reminders_router import (  # noqa: F401
    BASE, GENERAL, MON, TABLIGH, TESTER, client_for, count, env, on, q, transport, world,
)


async def add_cycle(db, org, label, starts, deadline, course_id=102, course_uuid="course_tabligh"):
    cycle = MkaComplianceCycle(org_id=org.id, label=label, starts_on=starts, deadline_on=deadline)
    db.add(cycle)
    await db.commit()
    db.add(MkaComplianceCycleCourse(org_id=org.id, cycle_id=cycle.id, course_id=course_id, course_uuid=course_uuid,
                                    kind="department", department="tabligh", signoff_assignment_id=5002))
    db.add(MkaComplianceExpected(org_id=org.id, cycle_id=cycle.id, email="old.officeholder@example.invalid",
                                 department="tabligh", level="local", majlis="Albany", region="Northeast",
                                 role_title="Nazim Tabligh", person_name="Old Holder"))
    await db.commit()
    return cycle


# ---------------------------------------------------------------------------------------------------------
# H1: manual Remind only acts on the CURRENT, already-started cycle
# ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("dry", ["true", "false"])
async def test_last_years_cycle_cannot_be_reminded(db, org, world, transport, on, dry):
    past = await add_cycle(db, org, "2025-26", date(2025, 11, 1), date(2025, 12, 1))
    async with client_for(db, 1) as c:
        r = await c.post(TABLIGH, params=q(org, dry_run=dry, cycle_id=past.id))
    assert r.status_code == 409 and "current cycle" in r.json()["detail"]
    assert transport.calls == [] and await count(db, MkaAutomationSendLog) == 0 and await count(db, MkaAutomationEvent) == 0


@pytest.mark.parametrize("dry", ["true", "false"])
async def test_an_early_imported_future_cycle_cannot_be_reminded(db, org, world, transport, on, dry):
    future = await add_cycle(db, org, "2027-28", date(2027, 11, 1), date(2027, 12, 1))
    async with client_for(db, 1) as c:
        r = await c.post(TABLIGH, params=q(org, dry_run=dry, cycle_id=future.id))
    assert r.status_code == 409
    assert transport.calls == [] and await count(db, MkaAutomationSendLog) == 0 and await count(db, MkaAutomationEvent) == 0


async def test_the_current_cycle_still_works_with_or_without_an_explicit_id(db, org, world, transport, on):
    await add_cycle(db, org, "2025-26", date(2025, 11, 1), date(2025, 12, 1))  # an old cycle must not shadow it
    async with client_for(db, 1) as c:
        implicit = await c.post(TABLIGH, params=q(org))
        explicit = await c.post(TABLIGH, params=q(org, cycle_id=world.cycle.id))
    assert implicit.status_code == explicit.status_code == 200
    assert implicit.json()["would_send"] == explicit.json()["would_send"] == 4


# ---------------------------------------------------------------------------------------------------------
# M3: manual reminders have their own key space and never spend the scheduled weekly slot
# ---------------------------------------------------------------------------------------------------------


@pytest.fixture
def real_mode(monkeypatch):
    monkeypatch.delenv("MKA_AUTOMATION_TEST_RECIPIENT")  # real mode: the weekly cap counts real rows
    monkeypatch.setenv("MKA_REMINDER_SCHEDULE", "11-16")  # today (MON) is a scheduled reminder day


async def test_a_manual_remind_does_not_use_up_the_scheduled_weekly_reminder(db, org, world, transport, on, real_mode):
    async with client_for(db, 1) as c:
        manual = await c.post(TABLIGH, params=q(org, dry_run="false"))  # one course only
    assert manual.status_code == 200 and manual.json()["sent"] == 4
    report = await rem.run_all(db, dry_run=False, kind="reminder", now=MON)
    mine = next(o for o in report["orgs"] if o["org_id"] == org.id)["reminder"]
    # everybody outstanding in the org is still reminded by the scheduled run, including the 4 manual recipients
    assert mine["sent"] == mine["candidates"] == 8 and mine["skipped_recent"] == 0


async def test_manual_keys_are_per_course_and_per_week(db, org, world, transport, on, real_mode):
    async with client_for(db, 1) as c:
        t1 = await c.post(TABLIGH, params=q(org, dry_run="false"))
        g1 = await c.post(GENERAL, params=q(org, dry_run="false"))  # same people, another course: its own slot
    assert t1.json()["sent"] == 4 and g1.json()["sent"] == 8
    keys = sorted(r.dedupe_key for r in (await db.execute(select(MkaAutomationSendLog))).scalars().all())
    assert all(k.startswith("manual:") for k in keys) and len(keys) == 12
    assert any(k.startswith("manual:101:2026-W47:") for k in keys) and any(k.startswith("manual:102:2026-W47:") for k in keys)


async def test_a_second_manual_remind_of_the_same_course_in_the_same_week_reaches_nobody_twice(
    db, org, world, transport, on, real_mode, monkeypatch
):
    async with client_for(db, 1) as c:
        assert (await c.post(TABLIGH, params=q(org, dry_run="false"))).json()["sent"] == 4
        monkeypatch.setattr(rem, "current_instant", lambda: MON + timedelta(hours=25))  # past the 24 h course limit
        later = await c.post(TABLIGH, params=q(org, dry_run="false"))
    assert later.status_code == 200 and later.json()["sent"] == 0 and later.json()["skipped_recent"] == 4
    assert len(transport.calls) == 4


async def test_the_scheduled_run_does_not_count_manual_rows_against_the_weekly_cap(db, org, world, transport, on, real_mode):
    from src.services.mka import automation_send as send

    async with client_for(db, 1) as c:
        await c.post(GENERAL, params=q(org, dry_run="false"))
    week = send.current_iso_week(MON)
    assert await send.reminders_this_week(db, org.id, "l2@example.invalid", week) == 0
    assert not await send.reminded_this_week(db, org.id, "l2@example.invalid", week)
