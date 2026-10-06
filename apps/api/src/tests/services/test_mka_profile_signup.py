from contextlib import ExitStack
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import HTTPException
from sqlmodel import select

from src.db.mka_user_profile import MkaUserProfile
from src.db.users import User, UserCreate
from src.services.users.mka_profile import profile_status
from src.services.users.users import create_user, create_user_without_org


def _signup_patches():
    stack = ExitStack()
    for target, kwargs in [
        ("src.services.users.users.validate_password_complexity", {"return_value": Mock(is_valid=True)}),
        ("src.services.users.users.check_limits_with_usage", {}),
        ("src.services.users.users.increase_feature_usage", {}),
        ("src.services.users.users.track", {"new_callable": AsyncMock}),
        ("src.services.users.users.dispatch_webhooks", {"new_callable": AsyncMock}),
        ("src.services.users.users.send_account_creation_email", {}),
        ("src.services.users.email_verification.send_verification_email", {"new_callable": AsyncMock}),
        ("src.services.users.users.get_deployment_mode", {"return_value": "oss"}),
        ("src.services.users.users.authorization_verify_based_on_roles_and_authorship", {"new_callable": AsyncMock}),
    ]:
        stack.enter_context(patch(target, **kwargs))
    return stack


def _body(name, **extra):
    return UserCreate(
        username=name, first_name="F", last_name="L",
        email=f"{name}@test.com", password="Passw0rd!x", **extra,
    )


async def _user_count(db):
    return len((await db.execute(select(User))).scalars().all())


@pytest.mark.asyncio
async def test_email_signup_stores_profile_and_derives_region(mock_request, db, admin_user, org):
    with _signup_patches():
        created = await create_user(
            mock_request, db, admin_user,
            _body("p1", mka_profile={"majlis": "Baltimore", "region": "Midwest", "amc_id": "42"}),
            org.id,
        )
    s = await profile_status(db, created.id)
    assert (s["majlis"], s["region"], s["amc_id"]) == ("Baltimore", "East", "42")


@pytest.mark.asyncio
async def test_email_signup_without_majlis_is_422_and_creates_no_user(mock_request, db, admin_user, org):
    before = await _user_count(db)
    with _signup_patches(), pytest.raises(HTTPException) as e:
        await create_user(mock_request, db, admin_user, _body("p2"), org.id)
    assert e.value.status_code == 422
    assert await _user_count(db) == before


@pytest.mark.asyncio
async def test_duplicate_amc_at_signup_is_409_and_creates_no_user(mock_request, db, admin_user, org):
    with _signup_patches():
        await create_user(mock_request, db, admin_user,
                          _body("p3", mka_profile={"majlis": "Zion", "amc_id": "5"}), org.id)
    before = await _user_count(db)
    with _signup_patches(), pytest.raises(HTTPException) as e:
        await create_user(mock_request, db, admin_user,
                          _body("p4", mka_profile={"majlis": "Zion", "amc_id": "5"}), org.id)
    assert e.value.status_code == 409
    assert await _user_count(db) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("fn", ["create_user", "create_user_without_org"])
async def test_forbidden_signup_403_wins_over_amc_409_and_precheck_not_reached(
    fn, mock_request, db, admin_user, org
):
    # An org that disallows signup must not leak "AMC ID already registered".
    await upsert_taken_amc(db)
    forbidden = HTTPException(status_code=403, detail="nope")
    with _signup_patches(), \
            patch("src.services.users.users.rbac_check", AsyncMock(side_effect=forbidden)), \
            patch("src.services.users.users.validate_signup_profile", AsyncMock()) as v:
        args = (mock_request, db, admin_user, _body("p9", mka_profile={"majlis": "Zion", "amc_id": "9"}))
        with pytest.raises(HTTPException) as e:
            if fn == "create_user":
                await create_user(*args, org.id)
            else:
                await create_user_without_org(*args)
    assert e.value.status_code == 403
    v.assert_not_called()


async def upsert_taken_amc(db):
    from src.services.users.mka_profile import MkaProfileIn, upsert_profile

    holder = User(
        username="holder9", first_name="H", last_name="L", email="holder9@test.com",
        password="x", user_uuid="user_holder9",
        creation_date="2026-01-01", update_date="2026-01-01",
    )
    db.add(holder)
    await db.commit()
    await db.refresh(holder)
    await upsert_profile(db, holder.id, MkaProfileIn(majlis="Zion", amc_id="9"))


@pytest.mark.asyncio
async def test_oauth_signup_without_profile_succeeds_and_is_incomplete(mock_request, db, admin_user, org):
    with _signup_patches():
        created = await create_user(
            mock_request, db, admin_user, _body("g1"), org.id,
            is_oauth=True, signup_provider="google",
        )
    assert await profile_status(db, created.id) == {"complete": False}


@pytest.mark.asyncio
async def test_unknown_keys_in_mka_profile_are_not_stored(mock_request, db, admin_user, org):
    with _signup_patches():
        created = await create_user(
            mock_request, db, admin_user,
            _body("p5", mka_profile={"majlis": "Zion", "extra_metadata": {"x": 1}, "is_superadmin": True}),
            org.id,
        )
    user = (await db.execute(select(User).where(User.id == created.id))).scalars().first()
    assert user.is_superadmin is False
    assert not user.extra_metadata  # None or {} — never the submitted blob


