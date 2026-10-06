"""MKA fork: API-token rights are the ones the org API-token UI can actually grant.

The Full Access / Read-only field sets below are copied from apps/web/services/api_tokens/api_tokens.ts
(getFullRights / getReadOnlyRights). They contain NO ``users`` / ``organizations`` keys. Reads need
courses.action_read AND assignments.action_read; writes need courses.action_update; empty rights are refused.
"""

from datetime import datetime

import pytest
from httpx import ASGITransport, AsyncClient

from src.db.api_tokens import APIToken
from src.services.api_tokens.api_tokens import generate_api_token
from src.tests.routers.test_mka_compliance_router import (  # noqa: F401  (fixtures + helpers)
    BASE, _app, cycle_payload, world,
)

_CRUD = ("action_create", "action_read", "action_update", "action_delete")


def _preset(full: bool) -> dict:
    crud = {a: full for a in _CRUD}
    crud["action_read"] = True
    rights = {r: dict(crud) for r in
              ("activities", "assignments", "coursechapters", "folders", "media", "certifications", "usergroups", "payments")}
    rights["courses"] = {**crud, "action_read_own": True, "action_update_own": full, "action_delete": full,
                         "action_delete_own": full}
    rights["search"] = {"action_read": True}
    assert "users" not in rights and "organizations" not in rights
    return rights


FULL = _preset(True)
READ_ONLY = _preset(False)
READ_NO_ASSIGNMENTS = {"courses": {"action_read": True, "action_update": False}}
READ_NO_COURSES = {"assignments": {"action_read": True}}

READ_PATHS = ("scope", "overview", "courses/course_general/summary", "courses/course_general/learners",
              "courses/course_general/learners.csv", "courses/course_general/trend")


def _q(org):
    return {"org_slug": org.slug}


async def _client(db, org, rights, uuid):
    full, prefix, hashed = generate_api_token()
    db.add(APIToken(name=uuid, token_uuid=uuid, token_prefix=prefix, token_hash=hashed, org_id=org.id,
                    created_by_user_id=1, rights=rights, creation_date=str(datetime.now()), update_date=str(datetime.now())))
    await db.commit()
    return AsyncClient(transport=ASGITransport(app=_app(db)), base_url="http://t", headers={"Authorization": f"Bearer {full}"})


@pytest.mark.asyncio
async def test_full_access_preset_reads_and_writes(db, org, world):  # noqa: F811
    async with await _client(db, org, FULL, "apitoken_full") as c:
        for path in READ_PATHS:
            assert (await c.get(f"{BASE}/{path}", params=_q(org))).status_code == 200, path
        assert (await c.post(f"{BASE}/cycles", params=_q(org), json=cycle_payload())).status_code == 200
        assert (await c.get("/api/v1/mka/attributes/users", params=_q(org))).status_code == 200


@pytest.mark.asyncio
async def test_read_only_preset_reads_but_cannot_write(db, org, world):  # noqa: F811
    async with await _client(db, org, READ_ONLY, "apitoken_ro") as c:
        for path in READ_PATHS:
            assert (await c.get(f"{BASE}/{path}", params=_q(org))).status_code == 200, path
        assert (await c.get("/api/v1/mka/attributes/users", params=_q(org))).status_code == 200
        r = await c.post(f"{BASE}/cycles", params=_q(org), json=cycle_payload())
        assert r.status_code == 403
        assert "courses.action_update" in r.json()["detail"] and "Full Access" in r.json()["detail"]
        assert (await c.post(f"{BASE}/expected/import", params=_q(org), json={"cycle": "x", "rows": []})).status_code == 403
        assert (await c.delete(f"{BASE}/cycles/1/expected", params=_q(org))).status_code == 403
        assert (await c.put("/api/v1/mka/attributes/roster/x.y@mkausa.org", params=_q(org),
                            json={"attributes": {"level": "national"}})).status_code == 403
        assert (await c.delete("/api/v1/mka/attributes/roster/x.y@mkausa.org", params=_q(org))).status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("rights,missing", [(READ_NO_ASSIGNMENTS, "assignments.action_read"),
                                            (READ_NO_COURSES, "courses.action_read")])
async def test_reads_need_courses_and_assignments_read(db, org, world, rights, missing):  # noqa: F811
    async with await _client(db, org, rights, "apitoken_partial") as c:
        for path in READ_PATHS:
            r = await c.get(f"{BASE}/{path}", params=_q(org))
            assert r.status_code == 403, path
            assert missing in r.json()["detail"] and "Read-only" in r.json()["detail"]
        assert (await c.get("/api/v1/mka/attributes/users", params=_q(org))).status_code == 403
        assert (await c.get("/api/v1/mka/attributes/roster", params=_q(org))).status_code == 403


@pytest.mark.asyncio
async def test_empty_rights_refused_everywhere(db, org, world):  # noqa: F811
    async with await _client(db, org, {}, "apitoken_empty") as c:
        for path in READ_PATHS:
            r = await c.get(f"{BASE}/{path}", params=_q(org))
            assert r.status_code == 403 and "no permissions configured" in r.json()["detail"], path
        assert (await c.post(f"{BASE}/cycles", params=_q(org), json=cycle_payload())).status_code == 403
        assert (await c.get("/api/v1/mka/attributes/roster", params=_q(org))).status_code == 403
        assert (await c.delete("/api/v1/mka/attributes/roster/x.y@mkausa.org", params=_q(org))).status_code == 403


@pytest.mark.asyncio
async def test_full_access_token_of_another_org_still_cannot_read(db, org, other_org, world):  # noqa: F811
    async with await _client(db, other_org, FULL, "apitoken_other") as c:
        for path in READ_PATHS:
            assert (await c.get(f"{BASE}/{path}", params=_q(org))).status_code in (403, 404), path
        assert (await c.post(f"{BASE}/cycles", params=_q(org), json=cycle_payload())).status_code in (403, 404)


# ---- writes need the whole Full Access update set ------------------------------------------------------------

UPDATE_RESOURCES = ("courses", "activities", "assignments", "coursechapters", "usergroups", "certifications")
COURSES_UPDATE_ONLY = {"courses": {"action_read": True, "action_update": True}, "assignments": {"action_read": True}}


def _without(resource: str) -> dict:
    rights = {r: dict(v) for r, v in FULL.items()}
    rights[resource]["action_update"] = False
    return rights


async def _write_attempts(c, org):
    return [
        await c.post(f"{BASE}/cycles", params=_q(org), json=cycle_payload()),
        await c.delete(f"{BASE}/cycles/1/expected", params=_q(org)),
        await c.put("/api/v1/mka/attributes/roster/x.y@mkausa.org", params=_q(org), json={"attributes": {"level": "national"}}),
    ]


@pytest.mark.asyncio
async def test_courses_update_only_token_cannot_write(db, org, world):  # noqa: F811
    async with await _client(db, org, COURSES_UPDATE_ONLY, "apitoken_cu") as c:
        for r in await _write_attempts(c, org):
            assert r.status_code == 403
            d = r.json()["detail"]
            assert "activities.action_update" in d and "Full Access" in d
        assert (await c.get(f"{BASE}/overview", params=_q(org))).status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("resource", UPDATE_RESOURCES)
async def test_each_update_right_is_required_for_writes(db, org, world, resource):  # noqa: F811
    async with await _client(db, org, _without(resource), f"apitoken_no_{resource}") as c:
        for r in await _write_attempts(c, org):
            assert r.status_code == 403 and f"{resource}.action_update" in r.json()["detail"]
        assert (await c.get(f"{BASE}/overview", params=_q(org))).status_code == 200
