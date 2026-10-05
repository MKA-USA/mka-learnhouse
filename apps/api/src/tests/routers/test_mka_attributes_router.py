"""MKA fork: /mka/attributes router (spec A7, B8 router tests).

Token tests use the REAL auth path (``Authorization: Bearer lh_...`` against a real
``apitoken`` row), because the companion service depends on exactly that.
"""

from datetime import datetime

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.core.events.database import get_db_session
from src.db.api_tokens import APIToken
from src.db.mka_user_profile import MkaUserProfile
from src.db.organization_config import OrganizationConfig
from src.db.user_organizations import UserOrganization
from src.db.users import User
from src.security.api_token_utils import require_authenticated_user_or_api_token
from src.security.auth import get_authenticated_user, get_current_user
from src.services.api_tokens.api_tokens import generate_api_token
from src.services.mka import attributes as svc

BASE = "/api/v1/mka/attributes"


async def _member(db, org, uid, email, role_id=4, signup="google"):
    now = str(datetime.now())
    db.add(User(id=uid, username=f"u{uid}", first_name="F", last_name="L", email=email, password="x",
                user_uuid=f"user_{uid}", signup_method=signup, creation_date=now, update_date=now))
    await db.commit()
    db.add(UserOrganization(user_id=uid, org_id=org.id, role_id=role_id, creation_date=now, update_date=now))
    await db.commit()


@pytest.fixture
async def seeded(db, org, other_org, admin_user, regular_user):
    emails = {
        10: "tabligh.albany@mkausa.org", 11: "tabligh.boston@mkausa.org", 12: "taleem.albany@mkausa.org",
        13: "qaid.northeast@mkausa.org", 14: "john.smith@mkausa.org", 15: "someone@gmail.com",
        16: "nazim.syracuse@atfalusa.org", 17: "tabligh@mkausa.org",
    }
    for uid, e in emails.items():
        await _member(db, org, uid, e)
    await _member(db, other_org, 99, "tabligh.albany+other@mkausa.org")
    for o in (org, other_org):  # the upstream admin-token pattern reads the org plan from its config
        db.add(OrganizationConfig(org_id=o.id, config={"config_version": "2.0"},
                                  creation_date=str(datetime.now()), update_date=str(datetime.now())))
    await db.commit()
    await svc.recompute_users(db)
    return emails


def _app(db):
    from src.router import v1_router

    app = FastAPI()
    app.include_router(v1_router)
    app.dependency_overrides[get_db_session] = lambda: db
    return app


@pytest.fixture
async def token_client(db, org, admin_user, seeded):
    full, prefix, hashed = generate_api_token()
    db.add(APIToken(name="companion", token_uuid="apitoken_x", token_prefix=prefix, token_hash=hashed,
                    org_id=org.id, created_by_user_id=admin_user.id, rights={},
                    creation_date=str(datetime.now()), update_date=str(datetime.now())))
    await db.commit()
    app = _app(db)  # no auth override: real get_current_user + real token validation
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t",
                           headers={"Authorization": f"Bearer {full}"}) as c:
        yield c


def _session_client(db, user):
    app = _app(db)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_authenticated_user] = lambda: user
    app.dependency_overrides[require_authenticated_user_or_api_token] = lambda: user
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


# --- API token: the companion service path ---------------------------------------------------

@pytest.mark.asyncio
async def test_token_can_list_with_filters(token_client, org):
    r = await token_client.get(f"{BASE}/users", params={"org_slug": org.slug})
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 8
    item = r.json()["items"][0]
    assert {"user_id", "email", "effective", "derived", "override"} <= set(item)

    async def q(**p):
        resp = await token_client.get(f"{BASE}/users", params={"org_slug": org.slug, **p})
        assert resp.status_code == 200, resp.text
        return resp.json()

    assert (await q(department="tabligh"))["total"] == 3          # albany, boston, national
    assert (await q(department="tabligh", level="local"))["total"] == 2
    assert (await q(level="national"))["total"] == 1
    assert (await q(level="regional"))["total"] == 1
    assert (await q(region="Northeast"))["total"] == 5
    assert (await q(majlis="Albany"))["total"] == 2
    assert (await q(status="unrecognized"))["total"] == 1          # john.smith
    assert (await q(status="not_applicable"))["total"] == 1
    assert (await q(status="unrecognized,not_applicable"))["total"] == 2
    assert (await q(q="boston"))["total"] == 1
    p1 = await q(page=1, page_size=5)
    p2 = await q(page=2, page_size=5)
    assert len(p1["items"]) == 5 and len(p2["items"]) == 3 and p1["total"] == 8


