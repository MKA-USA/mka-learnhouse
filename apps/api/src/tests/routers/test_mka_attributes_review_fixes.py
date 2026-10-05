"""Regression tests for the independent W1A review (REVIEW_W1A_ATTRIBUTES.md)."""

from datetime import datetime
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import IntegrityError

from src.core.events.database import get_db_session
from src.db.user_organizations import UserOrganization
from src.db.users import User
from src.security.api_token_utils import require_authenticated_user_or_api_token
from src.security.auth import get_authenticated_user, get_current_user
from src.services.auth.mka_google_only import require_workspace_hd
from src.services.auth.session import issue_session_or_challenge
from src.services.mka import attributes as svc

BASE = "/api/v1/mka/attributes"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("MKA_GOOGLE_ONLY_DOMAINS", "mkausa.org,atfalusa.org")


async def _user(db, uid, email, signup="google", org=None):
    now = str(datetime.now())
    u = User(id=uid, username=f"u{uid}", first_name="F", last_name="L", email=email, password="x",
             user_uuid=f"user_{uid}", signup_method=signup, creation_date=now, update_date=now)
    db.add(u)
    await db.commit()
    if org is not None:
        db.add(UserOrganization(user_id=uid, org_id=org.id, role_id=4, creation_date=now, update_date=now))
        await db.commit()
    return u


def _client(db, user):
    from src.router import v1_router

    app = FastAPI()
    app.include_router(v1_router)
    app.dependency_overrides[get_db_session] = lambda: db
    for dep in (get_current_user, get_authenticated_user, require_authenticated_user_or_api_token):
        app.dependency_overrides[dep] = lambda: user
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


# --- M1: hook is truly fail-open (commit failure must not break session minting) -------------

@pytest.mark.asyncio
async def test_m1_commit_failure_in_hook_does_not_break_login(db, org, monkeypatch):
    u = await _user(db, 10, "tabligh.albany@mkausa.org", org=org)
    real_commit = db.commit
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("connection blip")
        return await real_commit()

    monkeypatch.setattr(db, "commit", flaky)
    with patch("src.services.auth.session.is_mfa_active", return_value=False):
        result = await issue_session_or_challenge(db, u, amr="google")   # reads user.id/email after the hook
    assert result.access_token and not result.mfa_required


@pytest.mark.asyncio
async def test_m1_mark_stale_failure_does_not_break_login(db, org, monkeypatch):
    u = await _user(db, 11, "tabligh.albany@mkausa.org", org=org)
    async def boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(svc, "refresh_attributes", boom)
    monkeypatch.setattr(db, "commit", boom)
    with patch("src.services.auth.session.is_mfa_active", return_value=False):
        result = await issue_session_or_challenge(db, u, amr="google")
    assert result.access_token


# --- L1: lost insert race must not mark the winner's row stale -------------------------------

@pytest.mark.asyncio
async def test_l1_integrity_error_does_not_mark_stale(db, org):
    u = await _user(db, 12, "tabligh.albany@mkausa.org", org=org)
    require_workspace_hd(u.email, "mkausa.org")
    await svc.mka_refresh_on_login(db, u, "google")
    assert (await svc.read_effective(db, u))[1] is False

    async def race(*a, **k):
        raise IntegrityError("insert", {}, Exception("dup"))

    with patch.object(svc, "refresh_attributes", race):
        await svc.mka_refresh_on_login(db, u, "google")
    assert (await svc.read_effective(db, u))[1] is False


# --- M2: partial layers never promote -----------------------------------------------------------

@pytest.mark.asyncio
async def test_m2_partial_override_does_not_promote_gmail_member(db, org):
    admin = await _user(db, 1, "admin@test.com")
    u = await _user(db, 20, "someone@gmail.com", org=org)
    await svc.refresh_attributes(db, u)
    await db.commit()
    row = await svc.set_override(db, u, {"majlis": "Albany"}, "fix majlis", admin.id, org.id)
    assert row.eff_status == "not_applicable" and row.eff_is_officeholder is False
    assert row.eff_majlis == "Albany" and row.eff_region == "Northeast"
    attrs, stale = await svc.read_effective(db, u)
    assert attrs["is_officeholder"] is False and attrs["status"] == "not_applicable"


@pytest.mark.asyncio
async def test_m2_partial_roster_does_not_promote_and_role_does(db, org):
    u = await _user(db, 21, "someone@gmail.com", org=org)
    await svc.upsert_roster(db, org.id, "someone@gmail.com", {"majlis": "Albany"}, source="companion")
    await svc.refresh_attributes(db, u)
    await db.commit()
    assert (await svc.get_row(db, 21)).eff_is_officeholder is False
    await svc.upsert_roster(db, org.id, "someone@gmail.com", {"level": "local", "role": "nazim_dept", "department": "tabligh"}, source="companion")
    assert (await svc.get_row(db, 21)).eff_status == "matched"          # says what the person holds


