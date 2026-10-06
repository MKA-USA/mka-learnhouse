"""MKA fork: audience block routes of /mka/attributes (contract s2): authz matrix, cross-org isolation, hostile payloads,
count correctness (fail-closed reads, expected roster), counterparts, preview-as + audit.

World: the compliance test world (org 1 with admin 1, learner 2, maintainer 20, role-5 editor 21, authors 23/24/27/28, org 2 with
admin 40) plus ten attribute-bearing people (50-59) in org 1 and one in org 2 (61). Synthetic ``example.invalid`` data only.
"""

import json
from datetime import datetime

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlmodel import delete, select

from src.core.events.database import get_db_session
from src.db.api_tokens import APIToken
from src.db.mka_compliance import MkaComplianceCycle, MkaComplianceCycleCourse, MkaComplianceExpected
from src.db.mka_user_attributes import MkaUserAttributesAudit
from src.db.organization_config import OrganizationConfig
from src.db.users import PublicUser, SuperadminAPITokenUser, User
from src.security.api_token_utils import require_authenticated_user_or_api_token
from src.security.auth import get_authenticated_user, get_current_user
from src.services.api_tokens.api_tokens import generate_api_token
from src.services.mka import attributes as attr_svc
from src.services.mka import audience as audience_svc
from src.services.mka.audience_config import build_options
from src.tests.routers.mka_compliance_world import add_attributes, add_user, build_world

BASE = "/api/v1/mka/attributes"

ADMIN, LEARNER, MAINT, EDITOR = 1, 2, 20, 21
AUTHOR_TABLIGH, INACTIVE_AUTHOR, REPORTER, AUTHOR_GENERAL = 23, 24, 27, 28
ORG2_ADMIN, SUPER = 40, 60
LOCAL_ALBANY, STALE_LOCAL = 50, 59

PEOPLE = {  # uid: (email, effective attributes)
    50: ("tabligh.albany@example.invalid", dict(level="local", department="tabligh", role="nazim_dept", role_title="Nazim Tabligh", majlis="Albany", region="Northeast")),
    51: ("tabligh.boston@example.invalid", dict(level="local", department="tabligh", role="nazim_dept", role_title="Nazim Tabligh", majlis="Boston", region="Northeast")),
    52: ("maal.albany@example.invalid", dict(level="local", department="maal", role="nazim_dept", role_title="Nazim Maal", majlis="Albany", region="Northeast")),
    53: ("rq.northeast@example.invalid", dict(level="regional", role="regional_qaid", role_title="Regional Qaid", region="Northeast")),
    54: ("head.tabligh@example.invalid", dict(level="national", department="tabligh", role="mohtamim", role_title="Mohtamim Tabligh")),
    55: ("qaid.houston@example.invalid", dict(level="local", role="qaid", role_title="Qaid", majlis="Houston", region="Gulf")),
    56: ("partial.tabligh@example.invalid", dict(status="partial", department="tabligh", role="nazim_dept", role_title="Nazim Tabligh")),
    57: ("outsider@example.invalid", dict(status="not_applicable", is_officeholder=False)),
    58: ("ambiguous@example.invalid", dict(status="ambiguous")),
    59: ("stale.local@example.invalid", dict(level="local", department="tabligh", role="nazim_dept", majlis="Albany", region="Northeast")),
}

LOCAL_RULE = {"v": 1, "mode": "show", "groups": [{"level": ["local"]}]}
EVERYONE_OFFICEHOLDER = {"v": 1, "mode": "show", "groups": [{}]}


@pytest.fixture
async def world(db, org, other_org, admin_user, regular_user):
    for o in (org, other_org):  # the upstream token pattern reads the org plan from its config
        db.add(OrganizationConfig(org_id=o.id, config={"config_version": "2.0"},
                                  creation_date=str(datetime.now()), update_date=str(datetime.now())))
    await db.commit()
    w = await build_world(db, org, other_org, admin_user, regular_user)
    for uid, (email, eff) in PEOPLE.items():
        await add_user(db, org.id, uid, email)
        await add_attributes(db, uid, email, stale=(uid == STALE_LOCAL), **eff)
    await add_user(db, other_org.id, 61, "o2.local@example.invalid")
    await add_attributes(db, 61, "o2.local@example.invalid", level="local", department="tabligh", role="nazim_dept", majlis="Albany", region="Northeast")
    await add_user(db, None, SUPER, "super@example.invalid")
    me = await db.get(User, SUPER)
    me.is_superadmin = True
    db.add(me)
    await db.commit()
    return w


def _app(db):
    from src.router import v1_router

    app = FastAPI()
    app.include_router(v1_router)
    app.dependency_overrides[get_db_session] = lambda: db
    return app


def client_for(db, uid):
    app = _app(db)
    user = PublicUser(id=uid, username=f"u{uid}", first_name="F", last_name="L", email=f"u{uid}@x.invalid", user_uuid=f"user_{uid}")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_authenticated_user] = lambda: user
    app.dependency_overrides[require_authenticated_user_or_api_token] = lambda: user
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


def anonymous_client(db):
    return AsyncClient(transport=ASGITransport(app=_app(db)), base_url="http://t")  # real auth, no credentials


@pytest.fixture
async def token_client(db, org, world):
    full, prefix, hashed = generate_api_token()
    db.add(APIToken(name="prov", token_uuid="apitoken_aud", token_prefix=prefix, token_hash=hashed,
                    org_id=org.id, created_by_user_id=1,
                    rights={"users": {"action_read": True}, "organizations": {"action_update": True}},
                    creation_date=str(datetime.now()), update_date=str(datetime.now())))
    await db.commit()
    async with AsyncClient(transport=ASGITransport(app=_app(db)), base_url="http://t",
                           headers={"Authorization": f"Bearer {full}"}) as c:
        yield c


async def count(db, uid, rule, org_id=1, course_uuid=None, **extra):
    body = {"org_id": org_id, "rule": rule, **({"course_uuid": course_uuid} if course_uuid else {}), **extra}
    async with client_for(db, uid) as c:
        return await c.post(f"{BASE}/audience/count", json=body)


# ---------------------------------------------------------------------------------------------------------
# GET /me?course_uuid=
# ---------------------------------------------------------------------------------------------------------

