"""MKA fork: auto-enrol on Google sign-in (spec 2026-10-05 section 2 A). Synthetic ``example.invalid`` data only."""

import asyncio
from datetime import date, datetime
from unittest.mock import patch

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlmodel import select

from src.db.courses.courses import Course
from src.db.mka_automation import MkaAutomationEvent
from src.db.mka_compliance import MkaComplianceCycle, MkaComplianceCycleCourse, MkaComplianceExpected
from src.db.trail_runs import TrailRun
from src.db.trails import Trail
from src.db.users import User
from src.services.mka import attributes as attrs
from src.services.mka import automation_enroll as enroll
from src.tests.routers.mka_compliance_world import add_attributes, add_course, add_user

TODAY = "2026-11-05"
EMAIL = "tabligh.albany@example.invalid"
FLAGS = ("MKA_AUTOMATION_ENABLED", "MKA_AUTOENROLL_ENABLED")


@pytest.fixture(autouse=True)
def flags_on(monkeypatch):
    for f in FLAGS:
        monkeypatch.setenv(f, "true")
    monkeypatch.setattr(enroll.compliance, "today", lambda: TODAY)


@pytest.fixture
def factory(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def make_cycle(db, org_id, base, *, label="2026-27", published=(True, True, True)):
    """Cycle with general (id base+1), tabligh (base+2) and maal (base+3) courses."""
    cyc = MkaComplianceCycle(org_id=org_id, label=label, starts_on=date(2026, 11, 1), deadline_on=date(2026, 12, 1))
    db.add(cyc)
    await db.commit()
    await db.refresh(cyc)
    for i, (kind, dept) in enumerate((("general", None), ("department", "tabligh"), ("department", "maal"))):
        cid = base + 1 + i
        await add_course(db, org_id, cid, f"course_{cid}", f"C{cid}", 0)
        course = (await db.execute(select(Course).where(Course.id == cid))).scalars().one()
        course.published = published[i]
        db.add(course)
        db.add(MkaComplianceCycleCourse(org_id=org_id, cycle_id=cyc.id, course_id=cid, course_uuid=f"course_{cid}",
                                        kind=kind, department=dept))
    await db.commit()
    return cyc


async def roster(db, org_id, cycle_id, email=EMAIL, *rows):
    for dept, level, title in rows or (("tabligh", "local", "Secretary"),):
        db.add(MkaComplianceExpected(org_id=org_id, cycle_id=cycle_id, email=email, department=dept, level=level,
                                     role_title=title))
    await db.commit()


async def learner(db, org_id, uid=10, email=EMAIL):
    await add_user(db, org_id, uid, email)
    await add_attributes(db, uid, email)
    return (await db.execute(select(User).where(User.id == uid))).scalars().one()


async def enrolled(db, uid):
    return sorted(r.course_id for r in (await db.execute(select(TrailRun).where(TrailRun.user_id == uid))).scalars().all())


async def events(db, status=None):
    q = select(MkaAutomationEvent)
    rows = (await db.execute(q)).scalars().all()
    return [e for e in rows if status is None or e.status == status]


@pytest.mark.asyncio
async def test_flags_off_is_a_noop(db, org, factory, monkeypatch):
    cyc = await make_cycle(db, org.id, 100)
    await roster(db, org.id, cyc.id)
    u = await learner(db, org.id)
    for off in FLAGS:
        monkeypatch.delenv(off)
        await enroll.autoenroll_user(factory, u)
        monkeypatch.setenv(off, "true")
    assert await enrolled(db, u.id) == [] and await events(db) == []


@pytest.mark.asyncio
async def test_google_proven_roster_match_enrols_general_and_department(db, org, factory):
    cyc = await make_cycle(db, org.id, 100)
    await roster(db, org.id, cyc.id)
    u = await learner(db, org.id)
    await enroll.autoenroll_user(factory, u)
    assert await enrolled(db, u.id) == [101, 102]  # general + tabligh, not maal
    ev = await events(db)
    assert [(e.status, e.event) for e in ev] == [("processed", "autoenroll")]
    assert ev[0].delivery_id.startswith("autoenroll:") and EMAIL not in repr(ev[0].__dict__)


@pytest.mark.asyncio
async def test_two_roles_get_both_department_courses_once(db, org, factory):
    cyc = await make_cycle(db, org.id, 100)
    await roster(db, org.id, cyc.id, EMAIL, ("tabligh", "local", "Secretary"), ("maal", "local", "Secretary"),
                 ("tabligh", "regional", "Deputy"))
    u = await learner(db, org.id)
    await enroll.autoenroll_user(factory, u)
    assert await enrolled(db, u.id) == [101, 102, 103]


@pytest.mark.asyncio
async def test_national_executive_gets_general_only(db, org, factory):
    cyc = await make_cycle(db, org.id, 100)
    await roster(db, org.id, cyc.id, EMAIL, ("", "national", "Muqami"))
    u = await learner(db, org.id)
    plan = await enroll.autoenroll_user(factory, u)
    assert await enrolled(db, u.id) == [101] and plan.course_ids == [101]


@pytest.mark.asyncio
async def test_unpublished_course_is_skipped_and_recorded_then_picked_up_later(db, org, factory):
    cyc = await make_cycle(db, org.id, 100, published=(True, False, True))
    await roster(db, org.id, cyc.id)
    u = await learner(db, org.id)
    await enroll.autoenroll_user(factory, u)
    assert await enrolled(db, u.id) == [101]
    skipped = await events(db, "skipped_unpublished")
    assert [e.course_uuid for e in skipped] == ["course_102"]
    await enroll.autoenroll_user(factory, u)  # still draft: no duplicate event noise
    assert len(await events(db, "skipped_unpublished")) == 1
    c = (await db.execute(select(Course).where(Course.id == 102))).scalars().one()
    c.published = True
    db.add(c)
    await db.commit()
    await enroll.autoenroll_user(factory, u)  # next login enrols it
    assert await enrolled(db, u.id) == [101, 102]


@pytest.mark.asyncio
async def test_second_login_is_idempotent(db, org, factory):
    cyc = await make_cycle(db, org.id, 100)
    await roster(db, org.id, cyc.id)
    u = await learner(db, org.id)
    for _ in range(3):
        await enroll.autoenroll_user(factory, u)
    assert await enrolled(db, u.id) == [101, 102]
    assert len((await db.execute(select(Trail).where(Trail.user_id == u.id))).scalars().all()) == 1
    assert len(await events(db, "processed")) == 1  # nothing new on repeat logins


@pytest.mark.asyncio
async def test_concurrent_calls_do_not_duplicate(db, org, factory):
    cyc = await make_cycle(db, org.id, 100)
    await roster(db, org.id, cyc.id)
    u = await learner(db, org.id)
    await asyncio.gather(*(enroll.autoenroll_user(factory, u) for _ in range(4)))
    assert await enrolled(db, u.id) == [101, 102]


@pytest.mark.asyncio
async def test_losing_the_insert_race_is_harmless(db, org, factory):
    """A TrailRun inserted by someone else between plan and insert must not error or be duplicated."""
    cyc = await make_cycle(db, org.id, 100)
    await roster(db, org.id, cyc.id)
    u = await learner(db, org.id)
    await enroll.autoenroll_user(factory, u)
    real = enroll.plan_autoenroll
    async def stale_plan(s, user, today=None):  # a plan computed before the first enrolment finished
        return await real(s, user, today)
    with patch.object(enroll, "plan_autoenroll", stale_plan):
        await enroll.autoenroll_user(factory, u)
    assert await enrolled(db, u.id) == [101, 102]
    assert await events(db, "error") == []


@pytest.mark.asyncio
async def test_cross_org_roster_never_enrols_into_another_orgs_courses(db, org, other_org, factory):
    cyc1 = await make_cycle(db, org.id, 100)
    cyc2 = await make_cycle(db, other_org.id, 200)
    await roster(db, other_org.id, cyc2.id)  # on org 2's roster only
    u = await learner(db, org.id)  # but a member of org 1 only
    await enroll.autoenroll_user(factory, u)
    assert await enrolled(db, u.id) == []
    assert [(e.org_id, e.status, e.note) for e in await events(db)] == [(other_org.id, "ignored", "not_member")]
    # on both rosters + member of both: each org enrols into its OWN courses only
    await roster(db, org.id, cyc1.id)
    from src.db.user_organizations import UserOrganization
    db.add(UserOrganization(user_id=u.id, org_id=other_org.id, role_id=4, creation_date=str(datetime.now()),
                            update_date=str(datetime.now())))
    await db.commit()
    await enroll.autoenroll_user(factory, u)
    runs = (await db.execute(select(TrailRun).where(TrailRun.user_id == u.id))).scalars().all()
    assert sorted((r.org_id, r.course_id) for r in runs) == [(1, 101), (1, 102), (2, 201), (2, 202)]


@pytest.mark.asyncio
async def test_roster_of_a_non_active_cycle_does_not_enrol(db, org, factory):
    old = await make_cycle(db, org.id, 100, label="2025-26")
    old.starts_on, old.deadline_on = date(2025, 11, 1), date(2025, 12, 1)
    db.add(old)
    await db.commit()
    await make_cycle(db, org.id, 200)  # active one has no roster row for this person
    await roster(db, org.id, old.id)
    u = await learner(db, org.id)
    await enroll.autoenroll_user(factory, u)
    assert await enrolled(db, u.id) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("breakage", ["stale", "no_hd", "email_changed", "no_row", "email_seen_old"])
async def test_unproven_identity_is_never_enrolled_and_makes_no_noise(db, org, factory, breakage):
    cyc = await make_cycle(db, org.id, 100)
    await roster(db, org.id, cyc.id)
    u = await learner(db, org.id)
    row = await attrs.get_row(db, u.id)
    if breakage == "stale":
        row.stale = True
    elif breakage == "no_hd":
        row.verified_hd = None
    elif breakage == "email_seen_old":
        row.email_seen = "someone.else@example.invalid"
    elif breakage == "email_changed":  # profile email switched to the roster role address; proof was for the old one
        u.email = "role.address@example.invalid"
        db.add(u)
        await roster(db, org.id, cyc.id, "role.address@example.invalid")
    elif breakage == "no_row":
        await db.delete(row)
        row = None
    if row is not None:
        db.add(row)
    await db.commit()
    plan = await enroll.autoenroll_user(factory, u)
    assert plan.reason == "unproven"
    assert await enrolled(db, u.id) == [] and await events(db) == []


@pytest.mark.asyncio
async def test_non_google_signup_without_proof_has_no_row_and_is_not_enrolled(db, org, factory):
    cyc = await make_cycle(db, org.id, 100)
    await roster(db, org.id, cyc.id)
    await add_user(db, org.id, 11, EMAIL, signup="email")
    u = (await db.execute(select(User).where(User.id == 11))).scalars().one()
    plan = await enroll.autoenroll_user(factory, u)
    assert plan.reason == "unproven" and await enrolled(db, 11) == []


@pytest.mark.asyncio
async def test_no_roster_match_costs_exactly_one_query(db, org, engine, factory):
    cyc = await make_cycle(db, org.id, 100)
    await roster(db, org.id, cyc.id)
    u = await learner(db, org.id, uid=12, email="not.on.roster@example.invalid")
    seen = []
    def spy(conn, cursor, statement, *a):
        seen.append(statement)
    event.listen(engine.sync_engine, "before_cursor_execute", spy)
    try:
        plan = await enroll.autoenroll_user(factory, u)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", spy)
    assert plan.reason == "no_match"
    selects = [s for s in seen if s.lstrip().upper().startswith("SELECT")]
    assert len(selects) == 1 and "mka_compliance_expected" in selects[0] and len(seen) == 1


@pytest.mark.asyncio
async def test_plan_is_read_only_and_describes_the_enrolment(db, org, factory):
    cyc = await make_cycle(db, org.id, 100, published=(True, True, False))
    await roster(db, org.id, cyc.id, EMAIL, ("tabligh", "local", "Secretary"), ("maal", "local", "Secretary"))
    u = await learner(db, org.id)
    async with factory() as s:
        plan = await enroll.plan_autoenroll(s, u)
    assert sorted(plan.course_ids) == [101, 102]
    assert plan.orgs[0].skipped_unpublished == [(103, "course_103")]
    assert await enrolled(db, u.id) == [] and await events(db) == []


@pytest.mark.asyncio
async def test_failure_during_enrolment_is_contained_rolled_back_and_recorded(db, org, factory, monkeypatch):
    cyc = await make_cycle(db, org.id, 100)
    await roster(db, org.id, cyc.id)
    u = await learner(db, org.id)
    calls = {"n": 0}

    def boom(mapper, connection, target):
        calls["n"] += 1
        if calls["n"] == 2:  # fail on the SECOND course: the first must roll back too (fail-closed)
            raise RuntimeError("boom")

    event.listen(TrailRun, "before_insert", boom)
    try:
        plan = await enroll.autoenroll_user(factory, u)  # does not raise
    finally:
        event.remove(TrailRun, "before_insert", boom)
    assert plan.orgs[0].reason == "error"
    assert await enrolled(db, u.id) == []
    assert [e.note for e in await events(db, "error")] == ["enrol_failed:RuntimeError"]  # a class name, never data
    await enroll.autoenroll_user(factory, u)
    assert await enrolled(db, u.id) == [101, 102]


@pytest.mark.asyncio
async def test_unexpected_exception_never_escapes(db, org, factory, monkeypatch):
    u = await learner(db, org.id)
    async def boom(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(enroll, "plan_autoenroll", boom)
    plan = await enroll.autoenroll_user(factory, u)
    assert plan.reason == "error"


@pytest.mark.asyncio
async def test_login_hook_enrols_and_a_failure_never_breaks_login_or_the_callers_session(db, org, monkeypatch):
    from src.services.auth.session import issue_session_or_challenge

    cyc = await make_cycle(db, org.id, 100)
    await roster(db, org.id, cyc.id, "tabligh.albany@mkausa.org")
    await add_user(db, org.id, 20, "tabligh.albany@mkausa.org")  # google signup on a Google-only domain
    u = (await db.execute(select(User).where(User.id == 20))).scalars().one()
    with patch("src.services.auth.session.is_mfa_active", return_value=False):
        result = await issue_session_or_challenge(db, u, amr="google")
    assert result.access_token
    assert await enrolled(db, 20) == [101, 102]
    # failure path: login still succeeds and the caller's session is still usable
    await db.execute(TrailRun.__table__.delete())
    await db.commit()
    with patch("src.services.auth.session.is_mfa_active", return_value=False), \
         patch.object(enroll, "plan_autoenroll", side_effect=RuntimeError("boom")):
        result = await issue_session_or_challenge(db, u, amr="google")
    assert result.access_token
    assert (await db.execute(select(User).where(User.id == 20))).scalars().one().id == 20
    assert await enrolled(db, 20) == []


@pytest.mark.asyncio
async def test_login_hook_does_not_enrol_when_flag_off(db, org, monkeypatch):
    from src.services.auth.session import issue_session_or_challenge

    cyc = await make_cycle(db, org.id, 100)
    await roster(db, org.id, cyc.id, "tabligh.albany@mkausa.org")
    await add_user(db, org.id, 20, "tabligh.albany@mkausa.org")
    u = (await db.execute(select(User).where(User.id == 20))).scalars().one()
    monkeypatch.delenv("MKA_AUTOENROLL_ENABLED")
    with patch("src.services.auth.session.is_mfa_active", return_value=False):
        await issue_session_or_challenge(db, u, amr="google")
    assert await enrolled(db, 20) == []