@pytest.mark.asyncio
async def test_token_other_org_slug_is_403(token_client, other_org):
    r = await token_client.get(f"{BASE}/users", params={"org_slug": other_org.slug})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_token_other_org_id_is_403(token_client, other_org):
    r = await token_client.get(f"{BASE}/users", params={"org_slug": "x", "org_id": other_org.id})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_token_without_org_slug_is_422(token_client):
    assert (await token_client.get(f"{BASE}/users")).status_code == 422


@pytest.mark.asyncio
async def test_token_never_sees_other_orgs_users(token_client, org):
    r = await token_client.get(f"{BASE}/users", params={"org_slug": org.slug, "page_size": 200})
    assert 99 not in {i["user_id"] for i in r.json()["items"]}
    assert (await token_client.get(f"{BASE}/users/99", params={"org_slug": org.slug})).status_code == 404


@pytest.mark.asyncio
async def test_token_cannot_use_viewer_or_override_endpoints(token_client, org):
    assert (await token_client.get(f"{BASE}/me")).status_code == 403
    r = await token_client.put(f"{BASE}/users/14/override", params={"org_slug": org.slug},
                               json={"override": {"level": "local"}, "reason": "x"})
    assert r.status_code == 403
    assert (await token_client.delete(f"{BASE}/users/14/override", params={"org_slug": org.slug})).status_code == 403


@pytest.mark.asyncio
async def test_token_roster_upsert_import_delete_then_list(token_client, org, db):
    p = {"org_slug": org.slug}
    r = await token_client.put(f"{BASE}/roster/John.Smith@mkausa.org", params=p,
                               json={"attributes": {"level": "national", "role": "naib_sadr"}, "note": "from roster"})
    assert r.status_code == 200 and r.json()["source"] == "companion" and r.json()["updated_by"] is None
    got = (await token_client.get(f"{BASE}/users/14", params=p)).json()
    assert got["effective"]["role"] == "naib_sadr" and got["derived"]["status"] == "unrecognized"
    assert got["effective"]["source"] == "roster"
    audit = (await token_client.get(f"{BASE}/users/14/audit", params=p)).json()["items"]
    assert audit[0]["action"] == "roster_apply" and audit[0]["actor_user_id"] is None

    imp = await token_client.post(f"{BASE}/roster/import", params=p, json={"rows": [
        {"email": "ashfaq.khan@mkausa.org", "attributes": {"level": "national", "role": "naib_sadr"}},
        {"email": "bad", "attributes": {"level": "national"}},
    ]})
    assert imp.status_code == 200 and imp.json()["applied"] == 1 and imp.json()["failed"] == 1
    lst = (await token_client.get(f"{BASE}/roster", params=p)).json()["items"]
    assert {x["email"] for x in lst} == {"john.smith@mkausa.org", "ashfaq.khan@mkausa.org"}

    assert (await token_client.delete(f"{BASE}/roster/john.smith@mkausa.org", params=p)).status_code == 200
    assert (await token_client.delete(f"{BASE}/roster/john.smith@mkausa.org", params=p)).status_code == 404
    got = (await token_client.get(f"{BASE}/users/14", params=p)).json()
    assert got["effective"]["status"] == "unrecognized"


@pytest.mark.asyncio
async def test_token_roster_validation_422(token_client, org):
    p = {"org_slug": org.slug}
    r = await token_client.put(f"{BASE}/roster/a@b.org", params=p, json={"attributes": {"level": "galactic"}})
    assert r.status_code == 422
    r = await token_client.put(f"{BASE}/roster/a@b.org", params=p, json={"attributes": {}})
    assert r.status_code == 422
    r = await token_client.post(f"{BASE}/roster/import", params=p, json={"rows": [], "extra": 1})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_token_recompute_and_review_queue(token_client, org):
    p = {"org_slug": org.slug}
    r = await token_client.post(f"{BASE}/recompute", params=p, json={})
    assert r.status_code == 200 and r.json()["unchanged"] == 8 and r.json()["changed"] == 0
    q = (await token_client.get(f"{BASE}/review-queue", params=p)).json()
    assert {i["user_id"] for i in q["unclassified"]["items"]} == {14}
    assert q["mismatch"]["total"] == 0


@pytest.mark.asyncio
async def test_unauthenticated_is_401(db, seeded):
    app = _app(db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.get(f"{BASE}/me")).status_code == 401
        assert (await c.get(f"{BASE}/users", params={"org_id": 1})).status_code == 401