async def me(db, uid, course_uuid=None):
    async with client_for(db, uid) as c:
        return await c.get(f"{BASE}/me", params={"course_uuid": course_uuid} if course_uuid else None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "uid, course, expected",
    [
        (AUTHOR_TABLIGH, "course_tabligh", True),     # active creator of THIS course
        (AUTHOR_TABLIGH, None, False),                # no course => no elevation
        (AUTHOR_TABLIGH, "course_general", False),    # author of a DIFFERENT course
        (AUTHOR_TABLIGH, "course_maal", False),
        (AUTHOR_TABLIGH, "course_o2_general", False), # a course of another org
        (AUTHOR_TABLIGH, "no_such_course", False),    # unknown: ignored, no 404
        (INACTIVE_AUTHOR, "course_tabligh", False),   # inactive authorship
        (REPORTER, "course_tabligh", False),          # REPORTER is not an author role
        (AUTHOR_GENERAL, "course_general", True),     # active CONTRIBUTOR of that course
        (AUTHOR_GENERAL, "course_tabligh", False),
        (31, "course_tabligh", False),                # learner
        (LEARNER, "course_tabligh", False),
        (ORG2_ADMIN, "course_tabligh", False),        # a course that exists decides: admin of ANOTHER org is not elevated
        (ORG2_ADMIN, "course_o2_general", True),      # ... but is in their own org's course
        (ADMIN, "course_o2_general", False),
        (ADMIN, "course_tabligh", True),
        (MAINT, "course_tabligh", True),
        (SUPER, "course_tabligh", True),
        (SUPER, "course_o2_general", True),
        (ORG2_ADMIN, None, True),                     # no course_uuid: legacy any-org rule, unchanged
        (ORG2_ADMIN, "no_such_course", True),         # unknown course: legacy rule, unchanged (and no 404)
        (ADMIN, None, True),
        (MAINT, None, True),
        (SUPER, None, True),
        (EDITOR, "course_tabligh", False),
    ],
)
async def test_me_can_view_all_matrix(db, world, uid, course, expected):
    r = await me(db, uid, course)
    assert r.status_code == 200, r.text
    assert r.json()["can_view_all"] is expected
    assert r.headers["cache-control"] == "private, no-store"


@pytest.mark.asyncio
async def test_me_shape_is_unchanged(db, world):
    r = await me(db, LOCAL_ALBANY, "course_tabligh")
    body = r.json()
    assert set(body) == {"attributes", "stale", "can_view_all", "rules_version"}
    assert set(body["attributes"]) == set(attr_svc.PUBLIC_FIELDS)
    assert body["attributes"]["department"] == "tabligh" and body["can_view_all"] is False


@pytest.mark.asyncio
async def test_me_unknown_course_is_indistinguishable_from_no_course(db, world):
    a = (await me(db, 31, "no_such_course")).json()
    b = (await me(db, 31)).json()
    c = (await me(db, 31, "course_o2_general")).json()
    assert a == b == c


@pytest.mark.asyncio
async def test_me_author_who_left_the_org_is_not_elevated(db, world):
    from src.db.user_organizations import UserOrganization

    await db.execute(delete(UserOrganization).where(UserOrganization.user_id == AUTHOR_TABLIGH))
    await db.commit()
    assert (await me(db, AUTHOR_TABLIGH, "course_tabligh")).json()["can_view_all"] is False


@pytest.mark.asyncio
async def test_me_rejects_overlong_course_uuid_and_tokens(db, world, token_client):
    assert (await me(db, 31, "x" * 201)).status_code == 422
    assert (await token_client.get(f"{BASE}/me", params={"course_uuid": "course_tabligh"})).status_code == 403
    async with anonymous_client(db) as c:
        assert (await c.get(f"{BASE}/me")).status_code in (401, 403)


# ---------------------------------------------------------------------------------------------------------
# GET /options
# ---------------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("uid", [31, LEARNER, ADMIN, MAINT, AUTHOR_TABLIGH, EDITOR, SUPER])
async def test_options_any_member_and_superadmin(db, world, uid):
    async with client_for(db, uid) as c:
        r = await c.get(f"{BASE}/options", params={"org_id": 1})
    assert r.status_code == 200, r.text
    assert r.json() == build_options()
    assert r.headers["cache-control"] == "private, no-store"


@pytest.mark.asyncio
async def test_options_denied_for_non_members_tokens_and_anonymous(db, world, token_client):
    async with client_for(db, ORG2_ADMIN) as c:
        assert (await c.get(f"{BASE}/options", params={"org_id": 1})).status_code == 403
        assert (await c.get(f"{BASE}/options", params={"org_id": 2})).status_code == 200
    async with client_for(db, SUPER) as c:
        assert (await c.get(f"{BASE}/options", params={"org_id": 999})).status_code == 404
    assert (await token_client.get(f"{BASE}/options", params={"org_id": 1})).status_code == 403
    async with anonymous_client(db) as c:
        assert (await c.get(f"{BASE}/options", params={"org_id": 1})).status_code in (401, 403)


@pytest.mark.asyncio
@pytest.mark.parametrize("params", [{}, {"org_id": "abc"}, {"org_id": "0"}, {"org_id": "-3"}, {"org_id": str(10**12)}, {"org_id": "1.5"}])
async def test_options_bad_org_id_is_422(db, world, params):
    async with client_for(db, ADMIN) as c:
        assert (await c.get(f"{BASE}/options", params=params)).status_code == 422


