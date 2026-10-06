"""AMC ID is admin-managed once set: members may set it first time, never change/clear it."""

from datetime import datetime

import pytest
from fastapi import HTTPException

from src.db.users import User
from src.routers import mka_profile as r
from src.services.users.mka_profile import MkaProfileIn, profile_status, upsert_profile


async def _mk_user(db, n):
    u = User(
        username=f"amc{n}", first_name="U", last_name=str(n), email=f"amc{n}@test.com",
        password="x", user_uuid=f"user_amc{n}",
        creation_date=str(datetime.now()), update_date=str(datetime.now()),
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


@pytest.mark.asyncio
async def test_self_cannot_change_stored_amc(db):
    u = await _mk_user(db, 1)
    await upsert_profile(db, u.id, MkaProfileIn(majlis="Zion", amc_id="111"))
    await upsert_profile(db, u.id, MkaProfileIn(majlis="Seattle", amc_id="222"), actor="self")
    s = await profile_status(db, u.id)
    assert (s["amc_id"], s["majlis"]) == ("111", "Seattle")


@pytest.mark.asyncio
async def test_self_cannot_clear_stored_amc(db):
    u = await _mk_user(db, 1)
    await upsert_profile(db, u.id, MkaProfileIn(majlis="Zion", amc_id="111"))
    await upsert_profile(db, u.id, MkaProfileIn(majlis="Zion", amc_id=None), actor="self")
    assert (await profile_status(db, u.id))["amc_id"] == "111"


@pytest.mark.asyncio
async def test_self_can_set_amc_when_none_stored(db):
    u = await _mk_user(db, 1)
    await upsert_profile(db, u.id, MkaProfileIn(majlis="Zion"), actor="self")
    await upsert_profile(db, u.id, MkaProfileIn(majlis="Zion", amc_id="333"), actor="self")
    assert (await profile_status(db, u.id))["amc_id"] == "333"


@pytest.mark.asyncio
async def test_admin_can_change_and_clear_amc(db):
    u = await _mk_user(db, 1)
    await upsert_profile(db, u.id, MkaProfileIn(majlis="Zion", amc_id="111"))
    await upsert_profile(db, u.id, MkaProfileIn(majlis="Zion", amc_id="222"), actor="admin")
    assert (await profile_status(db, u.id))["amc_id"] == "222"
    await upsert_profile(db, u.id, MkaProfileIn(majlis="Zion"), actor="admin")
    assert (await profile_status(db, u.id))["amc_id"] is None


@pytest.mark.asyncio
async def test_admin_amc_conflict_is_409(db):
    a, b = await _mk_user(db, 1), await _mk_user(db, 2)
    await upsert_profile(db, a.id, MkaProfileIn(majlis="Zion", amc_id="111"), actor="admin")
    await upsert_profile(db, b.id, MkaProfileIn(majlis="Zion", amc_id="222"), actor="admin")
    with pytest.raises(HTTPException) as e:
        await upsert_profile(db, b.id, MkaProfileIn(majlis="Zion", amc_id="111"), actor="admin")
    assert e.value.status_code == 409
    assert (await profile_status(db, b.id))["amc_id"] == "222"


@pytest.mark.asyncio
async def test_self_first_time_taken_amc_is_409(db):
    a, b = await _mk_user(db, 1), await _mk_user(db, 2)
    await upsert_profile(db, a.id, MkaProfileIn(majlis="Zion", amc_id="111"))
    with pytest.raises(HTTPException) as e:
        await upsert_profile(db, b.id, MkaProfileIn(majlis="Zion", amc_id="111"), actor="self")
    assert e.value.status_code == 409


@pytest.mark.asyncio
async def test_put_me_keeps_stored_amc_but_admin_put_can_change(db, org, admin_user, regular_user):
    await r.api_put_me(
        body=MkaProfileIn(majlis="Zion", amc_id="111"), current_user=regular_user, db_session=db
    )
    out = await r.api_put_me(
        body=MkaProfileIn(majlis="Zion", amc_id="222"), current_user=regular_user, db_session=db
    )
    assert out["amc_id"] == "111"
    out = await r.api_put_user(
        user_id=regular_user.id, org_id=org.id, body=MkaProfileIn(majlis="Zion", amc_id="222"),
        current_user=admin_user, db_session=db,
    )
    assert out["amc_id"] == "222"
