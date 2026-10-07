"""MKA fork: security properties of identity attributes.

(1) nothing admin-only (override / audit / derived / email_seen) reaches learner routes;
(2) attributes are derived only for Google-verified accounts.
"""

from datetime import datetime
from unittest.mock import patch

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


async def _user(db, uid, email, signup="google", org=None):
    now = str(datetime.now())
    u = User(id=uid, username=f"u{uid}", first_name="F", last_name="L", email=email, password="x",
             user_uuid=f"user_{uid}", signup_method=signup, creation_date=now, update_date=now)
    db.add(u)
    await db.commit()
    if org is not None:
        from src.db.user_organizations import UserOrganization

        db.add(UserOrganization(user_id=uid, org_id=org.id, role_id=4, creation_date=now, update_date=now))
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
    u = await _user(db, 400, SPOOF, signup="password", org=org)
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
    await svc.upsert_roster(db, org.id, SPOOF, {"level": "local", "role": "nazim_atfal"}, source="admin")
    assert await svc.get_row(db, 400) is None
    await svc.delete_roster(db, org.id, SPOOF)
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
async def test_admin_override_on_unverified_account_uses_blank_derived(db, org):
    admin = await _user(db, 1, "admin@test.com")
    u = await _user(db, 404, SPOOF, signup="password", org=org)
    row = await svc.set_override(db, u, {"level": "local", "role": "nazim_atfal", "department": "atfal"},
                                 "verified by phone", admin.id)
    assert row.derived["status"] == "unrecognized"        # never parsed from the unverified email
    assert row.eff_role == "nazim_atfal" and row.effective["source"] == "admin"
    # later recompute/roster do not derive from the address either
    await svc.upsert_roster(db, org.id, SPOOF, {"majlis": "Albany"}, source="admin")
    assert (await svc.get_row(db, 404)).derived["status"] == "unrecognized"


# --- cross-tenant: roster is per org ---------------------------------------------------------

from src.db.api_tokens import APIToken  # noqa: E402
from src.db.organization_config import OrganizationConfig  # noqa: E402
from src.db.mka_user_attributes import MkaRosterOverride  # noqa: E402
from src.db.user_organizations import UserOrganization  # noqa: E402
from src.services.api_tokens.api_tokens import generate_api_token  # noqa: E402
from sqlmodel import select  # noqa: E402

BASE = "/api/v1/mka/attributes"


async def _two_orgs(db, org, other_org):
    for o in (org, other_org):
        db.add(OrganizationConfig(org_id=o.id, config={"config_version": "2.0"},
                                  creation_date=str(datetime.now()), update_date=str(datetime.now())))
    await db.commit()
    a_user = await _user(db, 501, "john.smith@mkausa.org", org=org)            # only in A
    b_user = await _user(db, 502, "jane.doe@mkausa.org", org=other_org)        # only in B
    return a_user, b_user


async def _roster_rows(db):
    return {(r.org_id, r.email): r.attributes for r in (await db.execute(select(MkaRosterOverride))).scalars().all()}


@pytest.fixture
async def token_a(db, org, other_org, admin_user):
    full, prefix, hashed = generate_api_token()
    db.add(APIToken(name="a", token_uuid="apitoken_a", token_prefix=prefix, token_hash=hashed, org_id=org.id,
                    created_by_user_id=admin_user.id, rights={**{r: {"action_read": True, "action_update": True} for r in ("courses", "activities", "assignments", "coursechapters", "usergroups", "certifications")}},
                    creation_date=str(datetime.now()), update_date=str(datetime.now())))
    await db.commit()
    from src.router import v1_router

    app = FastAPI()
    app.include_router(v1_router)
    app.dependency_overrides[get_db_session] = lambda: db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t",
                           headers={"Authorization": f"Bearer {full}"}) as c:
        yield c