# ---------------------------------------------------------------------------------------------------------
# POST /audience/count: authz matrix
# ---------------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "uid, org_id, course, status",
    [
        (ADMIN, 1, None, 200),
        (MAINT, 1, None, 200),
        (SUPER, 1, None, 200),
        (AUTHOR_TABLIGH, 1, "course_tabligh", 200),
        (AUTHOR_TABLIGH, 1, None, 403),                 # an author needs to name the course
        (AUTHOR_TABLIGH, 1, "course_general", 403),     # author of ANOTHER course
        (AUTHOR_TABLIGH, 1, "no_such_course", 403),
        (AUTHOR_TABLIGH, 1, "course_o2_general", 403),  # a course of another org
        (AUTHOR_GENERAL, 1, "course_tabligh", 403),     # contributor elsewhere
        (INACTIVE_AUTHOR, 1, "course_tabligh", 403),
        (REPORTER, 1, "course_tabligh", 403),
        (EDITOR, 1, "course_tabligh", 403),             # role with org-update right is NOT an audience admin
        (LEARNER, 1, "course_tabligh", 403),
        (31, 1, None, 403),
        (ORG2_ADMIN, 1, None, 403),                     # admin of ANOTHER org
        (ORG2_ADMIN, 1, "course_tabligh", 403),
        (ORG2_ADMIN, 2, None, 200),                     # ... but of their own
        (ADMIN, 2, None, 403),                          # org-1 admin is nobody in org 2
        (AUTHOR_TABLIGH, 2, "course_tabligh", 403),
        (SUPER, 999, None, 404),
    ],
)
async def test_count_authz_matrix(db, world, uid, org_id, course, status):
    r = await count(db, uid, LOCAL_RULE, org_id=org_id, course_uuid=course)
    assert r.status_code == status, r.text
    if status == 200:
        assert r.headers["cache-control"] == "private, no-store"


@pytest.mark.asyncio
async def test_count_denied_for_tokens_and_anonymous(db, world, token_client):
    body = {"org_id": 1, "rule": LOCAL_RULE}
    assert (await token_client.post(f"{BASE}/audience/count", json=body)).status_code == 403
    async with anonymous_client(db) as c:
        assert (await c.post(f"{BASE}/audience/count", json=body)).status_code in (401, 403)


def test_superadmin_token_principal_is_refused():
    with pytest.raises(Exception) as exc:
        audience_svc.session_uid(SuperadminAPITokenUser())
    assert getattr(exc.value, "status_code", None) == 403


# ---------------------------------------------------------------------------------------------------------
# POST /audience/count: payloads
# ---------------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {},
        {"org_id": 1},
        {"rule": LOCAL_RULE},
        {"org_id": "1", "rule": LOCAL_RULE},
        {"org_id": True, "rule": LOCAL_RULE},
        {"org_id": 1.0, "rule": LOCAL_RULE},
        {"org_id": None, "rule": LOCAL_RULE},
        {"org_id": 0, "rule": LOCAL_RULE},
        {"org_id": -1, "rule": LOCAL_RULE},
        {"org_id": 10**30, "rule": LOCAL_RULE},
        {"org_id": [1], "rule": LOCAL_RULE},
        {"org_id": 1, "rule": LOCAL_RULE, "extra": 1},
        {"org_id": 1, "rule": LOCAL_RULE, "course_uuid": 5},
        {"org_id": 1, "rule": LOCAL_RULE, "course_uuid": "x" * 201},
        {"org_id": 1, "rule": None},
        {"org_id": 1, "rule": []},
        {"org_id": 1, "rule": "x"},
        {"org_id": 1, "rule": 5},
        {"org_id": 1, "rule": {}},
        {"org_id": 1, "rule": {"v": 1, "mode": "maybe", "groups": [{}]}},
        {"org_id": 1, "rule": {"v": True, "mode": "show", "groups": [{}]}},
        {"org_id": 1, "rule": {"v": 1, "mode": "show", "groups": []}},
        {"org_id": 1, "rule": {"v": 1, "mode": "show", "groups": [{}] * 21}},
        {"org_id": 1, "rule": {"v": 1, "mode": "show", "groups": [{"level": "local"}]}},
        {"org_id": 1, "rule": {"v": 1, "mode": "show", "groups": [{"majlis": ["a"] * 501}]}},
        {"org_id": 1, "rule": {"v": 1, "mode": "show", "groups": [{"majlis": ["a" * 201]}]}},
        {"org_id": 1, "rule": {"v": 1, "mode": "show", "groups": [{"majlis": [f"m{i}" for i in range(200_000)]}]}},  # huge body
    ],
    ids=lambda b: json.dumps(b)[:60],
)
async def test_count_bad_payload_is_422_never_500(db, world, body):
    async with client_for(db, ADMIN) as c:
        r = await c.post(f"{BASE}/audience/count", json=body)
    assert r.status_code == 422, r.text[:300]
    assert r.json()["detail"]


@pytest.mark.asyncio
async def test_count_invalid_rule_detail_is_the_validator_message(db, world):
    r = await count(db, ADMIN, {"v": 1, "mode": "maybe", "groups": [{}]})
    assert r.status_code == 422 and r.json() == {"detail": "mode must be 'show' or 'hide'"}


@pytest.mark.asyncio
async def test_count_non_json_and_wrong_json_types_are_422(db, world):
    async with client_for(db, ADMIN) as c:
        for content in (b"not json", b"[1,2]", b'"x"', b"null", b""):
            r = await c.post(f"{BASE}/audience/count", content=content, headers={"content-type": "application/json"})
            assert r.status_code == 422, (content, r.status_code, r.text[:200])


@pytest.mark.asyncio
async def test_count_deeply_nested_rule_does_not_500(db, world):
    deep = "[" * 100_000 + "]" * 100_000
    raw = f'{{"org_id": 1, "rule": {{"v": 1, "mode": "show", "groups": [{{"gender": {deep}}}]}}}}'.encode()
    async with client_for(db, ADMIN) as c:
        r = await c.post(f"{BASE}/audience/count", content=raw, headers={"content-type": "application/json"})
    assert r.status_code in (200, 422), r.status_code


@pytest.mark.asyncio
async def test_unauthorized_garbage_does_not_leak_validation_detail_as_success(db, world):
    r = await count(db, 31, LOCAL_RULE)
    assert r.status_code == 403 and "level" not in r.text


# ---------------------------------------------------------------------------------------------------------
# POST /audience/count: numbers
# ---------------------------------------------------------------------------------------------------------
# Org 1 has 26 members: 16 from the compliance world (11 without an attribute row or with a stale one read as unknown) plus 50-59.

@pytest.mark.asyncio
async def test_count_local_officeholders(db, world):
    r = await count(db, ADMIN, LOCAL_RULE)
    body = r.json()
    assert set(body) == {"count", "total_officeholders", "unrecognized", "by_level", "expected"}
    assert body["count"] == 5                                  # 25 (local sadr) + 50, 51, 52, 55; 59 is stale => unknown
    assert body["total_officeholders"] == 15                   # stale rows read as NOT officeholders; ambiguous (58) is stored as one
    assert body["unrecognized"] == 11                          # 8 missing rows + 2 stale + 1 ambiguous
    assert body["by_level"] == {"national": 0, "regional": 0, "local": 5}