def test_l3_not_applicable_cannot_carry_a_role():
    from src.services.mka.identity_parser import load_rules

    with pytest.raises(ValueError):
        svc.validate_layer({"status": "not_applicable", "is_officeholder": True}, load_rules())


# --- L2: type-confused payloads are clean errors -----------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [{"majlis": []}, {"department": {}}, {"role": ["x"]}, {"region": [1]}])
async def test_l2_unhashable_values_are_validation_errors(db, org, bad):
    with pytest.raises(ValueError):
        svc.validate_layer(bad, svc.get_rules())


@pytest.mark.asyncio
async def test_l2_bad_row_does_not_abort_roster_import_or_500(db, org, admin_user):
    res = await svc.import_roster(db, org.id, [
        {"email": "a.one@mkausa.org", "attributes": {"majlis": []}},
        {"email": "b.two@mkausa.org", "attributes": {"level": "national", "role": "sadr"}},
    ], source="companion")
    assert (res["applied"], res["failed"]) == (1, 1)
    await _user(db, 22, "john.smith@mkausa.org", org=org)
    async with _client(db, admin_user) as c:
        r = await c.put(f"{BASE}/users/22/override", params={"org_id": org.id}, json={"override": {"majlis": []}, "reason": "x"})
    assert r.status_code == 422


# --- M3 / H2 / M6: proof of Workspace ownership --------------------------------------------------------

@pytest.mark.asyncio
async def test_m2m3_unverified_account_gets_no_row_and_override_stays_blank_derived(db, org):
    admin = await _user(db, 1, "admin@test.com")
    u = await _user(db, 30, "nazim.albany@atfalusa.org", signup="password", org=org)
    c = await svc.recompute_users(db, org_id=org.id)
    assert c["processed"] == 0 and await svc.get_row(db, 30) is None
    row = await svc.set_override(db, u, {"majlis": "Albany"}, "x", admin.id, org.id)     # the reviewer's laundering step
    assert row.derived["status"] == "unrecognized" and row.derived["department"] is None
    attrs, _ = await svc.read_effective(db, u)
    assert attrs["status"] == "unrecognized" and not attrs["department"] and attrs["is_officeholder"] is not True


@pytest.mark.asyncio
async def test_h2_consumer_google_account_on_officeholder_domain_gets_nothing(db, org, monkeypatch):
    monkeypatch.delenv("MKA_GOOGLE_ONLY_DOMAINS")                      # domain not configured Google-only
    u = await _user(db, 31, "nazim.albany@atfalusa.org", signup="google", org=org)
    require_workspace_hd(u.email, None)                                # consumer account: no hd claim
    await svc.mka_refresh_on_login(db, u, "google")
    row = await svc.get_row(db, 31)
    assert row.derived["status"] == "unrecognized" and row.eff_department is None
    attrs, stale = await svc.read_effective(db, u)
    assert attrs["status"] == "unrecognized" and attrs["is_officeholder"] is False and stale is True
    # recompute cannot create proof either
    await svc.recompute_users(db)
    assert (await svc.get_row(db, 31)).derived["status"] == "unrecognized"


@pytest.mark.asyncio
async def test_h2_hd_claim_equal_to_domain_proves_ownership_even_if_unconfigured(db, org, monkeypatch):
    monkeypatch.delenv("MKA_GOOGLE_ONLY_DOMAINS")
    u = await _user(db, 32, "nazim.albany@atfalusa.org", signup="google", org=org)
    require_workspace_hd(u.email, "atfalusa.org")
    await svc.mka_refresh_on_login(db, u, "google")
    row = await svc.get_row(db, 32)
    assert row.verified_hd == "atfalusa.org" and row.eff_department == "atfal" and row.eff_status == "matched"
    assert (await svc.read_effective(db, u))[1] is False
    await svc.recompute_users(db)                                      # proof persisted on the row
    assert (await svc.get_row(db, 32)).eff_department == "atfal"


@pytest.mark.asyncio
async def test_h2_mismatched_hd_does_not_prove(db, org, monkeypatch):
    monkeypatch.delenv("MKA_GOOGLE_ONLY_DOMAINS")
    u = await _user(db, 33, "nazim.albany@atfalusa.org", signup="google", org=org)
    require_workspace_hd(u.email, "evil.example")
    await svc.mka_refresh_on_login(db, u, "google")
    assert (await svc.get_row(db, 33)).derived["status"] == "unrecognized"