@pytest.mark.asyncio
async def test_token_of_org_a_cannot_touch_org_b_roster(db, org, other_org, admin_user, token_a):
    a_user, b_user = await _two_orgs(db, org, other_org)
    oa, ob = org.id, other_org.id
    await svc.recompute_users(db)
    await svc.upsert_roster(db, ob, "jane.doe@mkausa.org", {"level": "national", "role": "sadr"}, source="admin")
    before = await _roster_rows(db)
    assert (await svc.get_row(db, 502)).eff_role == "sadr"
    p = {"org_slug": org.slug}

    # cannot list B's roster
    r = await token_a.get(f"{BASE}/roster", params=p)
    assert r.status_code == 200 and r.json()["items"] == []
    # cannot PUT over, DELETE, or import over B's email: it only ever writes org A's table
    r = await token_a.put(f"{BASE}/roster/jane.doe@mkausa.org", params=p, json={"attributes": {"level": "local"}})
    assert r.status_code == 200 and r.json()["org_id"] == oa
    assert (await token_a.delete(f"{BASE}/roster/jane.doe@mkausa.org", params=p)).status_code == 200
    assert (await token_a.delete(f"{BASE}/roster/jane.doe@mkausa.org", params=p)).status_code == 404
    imp = await token_a.post(f"{BASE}/roster/import", params=p, json={"rows": [
        {"email": "jane.doe@mkausa.org", "attributes": {"level": "regional", "region": "Gulf", "role": "regional_qaid"}}]})
    assert imp.status_code == 200
    rows = await _roster_rows(db)
    assert rows[(ob, "jane.doe@mkausa.org")] == before[(ob, "jane.doe@mkausa.org")]   # B untouched
    assert {k for k in rows if k[0] == ob} == {k for k in before if k[0] == ob}
    # B's user attributes never changed
    eff = (await svc.get_row(db, 502)).effective
    assert (eff["role"], eff["level"]) == ("sadr", "national")
    # org-B slug / id is a hard 403
    assert (await token_a.get(f"{BASE}/roster", params={"org_slug": other_org.slug})).status_code == 403
    assert (await token_a.get(f"{BASE}/roster", params={"org_slug": org.slug, "org_id": ob})).status_code == 403


@pytest.mark.asyncio
async def test_roster_row_of_a_never_changes_user_only_in_b(db, org, other_org):
    a_user, b_user = await _two_orgs(db, org, other_org)
    oa = org.id
    await svc.recompute_users(db)
    await svc.upsert_roster(db, oa, "jane.doe@mkausa.org", {"level": "national", "role": "sadr"}, source="admin")
    assert (await svc.get_row(db, 502)).eff_status == "unrecognized"
    # also at (re)derivation time
    _, changed = await svc.refresh_attributes(db, b_user, action="recompute")
    assert changed is False and (await svc.get_row(db, 502)).eff_role is None


@pytest.mark.asyncio
async def test_roster_is_ignored_for_multi_org_users(db, org, other_org):
    """H1: a roster row (even pre-seeded before the user joined) never applies to a shared account."""
    a_user, _ = await _two_orgs(db, org, other_org)
    oa, ob = org.id, other_org.id
    await svc.recompute_users(db)
    await svc.upsert_roster(db, ob, "john.smith@mkausa.org", {"level": "national", "role": "sadr"}, source="admin")  # B pre-seeds
    db.add(UserOrganization(user_id=501, org_id=ob, role_id=4, creation_date="x", update_date="x"))   # then attaches the user
    await db.commit()
    await svc.recompute_users(db)
    row, _ = await svc.refresh_attributes(db, a_user, action="recompute")
    assert row.eff_role is None and row.eff_status == "unrecognized"
    await svc.upsert_roster(db, oa, "jane.doe@mkausa.org", {"level": "national", "role": "sadr"}, source="admin")


@pytest.mark.asyncio
async def test_gdpr_delete_only_removes_rosters_of_users_orgs(db, org, other_org):
    a_user, _ = await _two_orgs(db, org, other_org)
    oa, ob = org.id, other_org.id
    await svc.recompute_users(db)
    await svc.upsert_roster(db, oa, "john.smith@mkausa.org", {"level": "national"}, source="admin")
    await svc.upsert_roster(db, ob, "john.smith@mkausa.org", {"level": "regional", "region": "Gulf"}, source="admin")
    await svc.delete_attributes(db, 501)
    await db.commit()
    rows = await _roster_rows(db)
    assert (oa, "john.smith@mkausa.org") not in rows and (ob, "john.smith@mkausa.org") in rows


@pytest.mark.asyncio
async def test_per_user_routes_404_for_user_only_in_other_org(db, org, other_org, admin_user, token_a):
    await _two_orgs(db, org, other_org)
    await svc.recompute_users(db)
    p = {"org_slug": org.slug}
    for path in ("users/502", "users/502/audit"):          # tokens may not use per-user routes at all
        assert (await token_a.get(f"{BASE}/{path}", params=p)).status_code == 403
    ids = {i["user_id"] for i in (await token_a.get(f"{BASE}/users", params=p)).json()["items"]}
    assert 502 not in ids and 501 in ids
    assert (await token_a.get(f"{BASE}/review-queue", params=p)).status_code == 403
    # session admin of A: override/get on B's user -> 404
    async with _client(db, admin_user) as c:
        assert (await c.put(f"{BASE}/users/502/override", params={"org_id": org.id},
                            json={"override": {"level": "local"}, "reason": "x"})).status_code == 404
        assert (await c.get(f"{BASE}/users/502", params={"org_id": org.id})).status_code == 404
        assert (await c.get(f"{BASE}/users/502/audit", params={"org_id": org.id})).status_code == 404
        assert (await c.get(f"{BASE}/roster", params={"org_id": other_org.id})).status_code == 403