@pytest.mark.asyncio
async def test_count_all_officeholders_by_level(db, world):
    body = (await count(db, ADMIN, EVERYONE_OFFICEHOLDER)).json()
    assert body["count"] == 14                                 # matched/partial holders: 22, 25, 31-35, 50-56
    assert body["by_level"] == {"national": 2, "regional": 1, "local": 5}


@pytest.mark.asyncio
async def test_count_department_includes_partial_but_not_stale(db, world):
    assert (await count(db, ADMIN, {"v": 1, "mode": "show", "groups": [{"department": ["tabligh"]}]})).json()["count"] == 4  # 50, 51, 54, 56


@pytest.mark.asyncio
async def test_count_hide_mode_counts_unknown_people(db, world):
    rule = {"v": 1, "mode": "hide", "groups": [{"level": ["national"]}]}
    assert (await count(db, ADMIN, rule)).json()["count"] == 24  # 26 members minus 22 and 54


@pytest.mark.asyncio
async def test_count_officeholder_false_group_is_everyone_signed_in(db, world):
    rule = {"v": 1, "mode": "show", "groups": [{"officeholder": False}]}
    assert (await count(db, ADMIN, rule)).json()["count"] == 26


@pytest.mark.asyncio
async def test_count_newer_rule_version_reaches_nobody(db, world):
    assert (await count(db, ADMIN, {"v": 2, "mode": "show", "groups": [{}]})).json()["count"] == 0


@pytest.mark.asyncio
async def test_count_follows_the_fail_closed_reader_when_email_drifts(db, world):
    before = (await count(db, ADMIN, LOCAL_RULE)).json()["count"]
    user = await db.get(User, LOCAL_ALBANY)
    user.email = "changed.address@example.invalid"  # row was derived for the OLD address => reads as unknown
    db.add(user)
    await db.commit()
    assert (await count(db, ADMIN, LOCAL_RULE)).json()["count"] == before - 1


@pytest.mark.asyncio
async def test_count_author_gets_same_numbers_as_admin(db, world):
    a = (await count(db, ADMIN, LOCAL_RULE)).json()
    b = (await count(db, AUTHOR_TABLIGH, LOCAL_RULE, course_uuid="course_tabligh")).json()
    assert a == b


@pytest.mark.asyncio
async def test_count_never_returns_names_or_addresses(db, world):
    r = await count(db, ADMIN, EVERYONE_OFFICEHOLDER)
    text = r.text
    assert "example.invalid" not in text and "@" not in text
    assert all(isinstance(v, (int, dict, type(None))) for v in r.json().values())
    assert r.json()["expected"] is not None and set(r.json()["expected"]) == {"matching", "total", "cycle_id"}


@pytest.mark.asyncio
async def test_count_expected_roster(db, world):
    dept = (await count(db, ADMIN, {"v": 1, "mode": "show", "groups": [{"department": ["tabligh"]}]})).json()["expected"]
    assert dept == {"matching": 5, "total": 10, "cycle_id": world.cycle.id}  # l1, l2, ghost1, crossorg, head.tabligh
    local = (await count(db, ADMIN, LOCAL_RULE)).json()["expected"]
    assert local["matching"] == 6 and local["total"] == 10
    assert (await count(db, ADMIN, EVERYONE_OFFICEHOLDER)).json()["expected"]["matching"] == 10
    role = (await count(db, ADMIN, {"v": 1, "mode": "show", "groups": [{"role": ["qaid"]}]})).json()["expected"]
    assert role["matching"] == 0 and role["total"] == 10  # roster rows carry no role: documented undercount
    hide = (await count(db, ADMIN, {"v": 1, "mode": "hide", "groups": [{"department": ["tabligh"]}]})).json()["expected"]
    assert hide["matching"] == 5


def test_expected_roster_row_blank_department_becomes_null():
    from src.db.mka_compliance import MkaComplianceExpected

    row = MkaComplianceExpected(org_id=1, cycle_id=1, email="x@example.invalid", department="", level="national")
    viewer = audience_svc._expected_viewer(row)
    assert viewer["department"] is None and viewer["role"] is None and viewer["status"] == "matched" and viewer["is_officeholder"] is True
    row.department = "tabligh"
    assert audience_svc._expected_viewer(row)["department"] == "tabligh"


@pytest.mark.asyncio
async def test_count_expected_uses_the_most_recent_cycle(db, world):
    from datetime import date

    newer = MkaComplianceCycle(org_id=1, label="2027-28", starts_on=date(2027, 11, 1), deadline_on=date(2027, 12, 1))
    db.add(newer)
    await db.commit()
    db.add(MkaComplianceExpected(org_id=1, cycle_id=newer.id, email="only@example.invalid", department="tabligh", level="local", majlis="Albany", region="Northeast"))
    await db.commit()
    body = (await count(db, ADMIN, LOCAL_RULE)).json()["expected"]
    assert body == {"matching": 1, "total": 1, "cycle_id": newer.id}


@pytest.mark.asyncio
async def test_count_without_a_cycle_has_null_expected(db, world, other_org):
    for model in (MkaComplianceCycleCourse, MkaComplianceExpected, MkaComplianceCycle):
        await db.execute(delete(model).where(model.org_id == other_org.id))
    await db.commit()
    r = await count(db, ORG2_ADMIN, LOCAL_RULE, org_id=2)
    assert r.status_code == 200 and r.json()["expected"] is None


@pytest.mark.asyncio
async def test_count_is_org_scoped_both_ways(db, world):
    org1 = (await count(db, ADMIN, LOCAL_RULE)).json()
    org2 = (await count(db, ORG2_ADMIN, LOCAL_RULE, org_id=2)).json()
    assert org1["count"] == 5
    assert org2["count"] == 1                                   # only 61; org-1 people never appear
    assert org2["total_officeholders"] == 3                     # 41, 42 (matched, no level) and 61
    assert org2["expected"]["total"] == 3 and org2["expected"]["cycle_id"] == world.cycle2.id
    sup = (await count(db, SUPER, LOCAL_RULE, org_id=2)).json()
    assert sup == org2


