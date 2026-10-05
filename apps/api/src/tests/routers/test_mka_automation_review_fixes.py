"""MKA fork: regression tests for the independent review of the combined automation branch (H1, M3, M4).

Each test here FAILED before its fix (the fix commits say which). Fixtures come from the seam C router tests; the
transport is mocked and every address is ``example.invalid``."""

from datetime import date

import pytest
from sqlmodel import select

from src.db.mka_automation import MkaAutomationEvent, MkaAutomationSendLog
from src.db.mka_compliance import MkaComplianceCycle, MkaComplianceCycleCourse, MkaComplianceExpected
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