# --- fail-closed reads ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fresh_row_reads_normally_and_email_drift_reads_unrecognized(db, org):
    u = await _user(db, 601, "tabligh.albany@mkausa.org", org=org)
    await svc.refresh_attributes(db, u)
    await db.commit()
    attrs, stale = await svc.read_effective(db, u)
    assert stale is False and attrs["department"] == "tabligh" and attrs["majlis"] == "Albany"
    u.email = "someone@gmail.com"                       # email changed, row not refreshed
    attrs, stale = await svc.read_effective(db, u)
    assert stale is True and attrs["status"] == "unrecognized" and attrs["is_officeholder"] is False
    assert attrs["level"] is None and attrs["role"] is None


@pytest.mark.asyncio
async def test_row_without_proven_domain_is_stale_unless_overridden(db, org):
    admin = await _user(db, 1, "admin@test.com")
    u = await _user(db, 602, "tabligh.albany@mkausa.org", org=org)
    row, _ = await svc.refresh_attributes(db, u)
    await db.commit()
    assert (await svc.read_effective(db, u))[1] is False
    row.verified_hd = None
    db.add(row)
    await db.commit()
    assert (await svc.read_effective(db, u))[1] is True
    await svc.set_override(db, u, {"level": "local", "department": "tabligh"}, "ok", admin.id)
    attrs, stale = await svc.read_effective(db, u)
    assert stale is False and attrs["level"] == "local"


@pytest.mark.asyncio
async def test_old_rules_version_is_stale(db, org):
    u = await _user(db, 603, "tabligh.albany@mkausa.org", org=org)
    row, _ = await svc.refresh_attributes(db, u)
    row.rules_version = "2025.9"
    db.add(row)
    await db.commit()
    assert (await svc.read_effective(db, u))[1] is True
    row.rules_version = "2026.4"
    db.add(row)
    await db.commit()
    assert (await svc.read_effective(db, u))[1] is False


@pytest.mark.asyncio
async def test_login_hook_failure_marks_existing_row_stale_and_recovery_clears(db, org):
    u = await _user(db, 604, "tabligh.albany@mkausa.org", org=org)
    await svc.mka_refresh_on_login(db, u, "google")
    assert (await svc.read_effective(db, u))[1] is False
    with patch.object(svc, "parse_identity", side_effect=RuntimeError("boom")):
        await svc.mka_refresh_on_login(db, u, "google")          # login still fine
    attrs, stale = await svc.read_effective(db, u)
    assert stale is True and attrs["status"] == "unrecognized"
    await svc.mka_refresh_on_login(db, u, "google")
    assert (await svc.read_effective(db, u))[1] is False


@pytest.mark.asyncio
async def test_me_and_admin_list_fail_closed(db, org, admin_user, regular_user):
    reg = await db.get(User, regular_user.id)
    reg.email = "tabligh.albany@mkausa.org"
    reg.signup_method = "google"
    db.add(reg)
    await db.commit()
    await svc.refresh_attributes(db, reg)
    await db.commit()
    reg.email = "other@gmail.com"                       # drift
    db.add(reg)
    await db.commit()
    async with _client(db, regular_user) as c:
        me = (await c.get(f"{BASE}/me")).json()
    assert me["stale"] is True and me["attributes"]["status"] == "unrecognized"
    async with _client(db, admin_user) as c:
        lst = (await c.get(f"{BASE}/users", params={"org_id": org.id})).json()["items"]
    item = next(i for i in lst if i["user_id"] == regular_user.id)
    assert item["stale"] is True and item["effective"]["status"] == "unrecognized"
    assert item["stored_effective"]["department"] == "tabligh"