@pytest.mark.asyncio
async def test_count_ignores_a_cross_org_course_uuid_for_non_admins(db, world):
    # an org-2 course named while asking about org 1: the author branch needs the course IN that org
    r = await count(db, AUTHOR_TABLIGH, LOCAL_RULE, org_id=1, course_uuid="course_o2_general")
    assert r.status_code == 403


# ---------------------------------------------------------------------------------------------------------
# GET /me/counterparts
# ---------------------------------------------------------------------------------------------------------

async def counterparts(db, uid):
    async with client_for(db, uid) as c:
        return await c.get(f"{BASE}/me/counterparts")


async def add_viewer(db, uid, email, **eff):
    await add_user(db, 1, uid, email)
    await add_attributes(db, uid, email, **eff)


@pytest.mark.asyncio
async def test_counterparts_for_a_local_department_nazim(db, world):
    r = await counterparts(db, LOCAL_ALBANY)
    assert r.status_code == 200
    assert r.headers["cache-control"] == "private, no-store"
    assert r.json() == {
        "counterparts": [
            {"level": "national", "role_title": "Mohtamim Tabligh", "email": "tabligh@mkausa.org", "name": None, "department": "tabligh"},
            {"level": "regional", "role_title": "Regional Nazim Tabligh", "email": "tabligh.northeast@mkausa.org", "name": None, "department": "tabligh"},
            {"level": "regional", "role_title": "Regional Qaid", "email": "qaid.northeast@mkausa.org", "name": None, "department": None},
        ],
        "reason": None,
    }


@pytest.mark.asyncio
async def test_counterparts_atfal_viewer_gets_atfalusa_local_mailbox(db, world):
    await add_viewer(db, 70, "murabbi@example.invalid", level="local", department="atfal", role="murabbi_atfal", role_title="Murabbi Atfal",
                     majlis="Syracuse-Binghamton", region="Northeast")
    body = (await counterparts(db, 70)).json()
    assert [(r["level"], r["email"]) for r in body["counterparts"]] == [
        ("national", "atfal@mkausa.org"), ("regional", "qaid.northeast@mkausa.org"), ("local", "nazim.syracuse@atfalusa.org"),
    ]
    assert body["counterparts"][2]["role_title"] == "Nazim Atfal"


@pytest.mark.asyncio
async def test_counterparts_local_qaid_gets_regional_qaid_only(db, world):
    body = (await counterparts(db, 55)).json()
    assert body["reason"] is None
    assert [(r["level"], r["email"]) for r in body["counterparts"]] == [("regional", "qaid.gulf@mkausa.org")]


@pytest.mark.asyncio
async def test_counterparts_regional_qaid_is_not_applicable(db, world):
    assert (await counterparts(db, 53)).json() == {"counterparts": [], "reason": "not_applicable"}


@pytest.mark.asyncio
async def test_counterparts_partial_viewer_without_department_gets_no_department(db, world):
    await add_viewer(db, 72, "partial.nodept@example.invalid", status="partial", role="nazim_dept", role_title="Nazim")
    assert (await counterparts(db, 72)).json() == {"counterparts": [], "reason": "no_department"}


@pytest.mark.asyncio
async def test_counterparts_never_list_the_viewers_own_office_even_when_the_account_address_differs(db, world):
    # 54: national Mohtamim Tabligh whose account address is head.tabligh@example.invalid, not tabligh@
    assert (await counterparts(db, 54)).json() == {"counterparts": [], "reason": None}


@pytest.mark.asyncio
async def test_counterparts_partial_viewer_gets_department_head_only(db, world):
    body = (await counterparts(db, 56)).json()
    assert [r["email"] for r in body["counterparts"]] == ["tabligh@mkausa.org"]


@pytest.mark.asyncio
@pytest.mark.parametrize("uid", [LEARNER, 57, 58, STALE_LOCAL, 26])  # no row, not_applicable, ambiguous, stale flag, stale email-less row
async def test_counterparts_unrecognized_reasons(db, world, uid):
    assert (await counterparts(db, uid)).json() == {"counterparts": [], "reason": "unrecognized"}


@pytest.mark.asyncio
async def test_counterparts_omit_the_viewers_own_address(db, world):
    await add_viewer(db, 71, "tabligh@mkausa.org", level="national", department="tabligh", role="mohtamim", role_title="Mohtamim Tabligh")
    assert (await counterparts(db, 71)).json() == {"counterparts": [], "reason": None}


@pytest.mark.asyncio
async def test_counterparts_only_describe_the_session_user(db, world):
    a = (await counterparts(db, LOCAL_ALBANY)).json()
    b = (await counterparts(db, 51)).json()  # same role, other Majlis: identical rows (own local row omitted for both)
    assert a == b
    assert (await counterparts(db, ADMIN)).json()["reason"] == "unrecognized"


@pytest.mark.asyncio
async def test_counterparts_denied_for_tokens_and_anonymous(db, world, token_client):
    assert (await token_client.get(f"{BASE}/me/counterparts")).status_code == 403
    async with anonymous_client(db) as c:
        assert (await c.get(f"{BASE}/me/counterparts")).status_code in (401, 403)


# ---------------------------------------------------------------------------------------------------------
# GET /preview-people and POST /preview-people/{user_id}
# ---------------------------------------------------------------------------------------------------------

async def people(db, uid, org_id=1, q="example"):
    async with client_for(db, uid) as c:
        return await c.get(f"{BASE}/preview-people", params={"org_id": org_id, "q": q})


async def preview(db, uid, target, org_id=1):
    async with client_for(db, uid) as c:
        return await c.post(f"{BASE}/preview-people/{target}", params={"org_id": org_id})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "uid, org_id, status",
    [(ADMIN, 1, 200), (MAINT, 1, 200), (SUPER, 1, 200), (SUPER, 2, 200), (ORG2_ADMIN, 2, 200),
     (LEARNER, 1, 403), (31, 1, 403), (AUTHOR_TABLIGH, 1, 403), (EDITOR, 1, 403), (INACTIVE_AUTHOR, 1, 403),
     (ORG2_ADMIN, 1, 403), (ADMIN, 2, 403), (SUPER, 999, 404)],
)
async def test_preview_people_authz_matrix(db, world, uid, org_id, status):
    assert (await people(db, uid, org_id)).status_code == status


