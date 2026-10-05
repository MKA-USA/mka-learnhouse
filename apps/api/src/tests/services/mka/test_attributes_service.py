"""MKA fork: attribute store/service (spec A2/A5/A7/A9, B8 store tests)."""

from datetime import datetime
from unittest.mock import patch

import pytest
from sqlmodel import select

from src.db.mka_user_attributes import (
    MkaRosterOverride,
    MkaUserAttributes,
    MkaUserAttributesAudit,
)
from src.db.user_organizations import UserOrganization
from src.db.users import User
from src.services.mka import attributes as svc
from src.services.mka.identity_parser import load_rules

RULES = load_rules()


async def _user(db, uid, email, signup_method="google", org=None, role_id=None):
    u = User(
        id=uid, username=f"u{uid}", first_name="F", last_name="L", email=email,
        password="x", user_uuid=f"user_{uid}", signup_method=signup_method,
        creation_date=str(datetime.now()), update_date=str(datetime.now()),
    )
    db.add(u)
    await db.commit()
    if org is not None:
        db.add(UserOrganization(user_id=uid, org_id=org.id, role_id=role_id or 1,
                                creation_date=str(datetime.now()), update_date=str(datetime.now())))
        await db.commit()
    return u


async def _audit(db, uid):
    return (await db.execute(
        select(MkaUserAttributesAudit).where(MkaUserAttributesAudit.user_id == uid)
        .order_by(MkaUserAttributesAudit.id)
    )).scalars().all()


# --- compute_effective / validate ---------------------------------------------------------

def test_effective_equals_derived_without_layers():
    derived = {"status": "matched", "is_officeholder": True, "level": "local", "department": "tabligh",
               "role": "nazim_dept", "role_title": "Nazim Tabligh", "majlis": "Albany",
               "region": "Northeast", "source": "parser", "flags": []}
    eff = svc.compute_effective(derived, None, None, RULES)
    assert eff == derived


def test_precedence_override_beats_roster_beats_parser():
    derived = {"status": "unrecognized", "is_officeholder": None, "level": None, "department": None,
               "role": None, "role_title": None, "majlis": None, "region": None, "source": "parser",
               "flags": ["needs_review"]}
    roster = {"level": "national", "role": "naib_sadr"}
    eff = svc.compute_effective(derived, roster, None, RULES)
    assert (eff["status"], eff["level"], eff["role"], eff["source"]) == ("matched", "national", "naib_sadr", "roster")
    assert eff["role_title"] == "Naib Sadr" and eff["is_officeholder"] is True
    assert "needs_review" not in eff["flags"]
    eff2 = svc.compute_effective(derived, roster, {"role": "sadr"}, RULES)
    assert (eff2["role"], eff2["level"], eff2["source"]) == ("sadr", "national", "admin")


def test_override_majlis_derives_region_and_title():
    derived = {"status": "partial", "is_officeholder": True, "level": None, "department": "tabligh",
               "role": "nazim_dept", "role_title": "Nazim Tabligh", "majlis": None, "region": None,
               "source": "parser", "flags": []}
    eff = svc.compute_effective(derived, None, {"majlis": "Boston", "level": "local"}, RULES)
    assert (eff["majlis"], eff["region"], eff["level"], eff["status"]) == ("Boston", "Northeast", "local", "matched")


def test_explicit_status_in_override_is_respected():
    derived = {"status": "matched", "is_officeholder": True, "level": "local", "department": "tabligh",
               "role": "nazim_dept", "role_title": "x", "majlis": "Albany", "region": "Northeast",
               "source": "parser", "flags": []}
    eff = svc.compute_effective(derived, None, {"status": "not_applicable", "is_officeholder": False}, RULES)
    assert (eff["status"], eff["is_officeholder"]) == ("not_applicable", False)


@pytest.mark.parametrize("bad", [
    {}, None, "x", {"bogus": 1}, {"status": "weird"}, {"level": "galactic"}, {"department": "nope"},
    {"role": "nope"}, {"majlis": "Atlantis"}, {"region": "Mars"},
    {"majlis": "Boston", "region": "Gulf"}, {"is_officeholder": "yes"}, {"role_title": "x" * 101},
    {"source": "admin"}, {"flags": []},
])
def test_validate_layer_rejects(bad):
    with pytest.raises(ValueError):
        svc.validate_layer(bad, RULES)


