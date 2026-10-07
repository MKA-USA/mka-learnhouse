"""MKA fork: /mka/identity router (sync + status): authentication, org scoping, dry-run default, flag gate."""

import pytest
from httpx import AsyncClient

from src.tests.routers.mka_compliance_world import add_attributes, add_user
from httpx import ASGITransport

from src.db.users import PublicUser
from src.security.api_token_utils import require_authenticated_user_or_api_token
from src.security.auth import get_authenticated_user, get_current_user
from src.tests.routers.test_mka_automation_router import READ, _app, token_client

SYNC = "/api/v1/mka/identity/sync"
STATUS = "/api/v1/mka/identity/status"
FULL = {r: {"action_read": True, "action_update": True}
        for r in ("courses", "activities", "assignments", "coursechapters", "usergroups", "certifications")}


def session_client(db, uid):
    app = _app(db)
    user = PublicUser(id=uid, username=f"u{uid}", first_name="F", last_name="L", email=f"u{uid}@x.invalid", user_uuid=f"user_{uid}")
    for dep in (get_current_user, get_authenticated_user, require_authenticated_user_or_api_token):
        app.dependency_overrides[dep] = lambda: user
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("MKA_IDENTITY_SYNC_ENABLED", raising=False)
    monkeypatch.setenv("MKA_IDENTITY_SYNC_ORG_IDS", "1")  # the `org` fixture


@pytest.fixture
async def people(db, org, other_org, admin_user, regular_user):
    await add_user(db, org.id, 50, "tabligh@example.invalid")
    await add_attributes(db, 50, "tabligh@example.invalid", level="national", department="tabligh", role="mohtamim")
    await add_user(db, other_org.id, 51, "maal@example.invalid")
    await add_attributes(db, 51, "maal@example.invalid", level="national", department="maal", role="mohtamim")


async def test_unauthenticated_is_401(db, org):
    async with AsyncClient(transport=ASGITransport(app=_app(db)), base_url="http://t") as c:
        assert (await c.post(SYNC, params={"org_id": org.id})).status_code == 401
        assert (await c.get(STATUS, params={"org_id": org.id})).status_code == 401


async def test_a_plain_member_and_an_admin_of_another_org_are_403(db, org, other_org, people):
    async with session_client(db, 2) as c:
        assert (await c.post(SYNC, params={"org_id": org.id})).status_code == 403
        assert (await c.get(STATUS, params={"org_id": org.id})).status_code == 403
    async with session_client(db, 1) as c:  # admin of org, not of other_org
        assert (await c.post(SYNC, params={"org_id": other_org.id})).status_code == 403


async def test_dry_run_is_the_default_and_works_with_the_flag_off(db, org, people):
    async with session_client(db, 1) as c:
        r = await c.post(SYNC, params={"org_slug": org.slug})
    assert r.status_code == 200 and r.headers["cache-control"] == "private, no-store"
    body = r.json()
    assert body["dry_run"] is True and body["users_seen"] == 1 and body["roles_set"] == 1
    assert [p["user_id"] for p in body["planned"]] == [50]
    assert "email" not in str(body) and body["groups_created"] == 85 and body["groups_recreated"] == 0
    async with session_client(db, 1) as c:
        assert (await c.get(STATUS, params={"org_slug": org.slug})).json()["groups"] == 0  # nothing written


async def test_apply_needs_the_flag(db, org, people, monkeypatch):
    async with session_client(db, 1) as c:
        assert (await c.post(SYNC, params={"org_slug": org.slug, "dry_run": "false"})).status_code == 409
        denied = await c.post(SYNC, params={"org_slug": org.slug, "dry_run": "false"})
        assert denied.json() == {"detail": "identity sync is disabled"}
        monkeypatch.setenv("MKA_IDENTITY_SYNC_ENABLED", "true")
        r = await c.post(SYNC, params={"org_slug": org.slug, "dry_run": "false"})
        assert r.status_code == 200 and r.json()["roles_set"] == 1 and r.json()["groups_created"] == 85
        status = (await c.get(STATUS, params={"org_slug": org.slug})).json()
    assert status["enabled"] and status["groups"] == 85 and status["role_id"] and status["last_sync_at"]


async def test_token_rights_and_org_boundary(db, org, other_org, people, monkeypatch):
    monkeypatch.setenv("MKA_IDENTITY_SYNC_ENABLED", "true")
    async with await token_client(db, org, READ) as c:
        assert (await c.post(SYNC, params={"org_slug": org.slug})).status_code == 200  # dry run: read-only preset is enough
        assert (await c.get(STATUS, params={"org_slug": org.slug})).status_code == 200
        assert (await c.post(SYNC, params={"org_slug": org.slug, "dry_run": "false"})).status_code == 403
        assert (await c.post(SYNC, params={"org_slug": other_org.slug})).status_code in (401, 403, 404)
    async with await token_client(db, org, FULL, n=2) as c:
        r = await c.post(SYNC, params={"org_slug": org.slug, "dry_run": "false"})
        assert r.status_code == 200 and r.json()["users_seen"] == 1
        assert (await c.post(SYNC, params={"org_slug": other_org.slug, "dry_run": "false"})).status_code in (401, 403, 404)
        assert (await c.get(STATUS, params={"org_slug": other_org.slug})).status_code in (401, 403, 404)
    async with await token_client(db, org, {}, n=3) as c:
        assert (await c.post(SYNC, params={"org_slug": org.slug})).status_code == 403


async def test_apply_needs_the_org_on_the_allowlist_but_dry_run_does_not(db, org, other_org, people, monkeypatch):
    monkeypatch.setenv("MKA_IDENTITY_SYNC_ENABLED", "true")
    monkeypatch.delenv("MKA_IDENTITY_SYNC_ORG_IDS")
    async with session_client(db, 1) as c:
        dry = await c.post(SYNC, params={"org_slug": org.slug})
        assert dry.status_code == 200 and dry.json()["org_allowed"] is False
        assert dry.json()["planned"] == [] and dry.json()["users_seen"] == 0 and dry.json()["roles_set"] == 0
        denied = await c.post(SYNC, params={"org_slug": org.slug, "dry_run": "false"})
        assert denied.status_code == 409 and "allowlisted" in denied.json()["detail"]
        status = (await c.get(STATUS, params={"org_slug": org.slug})).json()
        assert status["org_allowed"] is False and "orgs_allowed" not in status
    monkeypatch.setenv("MKA_IDENTITY_SYNC_ORG_IDS", "1")
    async with session_client(db, 1) as c:
        assert (await c.post(SYNC, params={"org_slug": org.slug, "dry_run": "false"})).status_code == 200
