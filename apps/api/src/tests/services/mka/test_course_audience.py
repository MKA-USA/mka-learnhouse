"""MKA fork: course audience service (spec 2026-10-08). Synthetic example.invalid data only."""

import asyncio
from datetime import datetime

import pytest
from sqlalchemy import select

from src.db.courses.courses import Course
from src.db.mka_course_audience import MkaCourseAudience
from src.db.mka_identity import MkaManagedGroup
from src.db.mka_user_attributes import MkaUserAttributes
from src.db.trail_runs import TrailRun
from src.db.usergroup_resources import UserGroupResource
from src.db.usergroup_user import UserGroupUser
from src.db.usergroups import UserGroup
from src.services.mka import course_audience as ca
from src.tests.routers.mka_compliance_world import add_attributes, add_user

NOW = str(datetime.now())

MAAL_LOCAL = dict(level="local", department="maal", role="nazim_dept", majlis="Albany", region="Northeast")
MAAL_NATIONAL = dict(level="national", department="maal", role="mohtamim")
TABLIGH_LOCAL = dict(level="local", department="tabligh", role="nazim_dept", majlis="Albany", region="Northeast")
QAID_LOCAL = dict(level="local", role="qaid", majlis="Houston", region="Gulf")

PEOPLE = {  # uid: (email, effective)
    10: ("maal.local@example.invalid", MAAL_LOCAL),
    11: ("maal.national@example.invalid", MAAL_NATIONAL),
    12: ("tabligh.local@example.invalid", TABLIGH_LOCAL),
    13: ("qaid@example.invalid", QAID_LOCAL),
    14: ("member@example.invalid", dict(status="not_applicable", is_officeholder=False)),
}


@pytest.fixture(autouse=True)
def flag_on(monkeypatch):
    monkeypatch.setenv("MKA_COURSE_AUDIENCE_ENABLED", "true")
    monkeypatch.setenv("MKA_IDENTITY_SYNC_ENABLED", "true")
    monkeypatch.setenv("MKA_IDENTITY_SYNC_ORG_IDS", "1")


@pytest.fixture
async def world(db, org, other_org):
    for uid, (email, eff) in PEOPLE.items():
        await add_user(db, org.id, uid, email)
        await add_attributes(db, uid, email, **eff)
    await add_user(db, org.id, 15, "unproven@example.invalid")
    await add_attributes(db, 15, "unproven@example.invalid", **MAAL_LOCAL)
    row = await db.get(MkaUserAttributes, 15)
    row.verified_hd = None
    db.add(row)
    await add_user(db, org.id, 16, "stale@example.invalid")
    await add_attributes(db, 16, "stale@example.invalid", stale=True, **MAAL_LOCAL)
    await add_user(db, other_org.id, 20, "o2.maal@example.invalid")
    await add_attributes(db, 20, "o2.maal@example.invalid", **MAAL_LOCAL)
    await db.commit()


async def make_course(db, org_id=1, cid=1, published=True, public=True):
    c = Course(id=cid, name=f"Course {cid}", description="d", public=public, published=published, open_to_contributors=False,
               org_id=org_id, course_uuid=f"course_{cid}", creation_date=NOW, update_date=NOW)
    db.add(c)
    await db.commit()
    return c


async def settle():
    while ca._PENDING:
        await asyncio.gather(*list(ca._PENDING))


async def member_ids(db, course):
    return await _ids(db, course, UserGroupUser.user_id)


async def _ids(db, course, col):
    g = await ca._managed_group(db, course.org_id, course.course_uuid)
    if g is None:
        return None
    return set((await db.execute(select(col).where(UserGroupUser.usergroup_id == g.id))).scalars().all())


async def enrolled(db, course):
    return set((await db.execute(select(TrailRun.user_id).where(TrailRun.course_id == course.id))).scalars().all())


# --- matching --------------------------------------------------------------------------------------------------


async def test_officeholders_matches_proven_office_holders_only(db, world):
    c = await make_course(db)
    res = await ca.apply(db, c, "officeholders", "optin", None, 1)
    assert await member_ids(db, c) == {10, 11, 12, 13}  # not the plain member, not unproven (15), not stale (16), not org 2
    assert res["matched_count"] == 4 and res["enrolled"] == 0