def test_validate_layer_accepts_and_keeps_nulls():
    out = svc.validate_layer({"majlis": "Boston", "region": "Northeast", "department": None}, RULES)
    assert out == {"majlis": "Boston", "region": "Northeast", "department": None}


# --- refresh: idempotent store -----------------------------------------------------------

@pytest.mark.asyncio
async def test_refresh_creates_row_and_audit(db):
    u = await _user(db, 10, "Tabligh.Albany@mkausa.org")
    row, changed = await svc.refresh_attributes(db, u)
    await db.commit()
    assert changed and row.email_seen == "tabligh.albany@mkausa.org"
    assert row.eff_status == "matched" and row.eff_majlis == "Albany" and row.eff_department == "tabligh"
    assert row.rules_version == "2026.1"
    a = await _audit(db, 10)
    assert [x.action for x in a] == ["derive"] and a[0].actor_user_id is None


@pytest.mark.asyncio
async def test_recompute_is_idempotent_no_audit_when_unchanged(db):
    u = await _user(db, 11, "qaid.northeast@mkausa.org")
    await svc.refresh_attributes(db, u)
    await db.commit()
    for _ in range(3):
        _, changed = await svc.refresh_attributes(db, u, action="recompute")
        await db.commit()
        assert changed is False
    assert len(await _audit(db, 11)) == 1


@pytest.mark.asyncio
async def test_email_change_rederives_and_audits(db):
    u = await _user(db, 12, "tabligh.albany@mkausa.org")
    await svc.refresh_attributes(db, u)
    u.email = "tabligh.boston@mkausa.org"
    _, changed = await svc.refresh_attributes(db, u)
    await db.commit()
    row = await svc.get_row(db, 12)
    assert changed and row.eff_majlis == "Boston"
    assert [x.action for x in await _audit(db, 12)] == ["derive", "derive"]


@pytest.mark.asyncio
async def test_rules_version_bump_rewrites_without_audit(db):
    u = await _user(db, 13, "tabligh.albany@mkausa.org")
    await svc.refresh_attributes(db, u)
    await db.commit()
    row = await svc.get_row(db, 13)
    row.rules_version = "2025.0"
    db.add(row)
    await db.commit()
    _, changed = await svc.refresh_attributes(db, u, action="recompute")
    await db.commit()
    assert changed is False  # derived value unchanged
    assert (await svc.get_row(db, 13)).rules_version == "2026.1"
    assert len(await _audit(db, 13)) == 1


@pytest.mark.asyncio
async def test_non_officeholder_stored_as_not_applicable(db):
    u = await _user(db, 14, "someone@gmail.com")
    row, _ = await svc.refresh_attributes(db, u)
    await db.commit()
    assert row.eff_status == "not_applicable" and row.eff_is_officeholder is False


# --- override / roster layers over the store ------------------------------------------------

@pytest.mark.asyncio
async def test_override_survives_recompute_and_clear_restores(db):
    admin = await _user(db, 1, "admin@test.com")
    u = await _user(db, 15, "john.smith@mkausa.org")
    await svc.refresh_attributes(db, u)
    await db.commit()
    assert (await svc.get_row(db, 15)).eff_status == "unrecognized"

    row = await svc.set_override(db, u, {"level": "national", "role": "sadr"}, "Confirmed by Aitmad", admin.id)
    assert (row.eff_status, row.eff_role, row.eff_level) == ("matched", "sadr", "national")
    assert row.override_by == admin.id and row.override_reason == "Confirmed by Aitmad"

    _, changed = await svc.refresh_attributes(db, u, action="recompute")
    await db.commit()
    assert changed is False and (await svc.get_row(db, 15)).eff_role == "sadr"

    row = await svc.clear_override(db, u, admin.id, "mistake")
    assert row.override is None and row.eff_status == "unrecognized" and row.eff_role is None
    actions = [a.action for a in await _audit(db, 15)]
    assert actions == ["derive", "override_set", "override_clear"]
    audit = await _audit(db, 15)
    assert audit[1].actor_user_id == admin.id and audit[1].reason == "Confirmed by Aitmad"


@pytest.mark.asyncio
async def test_override_requires_reason_and_valid_layer(db):
    admin = await _user(db, 1, "admin@test.com")
    u = await _user(db, 16, "x.y@mkausa.org")
    with pytest.raises(ValueError):
        await svc.set_override(db, u, {"level": "local"}, "   ", admin.id)
    with pytest.raises(ValueError):
        await svc.set_override(db, u, {"level": "bogus"}, "why", admin.id)