@pytest.mark.asyncio
async def test_h2_proof_of_another_email_is_not_reused(db, org, monkeypatch):
    monkeypatch.delenv("MKA_GOOGLE_ONLY_DOMAINS")
    u = await _user(db, 34, "nazim.albany@atfalusa.org", signup="google", org=org)
    require_workspace_hd("someone.else@atfalusa.org", "atfalusa.org")
    await svc.mka_refresh_on_login(db, u, "google")
    assert (await svc.get_row(db, 34)).derived["status"] == "unrecognized"


@pytest.mark.asyncio
async def test_m6_invited_account_gets_attributes_on_first_google_login(db, org):
    """Provisioned (admin_api / invited / legacy password) account, first Google sign-in with a valid hd."""
    for uid, method in ((40, "admin_api"), (41, "email"), (42, None)):
        u = await _user(db, uid, f"tabligh.albany+{uid}@mkausa.org", signup=method, org=org)
        assert await svc.get_row(db, uid) is None
        require_workspace_hd(u.email, "mkausa.org")
        with patch("src.services.auth.session.is_mfa_active", return_value=False):
            result = await issue_session_or_challenge(db, u, amr="google")
        assert result.access_token
        row = await svc.get_row(db, uid)
        assert row.eff_status == "matched" and row.eff_department == "tabligh" and row.verified_hd == "mkausa.org"
        attrs, stale = await svc.read_effective(db, u)
        assert attrs["majlis"] == "Albany" and stale is False
    # and a password login of such an account still derives nothing new
    await _user(db, 43, "tabligh.boston@mkausa.org", signup="email", org=org)
    await svc.mka_refresh_on_login(db, await db.get(User, 43), "password")
    assert await svc.get_row(db, 43) is None


@pytest.mark.asyncio
async def test_m3_include_non_google_is_refused_over_http(db, org, admin_user):
    async with _client(db, admin_user) as c:
        r = await c.post(f"{BASE}/recompute", params={"org_id": org.id}, json={"include_non_google": True})
    assert r.status_code == 422


# --- N1: proof is per ADDRESS ------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_n1_proof_does_not_transfer_to_a_changed_email(db, org, monkeypatch):
    monkeypatch.delenv("MKA_GOOGLE_ONLY_DOMAINS")                      # domain NOT Google-only (the premise)
    u = await _user(db, 70, "john.doe@atfalusa.org", signup="google", org=org)
    require_workspace_hd(u.email, "atfalusa.org")
    await svc.mka_refresh_on_login(db, u, "google")
    assert (await svc.get_row(db, 70)).verified_hd == "atfalusa.org"
    u.email = "nazim.albany@atfalusa.org"                              # self-service email change
    db.add(u)
    await db.commit()
    row, _ = await svc.refresh_attributes(db, u, action="recompute")   # admin recompute / backfill / roster write
    await db.commit()
    assert row.eff_status == "unrecognized" and row.eff_department is None and row.verified_hd is None
    await svc.upsert_roster(db, org.id, "nazim.albany@atfalusa.org", {"majlis": "Albany"}, source="companion")
    assert (await svc.get_row(db, 70)).eff_department is None
    attrs, stale = await svc.read_effective(db, u)
    assert attrs["status"] == "unrecognized" and attrs["department"] is None
    # the NEW address is trusted only after a Google login proves it
    require_workspace_hd(u.email, "atfalusa.org")
    await svc.mka_refresh_on_login(db, u, "google")        # runs in its own session
    db.expire_all()
    assert (await svc.get_row(db, 70)).eff_department == "atfal"


# --- R1: the hook is fully fail-open even when the DB (and any reload) is down ----------------------------------

@pytest.mark.asyncio
async def test_r1_hook_never_raises_and_never_touches_callers_session(db, org, monkeypatch):
    u = await _user(db, 80, "tabligh.albany@mkausa.org", org=org)
    require_workspace_hd(u.email, "mkausa.org")

    class Down:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            raise RuntimeError("database unreachable")

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(svc, "_new_session", lambda db_: Down())

    async def boom(*a, **k):
        raise RuntimeError("caller session must not be used")

    monkeypatch.setattr(db, "commit", boom)
    monkeypatch.setattr(db, "rollback", boom)
    monkeypatch.setattr(db, "refresh", boom)
    await svc.mka_refresh_on_login(db, u, "google")          # must not raise
    with patch("src.services.auth.session.is_mfa_active", return_value=False):
        result = await issue_session_or_challenge(db, u, amr="google")
    assert result.access_token


FULL_ACCESS = {"courses": {"action_read": True, "action_update": True}, "assignments": {"action_read": True}}


# --- M5: token rights ------------------------------------------------------------------------------------------------