async def test_custom_department_matches_all_levels(db, world):
    c = await make_course(db)
    await ca.apply(db, c, "custom", "optin", ca.normalize_custom("custom", {"departments": ["maal"]}), 1)
    assert await member_ids(db, c) == {10, 11}


async def test_custom_and_across_fields_or_within(db, world):
    c = await make_course(db)
    await ca.apply(db, c, "custom", "optin", ca.normalize_custom("custom", {"departments": ["maal"], "levels": ["local"]}), 1)
    assert await member_ids(db, c) == {10}
    await ca.apply(db, c, "custom", "optin", ca.normalize_custom("custom", {"departments": ["maal", "tabligh"], "levels": ["local"]}), 1)
    assert await member_ids(db, c) == {10, 12}
    await ca.apply(db, c, "custom", "optin", ca.normalize_custom("custom", {"roles": ["qaid", "mohtamim"]}), 1)
    assert await member_ids(db, c) == {11, 13}


def test_custom_validation():
    with pytest.raises(ValueError):
        ca.normalize_custom("custom", {})
    with pytest.raises(ValueError):
        ca.normalize_custom("custom", {"departments": ["nope"]})
    assert ca.normalize_custom("officeholders", {"departments": ["maal"]}) is None


# --- access wiring ---------------------------------------------------------------------------------------------


async def test_group_is_linked_and_course_becomes_non_public(db, world):
    c = await make_course(db, public=True)
    await ca.apply(db, c, "officeholders", "optin", None, 1)
    await db.refresh(c)
    g = await ca._managed_group(db, 1, c.course_uuid)
    assert g is not None and g.name == "Course: Course 1" and g.description == "Managed by MKA course audience"
    assert c.public is False
    link = (await db.execute(select(UserGroupResource).where(UserGroupResource.resource_uuid == c.course_uuid))).scalars().all()
    assert [x.usergroup_id for x in link] == [g.id]
    row = await db.get(MkaCourseAudience, c.id)
    assert row.usergroup_id == g.id and row.updated_by == 1


async def test_everyone_has_no_group_and_is_not_public(db, world):
    c = await make_course(db)
    await ca.apply(db, c, "officeholders", "optin", None, 1)
    res = await ca.apply(db, c, "everyone", "optin", None, 1)
    await db.refresh(c)
    assert c.public is False
    assert await ca._managed_group(db, 1, c.course_uuid) is None
    assert (await db.execute(select(UserGroupResource))).scalars().all() == []
    assert res["memberships_removed"] == 4
    assert (await db.get(MkaCourseAudience, c.id)).usergroup_id is None


async def test_manual_usergroups_untouched(db, world):
    c = await make_course(db)
    manual = UserGroup(name="Manual", description="by hand", org_id=1, usergroup_uuid="usergroup_manual", creation_date=NOW, update_date=NOW)
    db.add(manual)
    await db.commit()
    db.add(UserGroupResource(usergroup_id=manual.id, resource_uuid=c.course_uuid, org_id=1, creation_date=NOW, update_date=NOW))
    db.add(UserGroupUser(usergroup_id=manual.id, user_id=14, org_id=1, creation_date=NOW, update_date=NOW))
    await db.commit()
    await ca.apply(db, c, "officeholders", "optin", None, 1)
    await ca.apply(db, c, "everyone", "optin", None, 1)
    await ca.remove(db, c)
    assert (await db.get(UserGroup, manual.id)) is not None
    assert len((await db.execute(select(UserGroupResource).where(UserGroupResource.usergroup_id == manual.id))).scalars().all()) == 1
    assert len((await db.execute(select(UserGroupUser).where(UserGroupUser.usergroup_id == manual.id))).scalars().all()) == 1


async def test_switching_audience_moves_membership_but_never_unenrols(db, world):
    c = await make_course(db)
    await ca.apply(db, c, "custom", "required", ca.normalize_custom("custom", {"departments": ["maal"]}), 1)
    assert await enrolled(db, c) == {10, 11}
    res = await ca.apply(db, c, "custom", "required", ca.normalize_custom("custom", {"departments": ["tabligh"]}), 1)
    assert await member_ids(db, c) == {12}
    assert res["memberships_added"] == 1 and res["memberships_removed"] == 2
    assert await enrolled(db, c) == {10, 11, 12}  # nobody unenrolled