@pytest.mark.asyncio
async def test_bad_token_is_401(db, seeded):
    app = _app(db)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t",
                           headers={"Authorization": "Bearer lh_totallywrongtoken"}) as c:
        assert (await c.get(f"{BASE}/users", params={"org_slug": "x"})).status_code == 401


# --- session: viewer ------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_me_returns_only_own_effective_without_metadata(db, org, seeded, admin_user, regular_user):
    u = (await db.get(User, 10))
    from src.db.users import PublicUser
    pu = PublicUser(id=u.id, username=u.username, first_name="F", last_name="L", email=u.email, user_uuid=u.user_uuid)
    async with _session_client(db, pu) as c:
        r = await c.get(f"{BASE}/me")
    assert r.status_code == 200
    body = r.json()
    assert r.headers["cache-control"] == "private, no-store"
    assert body["attributes"] == {
        "status": "matched", "is_officeholder": True, "level": "local", "department": "tabligh",
        "role": "nazim_dept", "role_title": "Nazim Tabligh", "majlis": "Albany", "region": "Northeast",
    }
    assert body["can_view_all"] is False and body["rules_version"] == "2026.1"
    assert "source" not in body["attributes"] and "flags" not in body["attributes"]


@pytest.mark.asyncio
async def test_me_without_row_is_unrecognized_not_non_officeholder(db, org, admin_user, regular_user):
    async with _session_client(db, regular_user) as c:
        r = await c.get(f"{BASE}/me")
    assert r.json()["attributes"]["status"] == "unrecognized"
    assert r.json()["attributes"]["is_officeholder"] is None


@pytest.mark.asyncio
async def test_me_can_view_all_for_admin(db, org, admin_user, regular_user):
    async with _session_client(db, admin_user) as c:
        assert (await c.get(f"{BASE}/me")).json()["can_view_all"] is True
    async with _session_client(db, regular_user) as c:
        assert (await c.get(f"{BASE}/me")).json()["can_view_all"] is False


@pytest.mark.asyncio
async def test_me_has_no_way_to_read_or_write_others(db, org, seeded, admin_user, regular_user):
    async with _session_client(db, regular_user) as c:
        assert (await c.get(f"{BASE}/me", params={"user_id": 10})).json()["attributes"]["status"] == "unrecognized"
        for method, url in (("PUT", f"{BASE}/me"), ("POST", f"{BASE}/me"), ("PATCH", f"{BASE}/me")):
            assert (await c.request(method, url, json={"level": "national"})).status_code == 405


# --- session: admin authz matrix -----------------------------------------------------------------

@pytest.mark.asyncio
async def test_regular_user_cannot_use_admin_routes(db, org, seeded, admin_user, regular_user):
    async with _session_client(db, regular_user) as c:
        for method, url, kw in (
            ("GET", f"{BASE}/users", {}), ("GET", f"{BASE}/users/10", {}), ("GET", f"{BASE}/review-queue", {}),
            ("GET", f"{BASE}/roster", {}), ("POST", f"{BASE}/recompute", {"json": {}}),
            ("PUT", f"{BASE}/roster/a@b.org", {"json": {"attributes": {"level": "local"}}}),
            ("PUT", f"{BASE}/users/10/override", {"json": {"override": {"level": "local"}, "reason": "x"}}),
            ("DELETE", f"{BASE}/users/10/override", {}),
        ):
            r = await c.request(method, url, params={"org_id": org.id}, **kw)
            assert r.status_code == 403, (method, url, r.status_code)


@pytest.mark.asyncio
async def test_admin_lists_with_org_id_and_requires_it(db, org, seeded, admin_user):
    async with _session_client(db, admin_user) as c:
        r = await c.get(f"{BASE}/users", params={"org_id": org.id, "department": "tabligh"})
        assert r.status_code == 200 and r.json()["total"] == 3
        assert (await c.get(f"{BASE}/users")).status_code == 422
        r = await c.get(f"{BASE}/users", params={"org_slug": org.slug})
        assert r.status_code == 200 and r.json()["total"] == 8


