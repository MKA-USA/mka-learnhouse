"""MKA fork: the Majlis Plan course (third compliance kind) in the receipts, records and enrolment flows. Synthetic data only."""

from datetime import date, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.db.mka_compliance import MkaComplianceCycle, MkaComplianceCycleCourse
from src.db.trail_runs import TrailRun
from src.db.users import User
from src.services.mka import automation_enroll as enroll
from src.services.mka import automation_receipts as receipts
from src.services.mka import compliance as comp
from src.tests.routers.mka_compliance_world import add_assignment, add_attributes, add_course, add_user, attest, expected

TODAY = "2026-11-05"
QAID = "qaid.albany@example.invalid"
SADR = "sadr@example.invalid"
CYC = MkaComplianceCycle(id=1, org_id=1, label="2026-27", starts_on=date(2026, 11, 1), deadline_on=date(2026, 12, 1))


def link(i, kind, dept=None, signoff=None):
    return MkaComplianceCycleCourse(id=i, org_id=1, cycle_id=1, course_id=100 + i, course_uuid=f"course_{100 + i}", kind=kind,
                                    department=dept, signoff_assignment_id=signoff)


def ctx(rows, links, signed_ids=()):
    required = [(lk, SimpleNamespace(name=lk.kind)) for lk in links if lk.signoff_assignment_id]
    signed = {a: datetime(2026, 11, 3) for a in signed_ids}
    return SimpleNamespace(rows=rows, required=required, signed=signed)


QAID_ROW = expected(1, 1, QAID, "", "local", "Albany", "Northeast", "Qaid", "Q One")
SADR_ROW = expected(1, 1, SADR, "", "national", None, None, "Sadr", "S One")
NAIB_ROW = expected(1, 1, "naib@example.invalid", "", "local", "Albany", "Northeast", "Naib Qaid I", "N One")


def test_is_all_set_needs_both_signoffs_for_a_qaid_but_only_general_for_others():
    links = [link(1, "general", signoff=5001), link(2, "majlis-plan", signoff=5002)]
    assert receipts.is_all_set(ctx([QAID_ROW], links, [5001])) is False
    assert receipts.is_all_set(ctx([QAID_ROW], links, [5002])) is False
    assert receipts.is_all_set(ctx([QAID_ROW], links, [5001, 5002])) is True
    assert receipts.is_all_set(ctx([NAIB_ROW], links, [5001])) is False
    assert receipts.is_all_set(ctx([SADR_ROW], links, [5001])) is True  # plan not required of a Sadr
    # a person with two offices (Qaid + Sadr row) needs the plan for the Qaid office only
    assert receipts.is_all_set(ctx([SADR_ROW, QAID_ROW], links, [5001])) is False
    assert receipts.is_all_set(ctx([SADR_ROW, QAID_ROW], links, [5001, 5002])) is True


def test_is_all_set_with_no_plan_course_in_the_cycle_is_unchanged():
    links = [link(1, "general", signoff=5001)]
    assert receipts.is_all_set(ctx([QAID_ROW], links, [5001])) is True


def dataset(links, rows, progress=None):
    users = {r.email: i + 10 for i, r in enumerate(rows)}
    bundle = {"totals": {lk.course_id: 3 for lk in links}, "progress": progress or {}, "contact": {}}
    return comp.Dataset(CYC, rows, users, bundle, links, {}), users


def prog(attested):
    return {"enrolled": True, "lessons_done": 3, "lessons_total": 3, "completed_at": "2026-11-02",
            "attested_at": "2026-11-03" if attested else None, "last_activity_at": "2026-11-03", "trailrun_status": None}


def test_records_for_a_cycle_without_a_plan_course_are_unchanged():
    links = [link(1, "general", signoff=5001)]
    ds, users = dataset(links, [QAID_ROW, SADR_ROW])
    ds.progress = {(users[QAID], 101): prog(True), (users[SADR], 101): prog(True)}
    recs = {r["email"]: r for r in comp.person_records(ds, TODAY)}
    assert recs[QAID]["stage"] == "attested" and recs[SADR]["stage"] == "attested"
    assert {r["email"] for r in comp.course_records(ds, links[0], TODAY)} == {QAID, SADR}