@pytest.mark.asyncio
async def test_org_less_signup_requires_and_stores_profile(mock_request, db, admin_user):
    with _signup_patches():
        with pytest.raises(HTTPException) as e:
            await create_user_without_org(mock_request, db, admin_user, _body("o1"))
        assert e.value.status_code == 422
        created = await create_user_without_org(
            mock_request, db, admin_user, _body("o2", mka_profile={"majlis": "Zion"}),
        )
    assert (await profile_status(db, created.id))["region"] == "Midwest"


@pytest.mark.asyncio
async def test_amc_race_after_user_commit_does_not_fail_signup(mock_request, db, admin_user, org):
    """Profile write 409s after the user row is committed: account stays, no error escapes."""
    real = HTTPException(status_code=409, detail="That AMC ID is already registered")
    with _signup_patches(), patch(
        "src.services.users.mka_profile.upsert_profile", new=AsyncMock(side_effect=real)
    ):
        created = await create_user(
            mock_request, db, admin_user,
            _body("r1", mka_profile={"majlis": "Zion", "amc_id": "77"}), org.id,
        )
    from src.db.user_organizations import UserOrganization

    uid = created.id
    user = (await db.execute(select(User).where(User.id == uid))).scalars().first()
    assert user is not None
    link = (await db.execute(
        select(UserOrganization).where(
            UserOrganization.user_id == uid, UserOrganization.org_id == org.id
        )
    )).scalars().first()
    assert link is not None
    rows = (await db.execute(select(MkaUserProfile).where(MkaUserProfile.user_id == uid))).scalars().all()
    assert rows == []
    assert await profile_status(db, uid) == {"complete": False}


async def _seed_amc_holder(db, amc_id):
    """A different, already-registered user who owns `amc_id`."""
    from datetime import datetime

    from src.services.users.mka_profile import MkaProfileIn, upsert_profile

    holder = User(
        username="holder", first_name="H", last_name="O", email="holder@test.com",
        password="x", user_uuid="user_holder",
        creation_date=str(datetime.now()), update_date=str(datetime.now()),
    )
    db.add(holder)
    await db.commit()
    await db.refresh(holder)
    await upsert_profile(db, holder.id, MkaProfileIn(majlis="Zion", amc_id=amc_id))


def _blind_to_conflict_until_commit(monkeypatch):
    """Simulate a real AMC race.

    `_amc_taken` is consulted 3 times on a signup that loses the race:
      1. validate_signup_profile (before the user row exists)
      2. the pre-check inside upsert_profile
      3. the re-check after the IntegrityError rollback
    Calls 1-2 must NOT see the conflict (the other signup "hasn't committed yet"),
    so the DB unique index is what rejects the insert (real IntegrityError and a
    real rollback()). Call 3 and later report the truth.
    """
    from src.services.users import mka_profile as mp

    real = mp._amc_taken
    calls = {"n": 0}

    async def stub(db_session, amc_id, exclude_user_id):
        calls["n"] += 1
        if calls["n"] <= 2:
            return False
        return await real(db_session, amc_id, exclude_user_id)

    monkeypatch.setattr(mp, "_amc_taken", stub)


@pytest.mark.asyncio
async def test_real_amc_race_after_user_commit_keeps_account_and_org_link(
    mock_request, db, admin_user, org, monkeypatch
):
    from src.db.user_organizations import UserOrganization

    org_id = org.id  # the rollback expires fixture instances too; keep a plain id
    await _seed_amc_holder(db, "7777")
    _blind_to_conflict_until_commit(monkeypatch)
    with _signup_patches():
        created = await create_user(
            mock_request, db, admin_user,
            _body("r4", mka_profile={"majlis": "Zion", "amc_id": "7777"}), org_id,
        )
    assert created.email == "r4@test.com"
    assert created.user_uuid
    uid = created.id
    user = (await db.execute(select(User).where(User.id == uid))).scalars().first()
    assert user is not None and user.email == "r4@test.com"
    link = (await db.execute(
        select(UserOrganization).where(
            UserOrganization.user_id == uid, UserOrganization.org_id == org_id
        )
    )).scalars().first()
    assert link is not None
    rows = (await db.execute(select(MkaUserProfile).where(MkaUserProfile.user_id == uid))).scalars().all()
    assert rows == []
    assert await profile_status(db, uid) == {"complete": False}


@pytest.mark.asyncio
async def test_real_amc_race_without_org_keeps_account(mock_request, db, admin_user, monkeypatch):
    await _seed_amc_holder(db, "7778")
    _blind_to_conflict_until_commit(monkeypatch)
    with _signup_patches():
        created = await create_user_without_org(
            mock_request, db, admin_user,
            _body("r5", mka_profile={"majlis": "Zion", "amc_id": "7778"}),
        )
    assert created.email == "r5@test.com"
    uid = created.id
    rows = (await db.execute(select(MkaUserProfile).where(MkaUserProfile.user_id == uid))).scalars().all()
    assert rows == []
    assert await profile_status(db, uid) == {"complete": False}


@pytest.mark.asyncio
async def test_non_409_error_saving_profile_still_propagates(mock_request, db, admin_user, org):
    with _signup_patches(), patch(
        "src.services.users.mka_profile.upsert_profile",
        new=AsyncMock(side_effect=HTTPException(status_code=500, detail="boom")),
    ), pytest.raises(HTTPException) as e:
        await create_user(
            mock_request, db, admin_user, _body("r2", mka_profile={"majlis": "Zion"}), org.id,
        )
    assert e.value.status_code == 500
