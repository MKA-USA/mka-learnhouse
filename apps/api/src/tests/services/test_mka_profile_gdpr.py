"""MKA fork: GDPR anonymize/export cover the Majlis profile."""

from unittest.mock import AsyncMock, patch

import pytest
from sqlmodel import select

from src.db.mka_user_profile import MkaUserProfile
from src.services.admin.admin import anonymize_user, export_user_data
from src.services.users.mka_profile import MkaProfileIn, profile_status, upsert_profile
from src.tests.services.test_admin_service_extra import (
    _add_user_to_org,
    _create_user,
    _make_token_user,
)


async def _count(db, user_id):
    rows = (
        await db.execute(select(MkaUserProfile).where(MkaUserProfile.user_id == user_id))
    ).scalars().all()
    return len(rows)


@pytest.mark.asyncio
async def test_anonymize_deletes_profile_and_frees_amc_id(db, org, user_role):
    token_user = _make_token_user(org.id)
    victim = await _create_user(db, user_id=201, username="gd201", email="gd201@test.com")
    other = await _create_user(db, user_id=202, username="gd202", email="gd202@test.com")
    await _add_user_to_org(db, victim, org, role_id=user_role.id)
    victim_id, other_id = victim.id, other.id
    await upsert_profile(
        db, victim_id,
        MkaProfileIn(majlis="Zion", mobile="7032340142", amc_id="4242", tanzeem="tifl"),
    )
    assert await _count(db, victim_id) == 1

    with patch("src.services.admin.admin.dispatch_webhooks", new_callable=AsyncMock):
        await anonymize_user(token_user, victim_id, db)

    assert await _count(db, victim_id) == 0
    # the former AMC ID is reusable by someone else
    await upsert_profile(db, other_id, MkaProfileIn(majlis="Seattle", amc_id="4242"))
    assert (await profile_status(db, other_id))["amc_id"] == "4242"


@pytest.mark.asyncio
async def test_anonymize_without_profile_still_works(db, org, user_role):
    token_user = _make_token_user(org.id)
    u = await _create_user(db, user_id=203, username="gd203", email="gd203@test.com")
    await _add_user_to_org(db, u, org, role_id=user_role.id)
    with patch("src.services.admin.admin.dispatch_webhooks", new_callable=AsyncMock):
        result = await anonymize_user(token_user, u.id, db)
    assert "anonymized" in result["detail"].lower()


@pytest.mark.asyncio
async def test_export_includes_profile(db, org, user_role):
    token_user = _make_token_user(org.id)
    u = await _create_user(db, user_id=204, username="gd204", email="gd204@test.com")
    await _add_user_to_org(db, u, org, role_id=user_role.id)
    await upsert_profile(db, u.id, MkaProfileIn(majlis="Zion", mobile="7032340142", amc_id="55"))
    data = await export_user_data(token_user, u.id, db)
    assert data["mka_profile"]["majlis"] == "Zion"
    assert data["mka_profile"]["mobile"] == "+17032340142"
    assert data["mka_profile"]["amc_id"] == "55"


@pytest.mark.asyncio
async def test_export_without_profile_has_incomplete_marker(db, org, user_role):
    token_user = _make_token_user(org.id)
    u = await _create_user(db, user_id=205, username="gd205", email="gd205@test.com")
    await _add_user_to_org(db, u, org, role_id=user_role.id)
    data = await export_user_data(token_user, u.id, db)
    assert data["mka_profile"] == {"complete": False}