@pytest.mark.asyncio
async def test_roster_before_user_exists_applies_at_first_login(db, org):
    await svc.upsert_roster(db, org.id, "M.Kauser@mkausa.org",
                            {"level": "national", "role": "naib_sadr"}, source="companion")
    u = await _user(db, 17, "m.kauser@mkausa.org", org=org)
    await svc.mka_refresh_on_login(db, u, "google")
    row = await svc.get_row(db, 17)
    assert row.derived["status"] == "unrecognized"          # parser alone cannot classify
    assert (row.eff_status, row.eff_role, row.eff_level) == ("matched", "naib_sadr", "national")
    assert row.effective["source"] == "roster"


@pytest.mark.asyncio
async def test_roster_change_updates_existing_row_and_audits(db, org):
    u = await _user(db, 18, "john.smith@mkausa.org", org=org)
    await svc.refresh_attributes(db, u)
    await db.commit()
    await svc.upsert_roster(db, org.id, "john.smith@mkausa.org", {"level": "regional", "region": "Gulf",
                                                          "role": "regional_qaid"}, source="admin")
    row = await svc.get_row(db, 18)
    assert (row.eff_level, row.eff_region, row.eff_role) == ("regional", "Gulf", "regional_qaid")
    assert (await _audit(db, 18))[-1].action == "roster_apply"
    assert await svc.delete_roster(db, org.id, "JOHN.SMITH@mkausa.org") is True
    assert (await svc.get_row(db, 18)).eff_status == "unrecognized"
    assert await svc.delete_roster(db, org.id, "john.smith@mkausa.org") is False


@pytest.mark.asyncio
async def test_roster_validation_and_bad_email(db, org):
    with pytest.raises(ValueError):
        await svc.upsert_roster(db, org.id, "not-an-email", {"level": "local"}, source="admin")
    with pytest.raises(ValueError):
        await svc.upsert_roster(db, org.id, "a@b.org", {"level": "bogus"}, source="admin")


@pytest.mark.asyncio
async def test_import_roster_partial_failure_and_dry_run(db, org):
    oid = org.id
    rows = [
        {"email": "a.one@mkausa.org", "attributes": {"level": "national", "role": "naib_sadr"}},
        {"email": "bad", "attributes": {"level": "national"}},
        {"email": "b.two@mkausa.org", "attributes": {"level": "nope"}},
    ]
    dry = await svc.import_roster(db, oid, rows, source="companion", dry_run=True)
    assert (dry["valid"], dry["failed"], dry["applied"]) == (1, 2, 0)
    assert await svc.get_roster_row(db, oid, "a.one@mkausa.org") is None
    res = await svc.import_roster(db, oid, rows, source="companion")
    assert (res["applied"], res["failed"]) == (1, 2)
    assert res["results"][1]["ok"] is False and "error" in res["results"][1]
    stored = await svc.get_roster_row(db, oid, "a.one@mkausa.org")
    assert stored.source == "companion"


# --- login hook ------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_login_hook_google_derives(db):
    u = await _user(db, 20, "tabligh.albany@mkausa.org")
    await svc.mka_refresh_on_login(db, u, "google")
    assert (await svc.get_row(db, 20)).eff_department == "tabligh"


@pytest.mark.asyncio
@pytest.mark.parametrize("amr", [None, "password", "magic_login", "sso", "api_token"])
async def test_login_hook_non_google_does_not_derive(db, amr):
    u = await _user(db, 21, "nazim.albany@atfalusa.org", signup_method="password")
    await svc.mka_refresh_on_login(db, u, amr)
    assert await svc.get_row(db, 21) is None


@pytest.mark.asyncio
async def test_login_hook_is_fail_open_when_parser_raises(db):
    u = await _user(db, 22, "tabligh.albany@mkausa.org")
    with patch.object(svc, "parse_identity", side_effect=RuntimeError("boom")):
        await svc.mka_refresh_on_login(db, u, "google")  # must not raise
    assert await svc.get_row(db, 22) is None


@pytest.mark.asyncio
async def test_login_hook_is_fail_open_when_db_write_fails(db):
    u = await _user(db, 23, "tabligh.albany@mkausa.org")

    async def boom(*a, **k):
        raise RuntimeError("db down")

    with patch.object(svc, "refresh_attributes", boom):
        await svc.mka_refresh_on_login(db, u, "google")  # must not raise
    # session is still usable afterwards
    assert (await db.execute(select(User).where(User.id == 23))).scalars().first() is not None