def _token_client(db, org, admin_user, rights):
    from src.db.api_tokens import APIToken
    from src.services.api_tokens.api_tokens import generate_api_token
    from src.router import v1_router

    full, prefix, hashed = generate_api_token()
    db.add(APIToken(name=f"t{len(str(rights))}", token_uuid=f"apitoken_{prefix}", token_prefix=prefix, token_hash=hashed,
                    org_id=org.id, created_by_user_id=admin_user.id, rights=rights,
                    creation_date=str(datetime.now()), update_date=str(datetime.now())))
    app = FastAPI()
    app.include_router(v1_router)
    app.dependency_overrides[get_db_session] = lambda: db
    return db, AsyncClient(transport=ASGITransport(app=app), base_url="http://t", headers={"Authorization": f"Bearer {full}"})


@pytest.mark.asyncio
async def test_m5_token_rights_are_enforced(db, org, admin_user):
    from src.db.organization_config import OrganizationConfig

    db.add(OrganizationConfig(org_id=org.id, config={"config_version": "2.0"},
                              creation_date=str(datetime.now()), update_date=str(datetime.now())))
    await db.commit()
    p = {"org_slug": org.slug}
    body = {"attributes": {"level": "national", "role": "sadr"}}
    cases = [
        ({}, 403, 403),                                                              # empty rights refused
        ({"search": {"action_read": True}}, 403, 403),                               # unrelated rights
        ({"courses": {"action_read": True}, "assignments": {"action_read": True}}, 200, 403),   # read only
        ({"courses": {"action_update": True}}, 403, 200),                            # write only
        (FULL_ACCESS, 200, 200),
    ]
    for rights, read_status, write_status in cases:
        _, c = _token_client(db, org, admin_user, rights)
        await db.commit()
        async with c:
            assert (await c.get(f"{BASE}/users", params=p)).status_code == read_status, rights
            assert (await c.get(f"{BASE}/roster", params=p)).status_code == read_status, rights
            assert (await c.put(f"{BASE}/roster/x.y@mkausa.org", params=p, json=body)).status_code == write_status, rights
            assert (await c.delete(f"{BASE}/roster/x.y@mkausa.org", params=p)).status_code in (write_status, 404) if write_status == 200 else True


# --- M4: other orgs' admin notes are redacted ------------------------------------------------------------

@pytest.mark.asyncio
async def test_m4_shared_user_override_details_are_redacted(db, org, other_org, admin_user):

    admin = await db.get(User, 1)
    u = await _user(db, 50, "john.smith@mkausa.org", org=org)
    await svc.refresh_attributes(db, u)
    await db.commit()
    await svc.set_override(db, u, {"level": "national", "role": "sadr"}, "org A secret note", admin.id, org.id)
    async with _client(db, admin_user) as c:
        mine = (await c.get(f"{BASE}/users/50", params={"org_id": org.id})).json()
        assert mine["override_reason"] == "org A secret note" and mine["redacted"] is False
        db.add(UserOrganization(user_id=50, org_id=other_org.id, role_id=4, creation_date="x", update_date="x"))
        await db.commit()
        shared = (await c.get(f"{BASE}/users/50", params={"org_id": org.id})).json()
        assert shared["redacted"] is True and shared["override_reason"] is None and shared["override_by"] is None
        assert shared["override"] is None
        lst = (await c.get(f"{BASE}/users", params={"org_id": org.id})).json()["items"]
        assert all(i["override_reason"] is None for i in lst if i["user_id"] == 50)
        assert (await c.get(f"{BASE}/users/50/audit", params={"org_id": org.id})).status_code == 403


# --- M7: SQL filters honour fail-closed ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_m7_filters_exclude_stale_rows(db, org):
    a = await _user(db, 60, "tabligh.albany@mkausa.org", org=org)
    await _user(db, 61, "tabligh.boston@mkausa.org", org=org)
    await svc.recompute_users(db)
    assert (await svc.list_attributes(db, org.id, filters={"department": "tabligh"}))["total"] == 2
    row = await svc.get_row(db, 61)
    row.stale = True
    db.add(row)
    await db.commit()
    assert (await svc.list_attributes(db, org.id, filters={"department": "tabligh"}))["total"] == 1
    assert (await svc.list_attributes(db, org.id, filters={"majlis": "Boston"}))["total"] == 0
    st = await svc.list_attributes(db, org.id, filters={"status": ["unrecognized"]})
    assert [i["user_id"] for i in st["items"]] == [61] and st["items"][0]["effective"]["status"] == "unrecognized"
    assert (await svc.list_attributes(db, org.id, filters={"status": ["matched"]}))["total"] == 1
    # email drift is stale too
    a.email = "other@gmail.com"
    db.add(a)
    await db.commit()
    assert (await svc.list_attributes(db, org.id, filters={"department": "tabligh"}))["total"] == 0