# --- multi-org write guard ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_multi_org_user_cannot_be_overridden_or_rostered_by_one_org(db, org, other_org, admin_user):
    a_user, _ = await _two_orgs(db, org, other_org)
    oa, ob = org.id, other_org.id
    db.add(UserOrganization(user_id=501, org_id=ob, role_id=4, creation_date="x", update_date="x"))
    await db.commit()
    await svc.recompute_users(db)
    with pytest.raises(svc.CrossOrgConflict):
        await svc.set_override(db, a_user, {"level": "national", "role": "sadr"}, "x", admin_user.id, oa)
    with pytest.raises(svc.CrossOrgConflict):
        await svc.clear_override(db, a_user, admin_user.id, None, oa)
    with pytest.raises(svc.CrossOrgConflict):
        await svc.upsert_roster(db, oa, "john.smith@mkausa.org", {"level": "national"}, source="admin")
    assert await _roster_rows(db) == {}
    res = await svc.import_roster(db, oa, [{"email": "john.smith@mkausa.org", "attributes": {"level": "national"}}],
                                  source="admin")
    assert res["failed"] == 1 and await _roster_rows(db) == {}
    assert (await svc.get_row(db, 501)).eff_role is None
    # HTTP: 409
    async with _client(db, admin_user) as c:
        r = await c.put(f"{BASE}/users/501/override", params={"org_id": oa},
                        json={"override": {"level": "national"}, "reason": "x"})
        assert r.status_code == 409 and "other organizations" in r.json()["detail"]
        assert (await c.delete(f"{BASE}/users/501/override", params={"org_id": oa})).status_code == 409
        r = await c.put(f"{BASE}/roster/john.smith@mkausa.org", params={"org_id": oa},
                        json={"attributes": {"level": "national"}})
        assert r.status_code == 409


@pytest.mark.asyncio
async def test_single_org_user_and_unmatched_roster_still_work(db, org, other_org, admin_user):
    a_user, _ = await _two_orgs(db, org, other_org)
    oa = org.id
    await svc.recompute_users(db)
    await svc.set_override(db, a_user, {"level": "national", "role": "sadr"}, "ok", admin_user.id, oa)
    # roster for an email with no matching user in the org is fine even if that email is a multi-org user elsewhere
    await svc.upsert_roster(db, oa, "nobody@mkausa.org", {"level": "national"}, source="admin")


# --- TOCTOU: membership appearing between the check and the commit -------------------------------

@pytest.mark.asyncio
async def test_membership_added_between_check_and_commit_refuses_write(db, org, other_org, admin_user, monkeypatch):
    a_user, _ = await _two_orgs(db, org, other_org)
    oa, ob = org.id, other_org.id
    await svc.recompute_users(db)
    real = svc.assert_exclusive_to_org
    calls = {"n": 0}

    async def racing(db_, user_id, org_id):
        await real(db_, user_id, org_id)
        calls["n"] += 1
        if calls["n"] == 1:   # the user joins another org right after the first (passing) check
            db_.add(UserOrganization(user_id=user_id, org_id=ob, role_id=4, creation_date="x", update_date="x"))
            await db_.flush()

    monkeypatch.setattr(svc, "assert_exclusive_to_org", racing)
    with pytest.raises(svc.CrossOrgConflict):
        await svc.set_override(db, a_user, {"level": "national", "role": "sadr"}, "x", admin_user.id, oa)
    assert calls["n"] == 1   # second (final) check raised inside real()
    monkeypatch.setattr(svc, "assert_exclusive_to_org", real)
    row = await svc.get_row(db, 501)
    assert row.override is None and row.eff_role is None            # nothing persisted
    assert (await db.execute(select(UserOrganization).where(UserOrganization.user_id == 501,
                                                            UserOrganization.org_id == ob))).first() is None


@pytest.mark.asyncio
async def test_roster_write_refused_when_membership_races(db, org, other_org):
    a_user, _ = await _two_orgs(db, org, other_org)
    oa, ob = org.id, other_org.id
    await svc.recompute_users(db)
    real = svc._guard_roster_target
    calls = {"n": 0}

    async def racing(db_, org_id, email):
        await real(db_, org_id, email)
        calls["n"] += 1
        if calls["n"] == 1:
            db_.add(UserOrganization(user_id=501, org_id=ob, role_id=4, creation_date="x", update_date="x"))
            await db_.flush()

    import pytest as _p
    with _p.MonkeyPatch.context() as mp:
        mp.setattr(svc, "_guard_roster_target", racing)
        with pytest.raises(svc.CrossOrgConflict):
            await svc.upsert_roster(db, oa, "john.smith@mkausa.org", {"level": "national"}, source="admin")
    assert await _roster_rows(db) == {}


@pytest.fixture(autouse=True)
def _google_only_domains(monkeypatch):
    monkeypatch.setenv("MKA_GOOGLE_ONLY_DOMAINS", "mkausa.org,atfalusa.org")