@pytest.mark.asyncio
async def test_login_hook_is_fail_open_when_rules_missing(db):
    u = await _user(db, 24, "tabligh.albany@mkausa.org")
    with patch.object(svc, "get_rules", side_effect=FileNotFoundError("no rules")):
        await svc.mka_refresh_on_login(db, u, "google")


# --- recompute / backfill ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recompute_google_only_and_counts(db, org):
    await _user(db, 30, "tabligh.albany@mkausa.org", "google", org)
    await _user(db, 31, "nazim.albany@atfalusa.org", "password", org)   # spoof attempt: excluded
    await _user(db, 32, "someone@gmail.com", "google", org)
    c = await svc.recompute_users(db, org_id=org.id)
    assert (c["processed"], c["created"], c["changed"], c["unchanged"]) == (2, 2, 0, 0)
    assert await svc.get_row(db, 31) is None
    c2 = await svc.recompute_users(db, org_id=org.id)
    assert (c2["created"], c2["changed"], c2["unchanged"]) == (0, 0, 2)
    assert len(await _audit(db, 30)) == 1   # idempotent: no new audit rows


@pytest.mark.asyncio
async def test_recompute_include_non_google_and_dry_run(db):
    await _user(db, 33, "tabligh.albany@mkausa.org", "password")
    dry = await svc.recompute_users(db, google_only=False, dry_run=True)
    assert dry["created"] == 1 and await svc.get_row(db, 33) is None
    real = await svc.recompute_users(db, google_only=False)
    assert real["created"] == 1 and await svc.get_row(db, 33) is not None


@pytest.mark.asyncio
async def test_recompute_batches(db):
    for i in range(7):
        await _user(db, 100 + i, f"tabligh.albany+{i}@mkausa.org")
    c = await svc.recompute_users(db, batch_size=3)
    assert c["processed"] == 7 and c["created"] == 7


@pytest.mark.asyncio
async def test_recompute_org_scope(db, org, other_org):
    await _user(db, 34, "tabligh.albany@mkausa.org", "google", org)
    await _user(db, 35, "tabligh.boston@mkausa.org", "google", other_org)
    c = await svc.recompute_users(db, org_id=org.id)
    assert c["processed"] == 1 and await svc.get_row(db, 35) is None


# --- listing ------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_filters_pagination_and_org_scope(db, org, other_org):
    emails = ["tabligh.albany@mkausa.org", "tabligh.boston@mkausa.org", "taleem.albany@mkausa.org",
              "qaid.northeast@mkausa.org", "john.smith@mkausa.org", "someone@gmail.com"]
    for i, e in enumerate(emails):
        await _user(db, 200 + i, e, "google", org)
    await _user(db, 299, "tabligh.albany+z@mkausa.org", "google", other_org)
    await svc.recompute_users(db)

    allr = await svc.list_attributes(db, org.id)
    assert allr["total"] == 6 and all(i["user_id"] != 299 for i in allr["items"])
    assert (await svc.list_attributes(db, org.id, filters={"department": "tabligh"}))["total"] == 2
    assert (await svc.list_attributes(db, org.id, filters={"level": "regional"}))["total"] == 1
    assert (await svc.list_attributes(db, org.id, filters={"region": "Northeast"}))["total"] == 4
    assert (await svc.list_attributes(db, org.id, filters={"majlis": "Albany"}))["total"] == 2
    assert (await svc.list_attributes(db, org.id, filters={"status": "unrecognized"}))["total"] == 1
    assert (await svc.list_attributes(db, org.id, filters={"status": "matched", "level": "local"}))["total"] == 3
    assert (await svc.list_attributes(db, org.id, q="BOSTON"))["total"] == 1
    p1 = await svc.list_attributes(db, org.id, page=1, page_size=4)
    p2 = await svc.list_attributes(db, org.id, page=2, page_size=4)
    assert len(p1["items"]) == 4 and len(p2["items"]) == 2 and p1["total"] == 6
    assert {i["user_id"] for i in p1["items"]}.isdisjoint({i["user_id"] for i in p2["items"]})
    item = p1["items"][0]
    assert {"effective", "derived", "override", "email", "user_id"} <= set(item)
    assert (await svc.list_attributes(db, org.id, page_size=10_000))["page_size"] == svc.MAX_PAGE_SIZE


