from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from src.core.events.database import get_db_session
from src.db.mka_user_profile import MkaUserProfile
from src.db.users import AnonymousUser, APITokenUser, User
from src.routers import mka_profile as r
from src.security.auth import get_authenticated_user, get_current_user
from src.services.users.mka_profile import MkaProfileIn, profile_status


@pytest.mark.asyncio
async def test_options_endpoint():
    o = await r.api_options()
    assert len(o["majlis"]) == 52


@pytest.mark.asyncio
async def test_me_get_then_put(db, regular_user):
    assert await r.api_get_me(current_user=regular_user, db_session=db) == {"complete": False}
    out = await r.api_put_me(
        body=MkaProfileIn(majlis="Seattle", tanzeem="khadim"),
        current_user=regular_user, db_session=db,
    )
    assert out["region"] == "Northwest" and out["complete"] is True
    assert (await profile_status(db, regular_user.id))["majlis"] == "Seattle"


@pytest.mark.asyncio
async def test_put_me_is_full_replace(db, regular_user):
    await r.api_put_me(
        body=MkaProfileIn(majlis="Seattle", tanzeem="khadim"),
        current_user=regular_user, db_session=db,
    )
    out = await r.api_put_me(
        body=MkaProfileIn(majlis="Zion"), current_user=regular_user, db_session=db
    )
    assert out == {
        "complete": True, "majlis": "Zion", "region": "Midwest",
        "mobile": None, "amc_id": None, "tanzeem": None,
    }


@pytest.mark.asyncio
async def test_api_token_caller_gets_403_not_500(db):
    tok = APITokenUser(id=7, org_id=1)
    with pytest.raises(HTTPException) as e:
        await r.api_get_me(current_user=tok, db_session=db)
    assert e.value.status_code == 403
    with pytest.raises(HTTPException) as e:
        await r.api_put_user(
            user_id=1, org_id=1, body=MkaProfileIn(majlis="Zion"),
            current_user=tok, db_session=db,
        )
    assert e.value.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_edit_member_in_their_org(db, org, admin_user, regular_user):
    out = await r.api_put_user(
        user_id=regular_user.id, org_id=org.id,
        body=MkaProfileIn(majlis="Zion"),
        current_user=admin_user, db_session=db,
    )
    assert out["region"] == "Midwest"


@pytest.mark.asyncio
async def test_regular_user_cannot_edit_others(db, org, admin_user, regular_user):
    with pytest.raises(HTTPException) as e:
        await r.api_put_user(
            user_id=admin_user.id, org_id=org.id,
            body=MkaProfileIn(majlis="Zion"),
            current_user=regular_user, db_session=db,
        )
    assert e.value.status_code == 403
    assert (await profile_status(db, admin_user.id)) == {"complete": False}


@pytest.mark.asyncio
async def test_non_admin_gets_403_even_for_nonexistent_user(db, org, regular_user):
    with pytest.raises(HTTPException) as e:
        await r.api_put_user(
            user_id=999999, org_id=org.id, body=MkaProfileIn(majlis="Zion"),
            current_user=regular_user, db_session=db,
        )
    assert e.value.status_code == 403


@pytest.mark.asyncio
async def test_admin_cannot_edit_user_outside_their_org(db, org, other_org, admin_user):
    outsider = User(
        username="out", first_name="O", last_name="U", email="out@test.com",
        password="x", user_uuid="user_out",
        creation_date=str(datetime.now()), update_date=str(datetime.now()),
    )
    db.add(outsider)
    await db.commit()
    await db.refresh(outsider)
    with pytest.raises(HTTPException) as e:
        await r.api_put_user(
            user_id=outsider.id, org_id=org.id,
            body=MkaProfileIn(majlis="Zion"),
            current_user=admin_user, db_session=db,
        )
    assert e.value.status_code == 404
    assert (await profile_status(db, outsider.id)) == {"complete": False}


def test_router_is_registered():
    # v1_router.routes holds a single nested mount in this FastAPI version, so
    # resolve the real paths through the generated OpenAPI schema instead.
    from src.router import v1_router
    app = FastAPI()
    app.include_router(v1_router)
    paths = set(app.openapi()["paths"])
    assert "/api/v1/mka/profile/options" in paths
    assert "/api/v1/mka/profile/me" in paths
    assert "/api/v1/mka/profile/user/{user_id}" in paths


@pytest.mark.asyncio
async def test_real_app_anonymous_options_ok_and_me_401(db):
    from src.router import v1_router
    app = FastAPI()
    app.include_router(v1_router)
    app.dependency_overrides[get_db_session] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: AnonymousUser()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            ok = await c.get("/api/v1/mka/profile/options")
            assert ok.status_code == 200 and len(ok.json()["majlis"]) == 52
            me = await c.get("/api/v1/mka/profile/me")
            assert me.status_code == 401
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def as_superadmin(monkeypatch):
    # No superadmin fixture exists for router tests; patch the router's check.
    monkeypatch.setattr(r, "is_user_superadmin", AsyncMock(return_value=True))


