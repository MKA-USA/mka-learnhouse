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
    user = (await db.execute(select(User).where(User.id == created.id))).scalars().first()
    assert user is not None
    rows = (await db.execute(select(MkaUserProfile).where(MkaUserProfile.user_id == created.id))).scalars().all()
    assert rows == []
    assert await profile_status(db, created.id) == {"complete": False}


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