@pytest.mark.asyncio
async def test_admin_of_other_org_is_forbidden(db, org, other_org, seeded, admin_user):
    async with _session_client(db, admin_user) as c:
        r = await c.get(f"{BASE}/users", params={"org_id": other_org.id})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_override_flow_and_audit(db, org, seeded, admin_user):
    p = {"org_id": org.id}
    async with _session_client(db, admin_user) as c:
        r = await c.put(f"{BASE}/users/14/override", params=p,
                        json={"override": {"level": "national", "role": "sadr"}, "reason": "Confirmed by Aitmad"})
        assert r.status_code == 200, r.text
        assert r.json()["effective"]["role"] == "sadr" and r.json()["override_by"] == admin_user.id
        assert r.json()["derived"]["status"] == "unrecognized"      # derived stays raw

        bad = await c.put(f"{BASE}/users/14/override", params=p,
                          json={"override": {"level": "galactic"}, "reason": "x"})
        assert bad.status_code == 422
        noreason = await c.put(f"{BASE}/users/14/override", params=p, json={"override": {"level": "local"}})
        assert noreason.status_code == 422
        blank = await c.put(f"{BASE}/users/14/override", params=p,
                            json={"override": {"level": "local"}, "reason": " "})
        assert blank.status_code == 422
        extra = await c.put(f"{BASE}/users/14/override", params=p,
                            json={"override": {"level": "local"}, "reason": "x", "user_id": 1})
        assert extra.status_code == 422

        assert (await c.post(f"{BASE}/recompute", params=p, json={})).json()["changed"] == 0
        assert (await c.get(f"{BASE}/users/14", params=p)).json()["effective"]["role"] == "sadr"

        d = await c.delete(f"{BASE}/users/14/override", params={**p, "reason": "oops"})
        assert d.status_code == 200 and d.json()["override"] is None
        assert d.json()["effective"]["status"] == "unrecognized"

        audit = (await c.get(f"{BASE}/users/14/audit", params=p)).json()["items"]
        assert [a["action"] for a in audit] == ["override_clear", "override_set", "recompute"]
        assert audit[1]["reason"] == "Confirmed by Aitmad" and audit[1]["actor_user_id"] == admin_user.id


@pytest.mark.asyncio
async def test_override_target_must_be_in_org(db, org, other_org, seeded, admin_user):
    async with _session_client(db, admin_user) as c:
        r = await c.put(f"{BASE}/users/99/override", params={"org_id": org.id},
                        json={"override": {"level": "local"}, "reason": "x"})
        assert r.status_code == 404
        r = await c.get(f"{BASE}/users/99", params={"org_id": org.id})
        assert r.status_code == 404
        r = await c.get(f"{BASE}/users/424242", params={"org_id": org.id})
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_user_without_attributes_is_404(db, org, admin_user, regular_user):
    async with _session_client(db, admin_user) as c:
        r = await c.get(f"{BASE}/users/{regular_user.id}", params={"org_id": org.id})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_session_roster_records_actor(db, org, seeded, admin_user):
    async with _session_client(db, admin_user) as c:
        r = await c.put(f"{BASE}/roster/new.person@mkausa.org", params={"org_id": org.id},
                        json={"attributes": {"majlis": "Boston", "department": "tabligh", "role": "nazim_dept"}})
    assert r.status_code == 200 and r.json()["source"] == "admin" and r.json()["updated_by"] == admin_user.id


@pytest.mark.asyncio
async def test_review_queue_mismatch(db, org, seeded, admin_user):
    db.add(MkaUserProfile(user_id=10, majlis="Seattle", region="Northwest"))
    db.add(MkaUserProfile(user_id=11, majlis="Boston", region="Northeast"))
    await db.commit()
    async with _session_client(db, admin_user) as c:
        q = (await c.get(f"{BASE}/review-queue", params={"org_id": org.id})).json()
        assert [i["user_id"] for i in q["mismatch"]["items"]] == [10]
        m = (await c.get(f"{BASE}/users", params={"org_id": org.id, "mismatch": "true"})).json()
        assert m["total"] == 1


@pytest.mark.asyncio
async def test_recompute_dry_run(db, org, seeded, admin_user):
    await _member(db, org, 50, "tabligh.denver@mkausa.org")
    async with _session_client(db, admin_user) as c:
        r = await c.post(f"{BASE}/recompute", params={"org_id": org.id}, json={"dry_run": True})
        assert r.json()["created"] == 1
    assert await svc.get_row(db, 50) is None


@pytest.mark.asyncio
async def test_user_profile_endpoints_unchanged_when_no_attributes(db, org, admin_user, regular_user):
    """The existing /mka/profile contract holds for users without attribute rows."""
    async with _session_client(db, regular_user) as c:
        r = await c.get("/api/v1/mka/profile/me")
    assert r.json() == {"complete": False}