@pytest.mark.asyncio
async def test_preview_people_denied_for_tokens_and_anonymous(db, world, token_client):
    assert (await token_client.get(f"{BASE}/preview-people", params={"org_id": 1, "q": "example"})).status_code == 403
    async with anonymous_client(db) as c:
        assert (await c.get(f"{BASE}/preview-people", params={"org_id": 1, "q": "example"})).status_code in (401, 403)


@pytest.mark.asyncio
async def test_preview_people_result_shape_and_cap(db, world):
    r = await people(db, ADMIN, q="example.invalid")
    body = r.json()
    assert set(body) == {"people"} and len(body["people"]) == 20  # 26 members match, capped at 20
    assert r.headers["cache-control"] == "private, no-store"
    for p in body["people"]:
        assert set(p) == {"user_id", "display_name", "email"}      # no attributes in the list
    one = (await people(db, ADMIN, q="nat.aitmad")).json()["people"]
    assert one == [{"user_id": 22, "display_name": "F L", "email": "nat.aitmad@example.invalid"}]


@pytest.mark.asyncio
async def test_preview_people_is_org_scoped(db, world):
    assert (await people(db, ADMIN, q="o2.local")).json() == {"people": []}
    assert [p["user_id"] for p in (await people(db, ORG2_ADMIN, org_id=2, q="o2.local")).json()["people"]] == [61]
    assert (await people(db, ORG2_ADMIN, org_id=2, q="tabligh.albany")).json() == {"people": []}


@pytest.mark.asyncio
@pytest.mark.parametrize("q", ["%%", "__", "\\", "%", "_e"])
async def test_preview_people_wildcards_are_literal(db, world, q):
    r = await people(db, ADMIN, q=q if len(q) >= 2 else q + q)
    assert r.status_code == 200 and r.json() == {"people": []}


@pytest.mark.asyncio
@pytest.mark.parametrize("q", ["", "a", " a", "  ", "x" * 101])
async def test_preview_people_short_or_long_q_is_422(db, world, q):
    assert (await people(db, ADMIN, q=q)).status_code == 422


@pytest.mark.asyncio
async def test_preview_people_missing_or_bad_params_are_422(db, world):
    async with client_for(db, ADMIN) as c:
        assert (await c.get(f"{BASE}/preview-people", params={"org_id": 1})).status_code == 422
        assert (await c.get(f"{BASE}/preview-people", params={"q": "ab"})).status_code == 422
        assert (await c.get(f"{BASE}/preview-people", params={"org_id": "x", "q": "ab"})).status_code == 422
        assert (await c.get(f"{BASE}/preview-people", params={"org_id": 10**12, "q": "ab"})).status_code == 422


async def audit_rows(db, action="preview_as"):
    return (await db.execute(select(MkaUserAttributesAudit).where(MkaUserAttributesAudit.action == action))).scalars().all()


@pytest.mark.asyncio
async def test_preview_person_returns_effective_attributes_and_audits(db, world):
    r = await preview(db, ADMIN, LOCAL_ALBANY)
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "private, no-store"
    body = r.json()
    assert set(body) == {"attributes"} and set(body["attributes"]) == set(attr_svc.PUBLIC_FIELDS)
    assert body["attributes"]["department"] == "tabligh" and body["attributes"]["majlis"] == "Albany"
    rows = await audit_rows(db)
    assert len(rows) == 1
    assert (rows[0].user_id, rows[0].actor_user_id, rows[0].reason) == (LOCAL_ALBANY, ADMIN, "Preview as (audience block)")
    assert rows[0].before is None and rows[0].after is None


@pytest.mark.asyncio
async def test_preview_person_uses_the_fail_closed_reader(db, world):
    stale = (await preview(db, ADMIN, STALE_LOCAL)).json()["attributes"]
    assert stale["status"] == "unrecognized" and stale["is_officeholder"] is False and stale["department"] is None
    missing = (await preview(db, ADMIN, LEARNER)).json()["attributes"]
    assert missing["status"] == "unrecognized" and missing["is_officeholder"] is None


@pytest.mark.asyncio
async def test_preview_person_audit_is_per_call_and_actor_is_the_caller(db, world):
    await preview(db, MAINT, 51)
    await preview(db, SUPER, 51)
    rows = sorted(await audit_rows(db), key=lambda r: r.id)
    assert [r.actor_user_id for r in rows] == [MAINT, SUPER]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "uid, target, org_id, status",
    [
        (ADMIN, 41, 1, 404),          # a member of ANOTHER org
        (ADMIN, 61, 1, 404),
        (ADMIN, 9999, 1, 404),        # nobody
        (ORG2_ADMIN, 50, 2, 404),     # org-1 person asked through org 2
        (ORG2_ADMIN, 50, 1, 403),     # org-2 admin has no business in org 1
        (ADMIN, 41, 2, 403),
        (LEARNER, 50, 1, 403),
        (AUTHOR_TABLIGH, 50, 1, 403),
        (EDITOR, 50, 1, 403),
        (MAINT, 50, 1, 200),
        (SUPER, 50, 1, 200),
        (ORG2_ADMIN, 61, 2, 200),
        (SUPER, 50, 999, 404),
    ],
)
async def test_preview_person_authz_and_scope(db, world, uid, target, org_id, status):
    before = len(await audit_rows(db))
    r = await preview(db, uid, target, org_id)
    assert r.status_code == status, r.text
    assert len(await audit_rows(db)) == before + (1 if status == 200 else 0)  # failures never write an audit row


@pytest.mark.asyncio
async def test_preview_person_denied_for_tokens_anonymous_and_bad_ids(db, world, token_client):
    assert (await token_client.post(f"{BASE}/preview-people/50", params={"org_id": 1})).status_code == 403
    async with anonymous_client(db) as c:
        assert (await c.post(f"{BASE}/preview-people/50", params={"org_id": 1})).status_code in (401, 403)
    async with client_for(db, ADMIN) as c:
        assert (await c.post(f"{BASE}/preview-people/abc", params={"org_id": 1})).status_code == 422
        assert (await c.post(f"{BASE}/preview-people/0", params={"org_id": 1})).status_code == 422
        assert (await c.post(f"{BASE}/preview-people/{10**12}", params={"org_id": 1})).status_code == 422
        assert (await c.post(f"{BASE}/preview-people/50")).status_code == 422
    assert await audit_rows(db) == []