async def test_delete_removes_row_and_group_keeps_enrolments(db, world):
    c = await make_course(db)
    await ca.apply(db, c, "officeholders", "required", None, 1)
    res = await ca.remove(db, c)
    assert res["removed"] is True
    assert await db.get(MkaCourseAudience, c.id) is None
    assert await ca._managed_group(db, 1, c.course_uuid) is None
    assert (await db.execute(select(MkaManagedGroup))).scalars().all() == []
    assert await enrolled(db, c) == {10, 11, 12, 13}
    assert (await db.get(Course, c.id)).public is False


# --- enrolment -------------------------------------------------------------------------------------------------


async def test_required_enrols_immediately_and_idempotently(db, world):
    c = await make_course(db)
    res = await ca.apply(db, c, "custom", "required", ca.normalize_custom("custom", {"departments": ["maal"]}), 1)
    assert res["enrolled"] == 2 and await enrolled(db, c) == {10, 11}
    again = await ca.apply(db, c, "custom", "required", ca.normalize_custom("custom", {"departments": ["maal"]}), 1)
    assert again["enrolled"] == 0 and again["memberships_added"] == 0
    assert len((await db.execute(select(TrailRun).where(TrailRun.course_id == c.id))).scalars().all()) == 2


async def test_optin_never_enrols(db, world):
    c = await make_course(db)
    await ca.apply(db, c, "officeholders", "optin", None, 1)
    assert await enrolled(db, c) == set()


async def test_everyone_required_enrols_all_org_members(db, world):
    c = await make_course(db)
    res = await ca.apply(db, c, "everyone", "required", None, 1)
    assert await enrolled(db, c) == {10, 11, 12, 13, 14, 15, 16}  # every org-1 member, nobody from org 2
    assert res["matched_count"] == 7


async def test_unpublished_not_enrolled_until_published(db, world):
    c = await make_course(db, published=False)
    res = await ca.apply(db, c, "officeholders", "required", None, 1)
    assert res["enrolled"] == 0 and await enrolled(db, c) == set()
    assert await member_ids(db, c) == {10, 11, 12, 13}  # access is wired already (authors see drafts)
    c.published = True
    db.add(c)
    await db.commit()
    await settle()
    assert await enrolled(db, c) == {10, 11, 12, 13}


async def test_publish_without_audience_or_optin_enrols_nobody(db, world):
    c1 = await make_course(db, cid=1, published=False)
    c2 = await make_course(db, cid=2, published=False)
    await ca.apply(db, c2, "officeholders", "optin", None, 1)
    for c in (c1, c2):
        c.published = True
        db.add(c)
    await db.commit()
    await settle()
    assert await enrolled(db, c1) == set() and await enrolled(db, c2) == set()


# --- flag + hooks ----------------------------------------------------------------------------------------------


async def test_flag_off_hooks_write_nothing(db, world, monkeypatch):
    c = await make_course(db, published=False)
    await ca.apply(db, c, "officeholders", "required", None, 1)
    monkeypatch.setenv("MKA_COURSE_AUDIENCE_ENABLED", "false")
    await add_user(db, 1, 30, "new.maal@example.invalid")
    await add_attributes(db, 30, "new.maal@example.invalid", **MAAL_LOCAL)
    before = (len((await db.execute(select(UserGroupUser))).scalars().all()), len((await db.execute(select(TrailRun))).scalars().all()))
    await ca.sync_user(db, 30, [1])
    assert await ca.reconcile_course(db, c.id) is None
    c.published = True
    db.add(c)
    await db.commit()
    await settle()
    after = (len((await db.execute(select(UserGroupUser))).scalars().all()), len((await db.execute(select(TrailRun))).scalars().all()))
    assert before == after


async def test_sign_in_sync_adds_new_matches_and_enrols(db, world, org):
    c = await make_course(db)
    await ca.apply(db, c, "custom", "required", ca.normalize_custom("custom", {"departments": ["maal"]}), 1)
    await add_user(db, 1, 30, "new.maal@example.invalid")
    await add_attributes(db, 30, "new.maal@example.invalid", **MAAL_LOCAL)
    await ca.sync_user(db, 30, [1])
    assert 30 in await member_ids(db, c) and 30 in await enrolled(db, c)
    await ca.sync_user(db, 30, [1])  # idempotent
    assert len((await db.execute(select(TrailRun).where(TrailRun.user_id == 30))).scalars().all()) == 1


