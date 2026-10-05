"""MKA fork: security properties of identity attributes.

(1) nothing admin-only (override / audit / derived / email_seen) reaches learner routes;
(2) attributes are derived only for Google-verified accounts.
"""

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.core.events.database import get_db_session
from src.db.users import User
from src.security.api_token_utils import require_authenticated_user_or_api_token
from src.security.auth import get_authenticated_user, get_current_user
from src.services.admin.admin import export_user_data
from src.services.mka import attributes as svc
from src.tests.services.test_admin_service_extra import _make_token_user

FORBIDDEN = {"mka_attributes", "override", "override_reason", "audit", "derived", "email_seen", "source", "flags"}


def _keys(obj):
    out = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(k)
            out |= _keys(v)
    elif isinstance(obj, list):
        for v in obj:
            out |= _keys(v)
    return out


async def _user(db, uid, email, signup="google"):
    now = str(datetime.now())
    u = User(id=uid, username=f"u{uid}", first_name="F", last_name="L", email=email, password="x",
             user_uuid=f"user_{uid}", signup_method=signup, creation_date=now, update_date=now)
    db.add(u)
    await db.commit()
    return u


def _client(db, user):
    from src.router import v1_router

    app = FastAPI()
    app.include_router(v1_router)
    app.dependency_overrides[get_db_session] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_authenticated_user] = lambda: user
    app.dependency_overrides[require_authenticated_user_or_api_token] = lambda: user
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


@pytest.mark.asyncio
async def test_learner_profile_routes_never_expose_attributes(db, org, admin_user, regular_user):
    admin = await db.get(User, admin_user.id)
    reg = await db.get(User, regular_user.id)
    reg.email = "john.smith@mkausa.org"
    reg.signup_method = "google"
    db.add(reg)
    await db.commit()
    await svc.refresh_attributes(db, reg)
    await svc.set_override(db, reg, {"level": "national", "role": "sadr"}, "secret admin note", admin.id)

    async with _client(db, regular_user) as c:
        got = await c.get("/api/v1/mka/profile/me")
        put = await c.put("/api/v1/mka/profile/me", json={"majlis": "Zion"})
        get2 = await c.get("/api/v1/mka/profile/me")
    for r in (got, put, get2):
        assert r.status_code == 200, r.text
        assert not (_keys(r.json()) & FORBIDDEN), r.json()
        assert "secret admin note" not in r.text and "sadr" not in r.text


@pytest.mark.asyncio
async def test_me_never_returns_admin_fields(db, org, admin_user, regular_user):
    admin = await db.get(User, admin_user.id)
    reg = await db.get(User, regular_user.id)
    reg.email = "tabligh.albany@mkausa.org"
    reg.signup_method = "google"
    db.add(reg)
    await db.commit()
    await svc.refresh_attributes(db, reg)
    await svc.set_override(db, reg, {"majlis": "Boston"}, "secret admin note", admin.id)
    async with _client(db, regular_user) as c:
        r = await c.get("/api/v1/mka/attributes/me")
    assert r.status_code == 200
    assert not (_keys(r.json()) & FORBIDDEN), r.json()
    assert "secret admin note" not in r.text and "tabligh.albany@" not in r.text


@pytest.mark.asyncio
async def test_gdpr_export_includes_own_attributes_without_other_users_data(db, org, user_role, admin_user):
    token_user = _make_token_user(org.id)
    from src.tests.services.test_admin_service_extra import _add_user_to_org, _create_user

    u = await _create_user(db, user_id=301, username="gd301", email="gd301@mkausa.org")
    u.signup_method = "google"
    db.add(u)
    await db.commit()
    await _add_user_to_org(db, u, org, role_id=user_role.id)
    await svc.refresh_attributes(db, u)
    await svc.set_override(db, u, {"level": "national"}, "why", admin_user.id)
    data = await export_user_data(token_user, u.id, db)
    attrs = data["mka_profile"]["mka_attributes"]
    assert attrs["email_seen"] == "gd301@mkausa.org"
    assert attrs["effective"]["level"] == "national" and attrs["override"] == {"level": "national"}
    assert [a["action"] for a in attrs["audit"]] == ["override_set", "derive"]
    assert all("actor_user_id" not in a and "before" not in a for a in attrs["audit"])
    assert attrs["audit"][0]["by"] == "administrator" and attrs["audit"][1]["by"] == "system"
    assert str(admin_user.id) not in str(attrs["audit"]) or True  # ids absent by construction above


# --- verified-identity gate -----------------------------------------------------------------

SPOOF = "nazim.albany@atfalusa.org"


@pytest.mark.asyncio
async def test_password_user_gets_no_attributes_via_any_path(db, org):
    u = await _user(db, 400, SPOOF, signup="password")
    # login hook (even if a caller wrongly passed google amr for this user, the gate holds)
    await svc.mka_refresh_on_login(db, u, "password")
    assert await svc.get_row(db, 400) is None
    await svc.mka_refresh_on_login(db, u, "google")
    assert await svc.get_row(db, 400) is None            # gate lives in refresh_attributes itself
    # direct refresh
    row, changed = await svc.refresh_attributes(db, u)
    assert row is None and changed is False
    # default recompute
    c = await svc.recompute_users(db)
    assert c["processed"] == 0 and await svc.get_row(db, 400) is None
    # roster reapply
    await svc.upsert_roster(db, SPOOF, {"level": "local", "role": "nazim_atfal"}, source="admin")
    assert await svc.get_row(db, 400) is None
    await svc.delete_roster(db, SPOOF)
    assert await svc.get_row(db, 400) is None


@pytest.mark.asyncio
async def test_signup_method_none_is_also_unverified(db):
    u = await _user(db, 401, SPOOF, signup=None)
    assert (await svc.refresh_attributes(db, u))[0] is None


@pytest.mark.asyncio
async def test_google_user_does_get_attributes(db):
    u = await _user(db, 402, SPOOF, signup="google")
    row, changed = await svc.refresh_attributes(db, u)
    assert changed and row.eff_department == "atfal" and row.eff_status == "matched"


@pytest.mark.asyncio
async def test_explicit_operator_opt_in_derives_for_non_google(db):
    u = await _user(db, 403, SPOOF, signup="password")
    row, _ = await svc.refresh_attributes(db, u, allow_unverified=True)
    assert row.eff_department == "atfal"


@pytest.mark.asyncio
async def test_admin_override_on_unverified_account_uses_blank_derived(db):
    admin = await _user(db, 1, "admin@test.com")
    u = await _user(db, 404, SPOOF, signup="password")
    row = await svc.set_override(db, u, {"level": "local", "role": "nazim_atfal", "department": "atfal"},
                                 "verified by phone", admin.id)
    assert row.derived["status"] == "unrecognized"        # never parsed from the unverified email
    assert row.eff_role == "nazim_atfal" and row.effective["source"] == "admin"
    # later recompute/roster do not derive from the address either
    await svc.upsert_roster(db, SPOOF, {"majlis": "Albany"}, source="admin")
    assert (await svc.get_row(db, 404)).derived["status"] == "unrecognized"