@pytest.mark.asyncio
async def test_list_has_override_filter(db, org):
    admin = await _user(db, 1, "admin@test.com")
    u = await _user(db, 210, "john.smith@mkausa.org", "google", org)
    await _user(db, 211, "tabligh.albany@mkausa.org", "google", org)
    await svc.recompute_users(db)
    await svc.set_override(db, u, {"level": "national", "role": "sadr"}, "r", admin.id)
    assert (await svc.list_attributes(db, org.id, has_override=True))["total"] == 1
    assert (await svc.list_attributes(db, org.id, has_override=False))["total"] == 1


# --- GDPR ---------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_gdpr_export_and_delete(db, org):
    admin = await _user(db, 1, "admin@test.com")
    victim = await _user(db, 40, "john.smith@mkausa.org", "google", org)
    other = await _user(db, 41, "tabligh.albany@mkausa.org", "google", org)
    await svc.recompute_users(db)
    await svc.upsert_roster(db, org.id, "john.smith@mkausa.org", {"level": "national"}, source="admin",
                            actor_user_id=victim.id)
    await svc.set_override(db, other, {"majlis": "Boston"}, "r", victim.id)   # victim acted on `other`
    await svc.set_override(db, victim, {"role": "sadr"}, "r", admin.id)

    exp = await svc.export_attributes(db, 40)
    assert exp["email_seen"] == "john.smith@mkausa.org" and exp["effective"]["role"] == "sadr"
    assert [a["action"] for a in exp["audit"]][0] == "override_set"
    assert await svc.export_attributes(db, 9999) is None

    await svc.delete_attributes(db, 40)
    await db.commit()
    assert await svc.get_row(db, 40) is None
    assert await svc.get_roster_row(db, org.id, "john.smith@mkausa.org") is None
    assert await _audit(db, 40) == []
    # the victim is anonymised as an actor on someone else's history
    other_audit = await _audit(db, 41)
    assert all(a.actor_user_id != 40 for a in other_audit)
    assert (await svc.get_row(db, 41)).override_by is None
    assert (await svc.get_row(db, 41)).eff_majlis == "Boston"   # other's data untouched


@pytest.mark.asyncio
async def test_profile_status_includes_attributes_only_when_present(db):
    from src.services.users.mka_profile import profile_status, delete_profile

    u = await _user(db, 50, "tabligh.albany@mkausa.org")
    assert await profile_status(db, 50) == {"complete": False}
    await svc.refresh_attributes(db, u)
    await db.commit()
    assert await profile_status(db, 50) == {"complete": False}   # user-facing shape: never attributes
    st = await profile_status(db, 50, include_attributes=True)
    assert st["complete"] is False and st["mka_attributes"]["effective"]["majlis"] == "Albany"
    await delete_profile(db, 50)
    await db.commit()
    assert await profile_status(db, 50) == {"complete": False}


def test_effective_public_strips_metadata():
    out = svc.effective_public({"status": "matched", "source": "admin", "flags": ["x"], "majlis": "Albany"})
    assert set(out) == set(svc.PUBLIC_FIELDS) and "source" not in out and "flags" not in out


@pytest.mark.asyncio
async def test_list_status_in_and_mismatch_filters(db, org):
    from src.db.mka_user_profile import MkaUserProfile

    for i, e in enumerate(["tabligh.albany@mkausa.org", "tabligh.boston@mkausa.org",
                           "john.smith@mkausa.org", "tabligh.atlantis@mkausa.org"]):
        await _user(db, 400 + i, e, "google", org)
    await svc.recompute_users(db)
    db.add(MkaUserProfile(user_id=400, majlis="Albany", region="Northeast"))   # agrees
    db.add(MkaUserProfile(user_id=401, majlis="Seattle", region="Northwest"))  # disagrees
    db.add(MkaUserProfile(user_id=402, majlis="Seattle", region="Northwest"))  # no derived majlis: not a mismatch
    await db.commit()
    q = await svc.list_attributes(db, org.id, filters={"status": ["unrecognized", "ambiguous", "partial"]})
    assert q["total"] == 2
    mm = await svc.list_attributes(db, org.id, mismatch=True)
    assert [i["user_id"] for i in mm["items"]] == [401]