async def test_sync_user_removes_membership_when_no_longer_matching_but_keeps_run(db, world):
    c = await make_course(db)
    await ca.apply(db, c, "custom", "required", ca.normalize_custom("custom", {"departments": ["maal"]}), 1)
    row = await db.get(MkaUserAttributes, 10)
    row.effective = {**row.effective, "department": "tabligh"}
    row.eff_department = "tabligh"
    db.add(row)
    await db.commit()
    await ca.sync_user(db, 10, [1])
    assert 10 not in await member_ids(db, c)
    assert 10 in await enrolled(db, c)


async def test_identity_run_calls_course_sync(db, engine, world):
    """identity_sync._run (sign-in / profile save) re-syncs course audiences for the user."""
    from types import SimpleNamespace

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from src.services.mka import identity_sync

    c = await make_course(db)
    await ca.apply(db, c, "custom", "required", ca.normalize_custom("custom", {"departments": ["maal"]}), 1)
    await add_user(db, 1, 31, "late.maal@example.invalid")
    await add_attributes(db, 31, "late.maal@example.invalid", **MAAL_LOCAL)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await identity_sync.identity_sync_user(factory, SimpleNamespace(id=31, email="late.maal@example.invalid"))
    assert 31 in await enrolled(db, c)


# --- review fixes ------------------------------------------------------------------------------------------------


async def test_large_enrolment_is_queued_to_background(db, world, monkeypatch):
    monkeypatch.setattr(ca, "INLINE_ENROLL_MAX", 2)
    c = await make_course(db)
    res = await ca.apply(db, c, "officeholders", "required", None, 1)
    assert res["enrolled"] == 0 and res["enroll_queued"] == 4
    while ca._BG:
        await asyncio.gather(*list(ca._BG))
    assert await enrolled(db, c) == {10, 11, 12, 13}


async def test_chunked_enrolment_inline(db, world, monkeypatch):
    monkeypatch.setattr(ca, "ENROLL_CHUNK", 2)
    c = await make_course(db)
    res = await ca.apply(db, c, "everyone", "required", None, 1)
    assert res["enrolled"] == 7 and res["enroll_failed"] == 0
    assert len((await db.execute(select(TrailRun).where(TrailRun.course_id == c.id))).scalars().all()) == 7


async def test_enrol_failure_does_not_abort_batch_or_expire_course(db, world, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("chunk down")

    real = ca._enrol_org

    async def flaky(d, uid, plan):
        if uid == 11:
            raise RuntimeError("bad account")
        return await real(d, uid, plan)

    monkeypatch.setattr(ca, "_enrol_chunk", boom)
    monkeypatch.setattr(ca, "_enrol_org", flaky)
    c = await make_course(db)
    cid = c.id
    res = await ca.apply(db, c, "officeholders", "required", None, 1)
    assert res["enroll_failed"] == 1 and res["enrolled"] == 3
    got = set((await db.execute(select(TrailRun.user_id).where(TrailRun.course_id == cid))).scalars().all())
    assert got == {10, 12, 13}


async def test_sync_user_repairs_public_drift(db, world):
    c = await make_course(db)
    await ca.apply(db, c, "officeholders", "optin", None, 1)
    c.public = True
    db.add(c)
    await db.commit()
    await ca.sync_user(db, 10, [1])
    assert (await db.get(Course, c.id, populate_existing=True)).public is False


async def test_manual_group_count(db, world):
    c = await make_course(db)
    manual = UserGroup(name="Manual", description="x", org_id=1, usergroup_uuid="usergroup_m", creation_date=NOW, update_date=NOW)
    db.add(manual)
    await db.commit()
    db.add(UserGroupResource(usergroup_id=manual.id, resource_uuid=c.course_uuid, org_id=1, creation_date=NOW, update_date=NOW))
    await db.commit()
    await ca.apply(db, c, "officeholders", "optin", None, 1)
    assert (await ca.get(db, c))["manual_group_count"] == 1
