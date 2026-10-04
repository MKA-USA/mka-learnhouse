import pytest
from fastapi import HTTPException
from sqlmodel import select

from src.db.mka_user_profile import MkaUserProfile
from src.db.users import User
from src.services.users.mka_profile import (
    MkaProfileIn,
    get_profile,
    profile_status,
    save_signup_profile,
    upsert_profile,
    validate_signup_profile,
)


async def _mk_user(db, n):
    from datetime import datetime
    u = User(
        username=f"u{n}", first_name="U", last_name=str(n), email=f"u{n}@test.com",
        password="x", user_uuid=f"user_u{n}",
        creation_date=str(datetime.now()), update_date=str(datetime.now()),
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


@pytest.mark.asyncio
async def test_status_incomplete_without_row(db):
    u = await _mk_user(db, 1)
    assert await profile_status(db, u.id) == {"complete": False}


@pytest.mark.asyncio
async def test_upsert_derives_region_and_round_trips(db):
    u = await _mk_user(db, 1)
    await upsert_profile(
        db, u.id,
        MkaProfileIn(majlis="Baltimore", mobile="(703) 234-0142", amc_id="00123", tanzeem="tifl"),
    )
    s = await profile_status(db, u.id)
    assert s == {
        "complete": True, "majlis": "Baltimore", "region": "East",
        "mobile": "+17032340142", "amc_id": "00123", "tanzeem": "tifl",
    }


@pytest.mark.asyncio
async def test_upsert_updates_and_rederives_region(db):
    u = await _mk_user(db, 1)
    await upsert_profile(db, u.id, MkaProfileIn(majlis="Baltimore"))
    await upsert_profile(db, u.id, MkaProfileIn(majlis="Zion"))
    s = await profile_status(db, u.id)
    assert (s["majlis"], s["region"]) == ("Zion", "Midwest")
    rows = (await db.execute(select(MkaUserProfile))).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_duplicate_amc_is_409(db):
    a, b = await _mk_user(db, 1), await _mk_user(db, 2)
    await upsert_profile(db, a.id, MkaProfileIn(majlis="Zion", amc_id="777"))
    with pytest.raises(HTTPException) as e:
        await upsert_profile(db, b.id, MkaProfileIn(majlis="Zion", amc_id="777"))
    assert e.value.status_code == 409
    assert await get_profile(db, b.id) is None


@pytest.mark.asyncio
async def test_same_user_can_resave_own_amc(db):
    a = await _mk_user(db, 1)
    await upsert_profile(db, a.id, MkaProfileIn(majlis="Zion", amc_id="777"))
    await upsert_profile(db, a.id, MkaProfileIn(majlis="Zion", amc_id="777", tanzeem="khadim"))
    assert (await profile_status(db, a.id))["tanzeem"] == "khadim"


@pytest.mark.asyncio
async def test_two_null_amc_ids_do_not_collide(db):
    a, b = await _mk_user(db, 1), await _mk_user(db, 2)
    await upsert_profile(db, a.id, MkaProfileIn(majlis="Zion"))
    await upsert_profile(db, b.id, MkaProfileIn(majlis="Zion"))
    assert (await profile_status(db, a.id))["complete"] and (await profile_status(db, b.id))["complete"]


@pytest.mark.asyncio
async def test_validate_signup_profile_rules(db):
    # non-oauth requires majlis
    with pytest.raises(HTTPException) as e:
        await validate_signup_profile(db, None, is_oauth=False)
    assert e.value.status_code == 422
    # oauth may omit it
    assert await validate_signup_profile(db, None, is_oauth=True) is None
    # valid
    p = await validate_signup_profile(db, {"majlis": "Zion", "region": "East"}, is_oauth=False)
    assert p.majlis == "Zion"


@pytest.mark.asyncio
async def test_validate_signup_profile_precheck_conflict(db):
    a = await _mk_user(db, 1)
    await upsert_profile(db, a.id, MkaProfileIn(majlis="Zion", amc_id="9"))
    with pytest.raises(HTTPException) as e:
        await validate_signup_profile(db, {"majlis": "Zion", "amc_id": "9"}, is_oauth=False)
    assert e.value.status_code == 409


@pytest.mark.asyncio
async def test_save_signup_profile_none_is_noop(db):
    u = await _mk_user(db, 1)
    await save_signup_profile(db, u.id, None)
    assert await get_profile(db, u.id) is None


@pytest.mark.asyncio
async def test_integrity_error_is_409_when_amc_really_taken(db, monkeypatch):
    from src.services.users import mka_profile as mp

    u1, u2 = await _mk_user(db, 91), await _mk_user(db, 92)
    id1, id2 = u1.id, u2.id  # rollback expires ORM instances; keep plain ids
    await upsert_profile(db, id1, MkaProfileIn(majlis="Zion", amc_id="9001"))
    real = mp._amc_taken
    calls = {"n": 0}

    async def fake(db_session, amc_id, exclude_user_id):
        calls["n"] += 1
        if calls["n"] == 1:  # pre-check misses (simulated race)
            return False
        return await real(db_session, amc_id, exclude_user_id)

    monkeypatch.setattr(mp, "_amc_taken", fake)
    with pytest.raises(HTTPException) as e:
        await upsert_profile(db, id2, MkaProfileIn(majlis="Zion", amc_id="9001"))
    assert e.value.status_code == 409
    assert (await get_profile(db, id1)).amc_id == "9001"  # session still usable
    assert await get_profile(db, id2) is None


@pytest.mark.asyncio
async def test_integrity_error_not_caused_by_amc_is_reraised(db, monkeypatch):
    from sqlalchemy.exc import IntegrityError
    from src.services.users import mka_profile as mp

    u = await _mk_user(db, 93)

    async def never_taken(*a, **k):
        return False

    async def boom():
        raise IntegrityError("stmt", {}, Exception("other constraint"))

    monkeypatch.setattr(mp, "_amc_taken", never_taken)
    monkeypatch.setattr(db, "commit", boom)
    with pytest.raises(IntegrityError):
        await upsert_profile(db, u.id, MkaProfileIn(majlis="Zion", amc_id="9002"))