async def _count_profiles(db, user_id):
    from sqlmodel import select

    rows = (
        await db.execute(select(MkaUserProfile).where(MkaUserProfile.user_id == user_id))
    ).scalars().all()
    return len(rows)


async def _make_user(db, name):
    u = User(
        username=name, first_name="O", last_name="U", email=f"{name}@test.com",
        password="x", user_uuid=f"user_{name}",
        creation_date=str(datetime.now()), update_date=str(datetime.now()),
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


@pytest.mark.asyncio
async def test_superadmin_unknown_user_404_no_row(db, org, admin_user, as_superadmin):
    with pytest.raises(HTTPException) as e:
        await r.api_put_user(
            user_id=999999, org_id=org.id, body=MkaProfileIn(majlis="Zion"),
            current_user=admin_user, db_session=db,
        )
    assert e.value.status_code == 404
    assert await _count_profiles(db, 999999) == 0


@pytest.mark.asyncio
async def test_admin_unknown_user_is_404(db, org, admin_user):
    with pytest.raises(HTTPException) as e:
        await r.api_put_user(
            user_id=999999, org_id=org.id, body=MkaProfileIn(majlis="Zion"),
            current_user=admin_user, db_session=db,
        )
    assert e.value.status_code == 404
    assert await _count_profiles(db, 999999) == 0


@pytest.mark.asyncio
async def test_non_admin_unknown_user_is_403_not_404(db, org, regular_user):
    with pytest.raises(HTTPException) as e:
        await r.api_put_user(
            user_id=999999, org_id=org.id, body=MkaProfileIn(majlis="Zion"),
            current_user=regular_user, db_session=db,
        )
    assert e.value.status_code == 403
    assert await _count_profiles(db, 999999) == 0


@pytest.mark.asyncio
async def test_superadmin_edits_user_outside_org_id(db, org, other_org, admin_user, as_superadmin):
    outsider = await _make_user(db, "out2")
    out = await r.api_put_user(
        user_id=outsider.id, org_id=org.id, body=MkaProfileIn(majlis="Zion"),
        current_user=admin_user, db_session=db,
    )
    assert out["region"] == "Midwest" and out["complete"] is True


@pytest.mark.asyncio
async def test_maintainer_cannot_edit_profiles(db, org, regular_user):
    from src.db.roles import Role, RoleTypeEnum
    from src.db.user_organizations import UserOrganization
    from src.security.rbac.constants import MAINTAINER_ROLE_ID

    now = str(datetime.now())
    db.add(Role(
        id=MAINTAINER_ROLE_ID, name="Maintainer", org_id=org.id,
        role_type=RoleTypeEnum.TYPE_ORGANIZATION, role_uuid="role_maint",
        rights={}, creation_date=now, update_date=now,
    ))
    maint = await _make_user(db, "maint")
    db.add(UserOrganization(
        user_id=maint.id, org_id=org.id, role_id=MAINTAINER_ROLE_ID,
        creation_date=now, update_date=now,
    ))
    await db.commit()
    with pytest.raises(HTTPException) as e:
        await r.api_put_user(
            user_id=regular_user.id, org_id=org.id, body=MkaProfileIn(majlis="Zion"),
            current_user=maint, db_session=db,
        )
    assert e.value.status_code == 403
    assert await _count_profiles(db, regular_user.id) == 0


@pytest.fixture
async def asgi_client(db, regular_user):
    from src.router import v1_router

    app = FastAPI()
    app.include_router(v1_router)
    app.dependency_overrides[get_db_session] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: regular_user
    app.dependency_overrides[get_authenticated_user] = lambda: regular_user
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            yield c
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body,needle",
    [
        ({"majlis": "Atlantis"}, "Select a valid Majlis"),
        ({"majlis": "Zion", "amc_id": "12a"}, "Value error"),
        ({"majlis": "Zion", "mobile": "+44 20 7946 0958"}, "Value error"),
    ],
)
async def test_asgi_put_me_invalid_body_422(asgi_client, db, regular_user, body, needle):
    resp = await asgi_client.put("/api/v1/mka/profile/me", json=body)
    assert resp.status_code == 422
    assert needle in str(resp.json()["detail"])
    assert await _count_profiles(db, regular_user.id) == 0


@pytest.mark.asyncio
async def test_asgi_put_me_ignores_client_region(asgi_client, db, regular_user):
    resp = await asgi_client.put(
        "/api/v1/mka/profile/me", json={"majlis": "Seattle", "region": "X"}
    )
    assert resp.status_code == 200
    assert resp.json()["region"] == "Northwest"
    assert (await profile_status(db, regular_user.id))["region"] == "Northwest"