@pytest.mark.asyncio
async def test_preview_audit_does_not_break_existing_audit_listing(db, world):
    await preview(db, ADMIN, LOCAL_ALBANY)
    items = await attr_svc.list_audit(db, LOCAL_ALBANY)
    assert any(i["action"] == "preview_as" and i["actor_user_id"] == ADMIN for i in items)
    export = attr_svc._subject_audit(items)
    assert any(e["action"] == "preview_as" and e["by"] == "administrator" for e in export)
    assert "preview_as" in attr_svc.AUDIT_ACTIONS


# ---------------------------------------------------------------------------------------------------------
# search helper corner
# ---------------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_matches_full_name_and_email_case_insensitively(db, world):
    user = await db.get(User, 31)
    user.first_name, user.last_name = "Sample", "Person"
    db.add(user)
    await db.commit()
    for q in ("sample person", "SAMPLE", "person", "l1@example"):
        got = await audience_svc.search_people(db, 1, q)
        assert [p["user_id"] for p in got] == [31], q
    assert (await audience_svc.search_people(db, 1, "sample person"))[0]["display_name"] == "Sample Person"



@pytest.mark.asyncio
async def test_count_expected_counts_distinct_people_not_rows(db, world):
    # one person with two roster rows (different roles/emails in different case): counted once; matches if ANY row matches
    for dept, level, majlis, region, role in (("tabligh", "local", "Albany", "Northeast", "Nazim Tabligh"), ("maal", "regional", None, "Northeast", "Regional Nazim Maal")):
        db.add(MkaComplianceExpected(org_id=1, cycle_id=world.cycle.id, email="Dual.Role@example.invalid" if dept == "maal" else "dual.role@example.invalid",
                                     department=dept, level=level, majlis=majlis, region=region, role_title=role))
    await db.commit()
    base = {"department": 5, "total": 10}
    tab = (await count(db, ADMIN, {"v": 1, "mode": "show", "groups": [{"department": ["tabligh"]}]})).json()["expected"]
    assert tab == {"matching": base["department"] + 1, "total": base["total"] + 1, "cycle_id": world.cycle.id}  # 12 rows, 11 people
    both = (await count(db, ADMIN, {"v": 1, "mode": "show", "groups": [{"department": ["tabligh"]}, {"department": ["maal"]}]})).json()["expected"]
    assert both["matching"] == 5 + 3 + 1 and both["total"] == 11  # l3, l4, ghost2 (maal) + the dual person once


# ---------------------------------------------------------------------------------------------------------
# review fixes
# ---------------------------------------------------------------------------------------------------------

CROSS = 80  # learner member of org 1 AND org 2, active CREATOR of the org-2 course


async def make_cross_org_author(db, member_of_org2=True):
    from src.db.resource_authors import ResourceAuthor, ResourceAuthorshipEnum, ResourceAuthorshipStatusEnum

    await add_user(db, 1, CROSS, "cross.author@example.invalid")
    if member_of_org2:
        from src.db.user_organizations import UserOrganization

        db.add(UserOrganization(user_id=CROSS, org_id=2, role_id=4, creation_date=str(datetime.now()), update_date=str(datetime.now())))
    db.add(ResourceAuthor(resource_uuid="course_o2_general", user_id=CROSS, authorship=ResourceAuthorshipEnum.CREATOR,
                          authorship_status=ResourceAuthorshipStatusEnum.ACTIVE, creation_date=str(datetime.now()), update_date=str(datetime.now())))
    await db.commit()


@pytest.mark.asyncio
async def test_count_author_of_a_course_in_another_org_cannot_count_for_their_member_org(db, world):
    await make_cross_org_author(db)
    r = await count(db, CROSS, LOCAL_RULE, org_id=1, course_uuid="course_o2_general")
    assert r.status_code == 403
    assert (await count(db, CROSS, LOCAL_RULE, org_id=2, course_uuid="course_o2_general")).status_code == 200  # the legit case


@pytest.mark.asyncio
async def test_me_author_branch_needs_membership_of_the_courses_org(db, world):
    await make_cross_org_author(db, member_of_org2=False)
    assert (await me(db, CROSS, "course_o2_general")).json()["can_view_all"] is False


@pytest.mark.asyncio
async def test_me_author_of_a_course_in_their_other_org_is_elevated_there_only(db, world):
    await make_cross_org_author(db)
    assert (await me(db, CROSS, "course_o2_general")).json()["can_view_all"] is True
    assert (await me(db, CROSS, "course_tabligh")).json()["can_view_all"] is False
    assert (await me(db, CROSS)).json()["can_view_all"] is False


async def post_raw(db, uid, raw: bytes):
    async with client_for(db, uid) as c:
        return await c.post(f"{BASE}/audience/count", content=raw, headers={"content-type": "application/json"})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw",
    [
        b'{"org_id": NaN, "rule": {"v": 1, "mode": "show", "groups": [{}]}}',
        b'{"org_id": Infinity, "rule": {"v": 1, "mode": "show", "groups": [{}]}}',
        b'{"org_id": -Infinity, "rule": {"v": 1, "mode": "show", "groups": [{}]}}',
        b'{"org_id": 1, "rule": {"v": NaN, "mode": "show", "groups": [{}]}}',
        b'{"org_id": 1, "rule": {"v": 1, "mode": "show", "groups": [{"gender": [NaN]}]}}',
        b'{"org_id": 1, "rule": {"v": 1, "mode": "show", "groups": [{}], "label": Infinity}}',
        b'{"org_id": 1, "course_uuid": NaN, "rule": {"v": 1, "mode": "show", "groups": [{}]}}',
    ],
)
async def test_count_nan_and_infinity_anywhere_is_a_clean_422(db, world, raw):
    r = await post_raw(db, ADMIN, raw)
    assert r.status_code == 422, (r.status_code, r.text[:200])
    assert "NaN" not in r.text and "Infinity" not in r.text
    assert r.json()["detail"]


