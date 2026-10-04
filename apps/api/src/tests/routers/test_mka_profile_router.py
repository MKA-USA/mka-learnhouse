from datetime import datetime

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from src.core.events.database import get_db_session
from src.db.users import AnonymousUser, APITokenUser, User
from src.routers import mka_profile as r
from src.security.auth import get_current_user
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
    assert out["majlis"] == "Zion"
    assert not out.get("tanzeem")


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
    print(sorted(p for p in paths if "mka" in p))
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
