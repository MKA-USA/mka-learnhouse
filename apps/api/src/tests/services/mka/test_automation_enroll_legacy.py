"""MKA fork: review M1, auto-enrol must not depend on a unique constraint that only exists in the model.

Nothing here runs Alembic: tables come from ``create_all`` at first startup, which never adds a constraint to a table
that already exists. A ``trailrun`` table that predates ``uq_trailrun_trail_course_user`` therefore has NO unique
constraint, and ``INSERT ... ON CONFLICT (trail_id, course_id, user_id)`` fails on it. These tests build that table
explicitly (without the constraint) and prove enrolment still works and cannot duplicate."""

import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlmodel import select

from src.db.mka_automation import MkaAutomationEvent
from src.db.trail_runs import TrailRun
from src.services.mka import automation_enroll as enroll
from src.tests.services.mka.test_automation_enroll import (  # noqa: F401
    EMAIL, TODAY, enrolled, events, flags_on, learner, make_cycle, roster,
)


@pytest.fixture
async def legacy_trailrun(engine):
    """Replace ``trailrun`` by a table that has NO unique constraint, exactly like a pre-constraint deployment."""
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE trailrun"))
        await conn.execute(text(
            "CREATE TABLE trailrun (id INTEGER PRIMARY KEY, data JSON, status VARCHAR, trail_id INTEGER, "
            "course_id INTEGER, org_id INTEGER, user_id INTEGER, creation_date VARCHAR, update_date VARCHAR)"
        ))
    async with engine.connect() as conn:
        rows = (await conn.execute(text("SELECT sql FROM sqlite_master WHERE name = 'trailrun'"))).scalars().all()
    assert rows and "UNIQUE" not in rows[0].upper()  # the premise of every test below
    yield


@pytest.fixture
def factory(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def test_enrolment_works_on_a_table_without_the_unique_constraint(db, org, factory, legacy_trailrun):
    cyc = await make_cycle(db, org.id, 100)
    await roster(db, org.id, cyc.id)
    u = await learner(db, org.id)
    await enroll.autoenroll_user(factory, u)
    assert await enrolled(db, u.id) == [101, 102]
    assert [e.status for e in await events(db)] == ["processed"]  # no enrol error was recorded


async def test_repeat_logins_and_concurrent_calls_cannot_duplicate_without_the_constraint(db, org, factory, legacy_trailrun):
    cyc = await make_cycle(db, org.id, 100)
    await roster(db, org.id, cyc.id)
    u = await learner(db, org.id)
    await asyncio.gather(*(enroll.autoenroll_user(factory, u) for _ in range(6)))  # a burst of simultaneous logins
    await enroll.autoenroll_user(factory, u)
    runs = (await db.execute(select(TrailRun).where(TrailRun.user_id == u.id))).scalars().all()
    assert sorted(r.course_id for r in runs) == [101, 102]  # exactly one run per course, no unique index to catch a dup
    assert await events(db, "error") == []


async def test_two_concurrent_enrol_org_calls_with_separate_sessions_insert_once(db, org, factory, legacy_trailrun):
    cyc = await make_cycle(db, org.id, 100)
    await roster(db, org.id, cyc.id)
    u = await learner(db, org.id)
    async with factory() as s0:
        plan = await enroll.plan_autoenroll(s0, u)
    op = plan.orgs[0]

    async def one() -> int:
        async with factory() as s:
            return await enroll._enrol_org(s, u.id, op)

    created = await asyncio.gather(one(), one(), one())
    assert sum(created) == 2  # general + tabligh, once in total
    assert await enrolled(db, u.id) == [101, 102]


async def test_a_run_the_learner_created_themselves_is_left_alone(db, org, factory, legacy_trailrun):
    cyc = await make_cycle(db, org.id, 100)
    await roster(db, org.id, cyc.id)
    u = await learner(db, org.id)
    await enroll.autoenroll_user(factory, u)
    (first,) = (await db.execute(select(TrailRun).where(TrailRun.course_id == 101))).scalars().all()
    await enroll.autoenroll_user(factory, u)
    (again,) = (await db.execute(select(TrailRun).where(TrailRun.course_id == 101))).scalars().all()
    assert first.id == again.id


async def test_a_failure_is_recorded_with_a_short_reason(db, org, factory, legacy_trailrun, monkeypatch):
    cyc = await make_cycle(db, org.id, 100)
    await roster(db, org.id, cyc.id)
    u = await learner(db, org.id)

    async def boom(*a, **k):
        raise ValueError(f"constraint failed for {EMAIL}")  # a message that holds PII must never be stored

    monkeypatch.setattr(enroll, "_enrol_org_locked", boom)
    await enroll.autoenroll_user(factory, u)
    (event,) = await events(db, "error")
    assert event.note == "enrol_failed:ValueError" and EMAIL not in repr(event.__dict__)
    assert isinstance(event, MkaAutomationEvent)