@pytest.mark.asyncio
async def test_count_rule_larger_than_64kb_is_422_and_just_under_is_fine(db, world):
    def rule_of(n):
        return {"v": 1, "mode": "show", "groups": [{"majlis": [f"{i:04d}" + "m" * 156 for i in range(n)]}]}  # 160 chars + JSON overhead per entry

    small = rule_of(380)   # ~ 62 KB
    big = rule_of(420)     # ~ 68 KB, still structurally valid
    assert 60_000 < len(json.dumps(small, separators=(",", ":"))) < 65_536 < len(json.dumps(big, separators=(",", ":")))
    assert (await count(db, ADMIN, small)).status_code == 200
    r = await count(db, ADMIN, big)
    assert r.status_code == 422 and "too large" in r.json()["detail"]


@pytest.mark.asyncio
async def test_count_body_larger_than_128kb_is_refused_before_parsing(db, world):
    r = await post_raw(db, ADMIN, b'{"org_id": 1, "rule": ' + b'"' + b"x" * 200_000 + b'"}')
    assert r.status_code == 422 and r.json()["detail"] == "request body is too large"


@pytest.mark.asyncio
async def test_count_body_cap_is_independent_of_the_rule_cap(db, world):
    # a tiny, valid rule: only the 128 KB BODY cap can refuse this (the 64 KB rule cap sees a 30-byte rule)
    padding = b" " * 200_000
    raw = b'{"org_id": 1, "rule": {"v": 1, "mode": "show", "groups": [{}]},' + padding + b'"course_uuid": null}'
    assert len(raw) > 128 * 1024
    r = await post_raw(db, ADMIN, raw)
    assert r.status_code == 422 and r.json()["detail"] == "request body is too large"
    ok_raw = b'{"org_id": 1, "rule": {"v": 1, "mode": "show", "groups": [{}]},' + b" " * 1000 + b'"course_uuid": null}'
    assert (await post_raw(db, ADMIN, ok_raw)).status_code == 200  # same payload with modest padding is fine


class _FakeRequest:
    def __init__(self, raw: bytes):
        self._raw = raw

    async def body(self):
        return self._raw


@pytest.mark.asyncio
@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
async def test_count_body_parser_rejects_json_constants_even_in_an_otherwise_valid_body(constant):
    from fastapi import HTTPException

    from src.routers.mka_attributes import _count_body

    # NaN sits inside an UNKNOWN group key value: the model and the rule validator would both accept it, only the parser refuses
    raw = ('{"org_id": 1, "rule": {"v": 1, "mode": "show", "groups": [{"gender": [%s]}]}}' % constant).encode()
    with pytest.raises(HTTPException) as exc:
        await _count_body(_FakeRequest(raw))
    assert exc.value.status_code == 422 and exc.value.detail == "request body must be valid JSON"
    ok = await _count_body(_FakeRequest(b'{"org_id": 1, "rule": {"v": 1, "mode": "show", "groups": [{"gender": [1.5]}]}}'))
    assert ok.org_id == 1  # same shape without the constant is accepted


@pytest.mark.asyncio
async def test_count_cpu_work_runs_off_the_event_loop(db, world, monkeypatch):
    import threading

    seen = []
    real = audience_svc._tally

    def spy(compiled, members):
        seen.append(threading.current_thread() is threading.main_thread())
        return real(compiled, members)

    monkeypatch.setattr(audience_svc, "_tally", spy)
    r = await count(db, ADMIN, LOCAL_RULE)
    assert r.status_code == 200 and r.json()["count"] == 5
    assert seen == [False]


# ---------------------------------------------------------------------------------------------------------
# authorize before validating; org MFA policy
# ---------------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rule",
    [
        None,
        {"v": 1, "mode": "maybe", "groups": [{}]},
        {"v": 1, "mode": "show", "groups": [{"majlis": [f"{i:04d}" + "m" * 156 for i in range(420)]}]},  # > 64 KB
    ],
    ids=["null", "bad-mode", "oversize"],
)
async def test_count_authorizes_before_validating_the_rule(db, world, rule):
    for uid, course in ((31, None), (LEARNER, None), (ORG2_ADMIN, None), (AUTHOR_TABLIGH, "course_general")):
        r = await count(db, uid, rule, course_uuid=course)
        assert r.status_code == 403, (uid, r.status_code, r.text[:120])  # no rule-validation detail for people who may not use the tool
        assert "mode" not in r.text and "large" not in r.text
    assert (await count(db, ADMIN, rule)).status_code == 422                # the same payload from an allowed caller is a 422


async def require_org1_two_factor(db):
    from src.db.organization_config import OrganizationConfig

    row = (await db.execute(select(OrganizationConfig).where(OrganizationConfig.org_id == 1))).scalars().first()
    row.config = {"config_version": "2.0", "admin_toggles": {"security": {
        "require_2fa": True, "require_2fa_grace_days": 0, "require_2fa_enabled_at": "2020-01-01T00:00:00", "exempt_external_auth": False}}}
    db.add(row)
    await db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("uid", [31, LEARNER, ADMIN, MAINT])
async def test_org_mfa_policy_blocks_options_and_count_for_members_without_mfa(db, world, uid):
    await require_org1_two_factor(db)
    async with client_for(db, uid) as c:
        r = await c.get(f"{BASE}/options", params={"org_id": 1})
        assert r.status_code == 403 and r.json()["detail"]["code"] == "MFA_REQUIRED_BY_ORG", r.text
    r = await count(db, uid, LOCAL_RULE)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "MFA_REQUIRED_BY_ORG", r.text


@pytest.mark.asyncio
async def test_org_mfa_policy_is_per_org_and_spares_superadmins(db, world):
    await require_org1_two_factor(db)
    async with client_for(db, SUPER) as c:
        assert (await c.get(f"{BASE}/options", params={"org_id": 1})).status_code == 200
    assert (await count(db, SUPER, LOCAL_RULE)).status_code == 200
    async with client_for(db, ORG2_ADMIN) as c:
        assert (await c.get(f"{BASE}/options", params={"org_id": 2})).status_code == 200  # org 2 has no policy
    assert (await count(db, ORG2_ADMIN, LOCAL_RULE, org_id=2)).status_code == 200