def test_person_and_course_records_with_a_plan_course():
    links = [link(1, "general", signoff=5001), link(2, "majlis-plan", signoff=5002)]
    ds, users = dataset(links, [QAID_ROW, SADR_ROW])
    ds.progress = {(users[QAID], 101): prog(True), (users[SADR], 101): prog(True), (users[QAID], 102): prog(False)}
    recs = {r["email"]: r for r in comp.person_records(ds, TODAY)}
    assert recs[QAID]["stage"] == "completed"      # plan lessons done, plan not signed
    assert recs[SADR]["stage"] == "attested"       # plan not required of a Sadr
    ds.progress[(users[QAID], 102)] = prog(True)
    assert {r["email"]: r for r in comp.person_records(ds, TODAY)}[QAID]["stage"] == "attested"
    plan_rows = comp.course_records(ds, links[1], TODAY)
    assert [r["email"] for r in plan_rows] == [QAID]  # only roles that require the plan are listed for the plan course
    assert {r["email"] for r in comp.course_records(ds, links[0], TODAY)} == {QAID, SADR}


# ---- build_context + enrolment (DB) ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def flags_on(monkeypatch):
    for f in ("MKA_AUTOMATION_ENABLED", "MKA_AUTOENROLL_ENABLED"):
        monkeypatch.setenv(f, "true")
    monkeypatch.setattr(enroll.compliance, "today", lambda: TODAY)


@pytest.fixture
def factory(engine):
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def world(db, org):
    cyc = MkaComplianceCycle(org_id=org.id, label="2026-27", starts_on=date(2026, 11, 1), deadline_on=date(2026, 12, 1))
    db.add(cyc)
    await db.commit()
    await db.refresh(cyc)
    for cid, uuid, kind, asg in ((101, "course_general", "general", 5001), (102, "course_plan", "majlis-plan", 5002)):
        await add_course(db, org.id, cid, uuid, uuid, 1, 0, base=cid * 10)
        await add_assignment(db, org.id, cid, cid * 10 + 5, asg)
        db.add(MkaComplianceCycleCourse(org_id=org.id, cycle_id=cyc.id, course_id=cid, course_uuid=uuid, kind=kind,
                                        department=None, signoff_assignment_id=asg))
    for uid, email, title, level in ((31, QAID, "Qaid", "local"), (32, SADR, "Sadr", "national")):
        await add_user(db, org.id, uid, email)
        await add_attributes(db, uid, email)
        db.add(expected(org.id, cyc.id, email, "", level, None if level == "national" else "Albany", None, title, title))
    await db.commit()
    return cyc


async def user_of(db, uid):
    return (await db.execute(sa_select(User).where(User.id == uid))).scalars().one()


@pytest.mark.asyncio
async def test_build_context_requires_the_plan_for_a_qaid_and_all_set_needs_both(db, org):
    await world(db, org)
    links = {lk.kind: lk for lk in (await db.execute(sa_select(MkaComplianceCycleCourse))).scalars().all()}
    q, s = await user_of(db, 31), await user_of(db, 32)
    c, reason = await receipts.build_context(db, org.id, links["majlis-plan"], q)
    assert reason == "ok" and sorted(lk.kind for lk, _ in c.required) == ["general", "majlis-plan"]
    assert receipts.remaining_titles(c) == ["course_general", "course_plan"] and receipts.is_all_set(c) is False
    none, reason = await receipts.build_context(db, org.id, links["majlis-plan"], s)
    assert none is None and reason == "course_not_required_of_user"
    await attest(db, 31, 5001, TODAY)
    c, _ = await receipts.build_context(db, org.id, links["general"], q)
    assert receipts.is_all_set(c) is False
    await attest(db, 31, 5002, TODAY)
    c, _ = await receipts.build_context(db, org.id, links["general"], q)
    assert receipts.is_all_set(c) is True and receipts.remaining_titles(c) == []
    gs, _ = await receipts.build_context(db, org.id, links["general"], s)
    assert sorted(lk.kind for lk, _ in gs.required) == ["general"]


@pytest.mark.asyncio
async def test_second_autoenrol_run_for_a_qaid_is_idempotent(db, org, factory):
    await world(db, org)
    u = await user_of(db, 31)
    await enroll.autoenroll_user(factory, u)
    first = sorted(r.course_id for r in (await db.execute(sa_select(TrailRun).where(TrailRun.user_id == 31))).scalars().all())
    assert first == [101, 102]
    await enroll.autoenroll_user(factory, u)
    again = sorted(r.course_id for r in (await db.execute(sa_select(TrailRun).where(TrailRun.user_id == 31))).scalars().all())
    assert again == first
