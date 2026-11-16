"""MKA fork: /mka/courses/*/audience routes: authz matrix, org boundary, flag, response shapes."""

from datetime import datetime

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.core.events.database import get_db_session
from src.db.courses.courses import Course
from src.db.users import APITokenUser, PublicUser
from src.security.api_token_utils import require_authenticated_user_or_api_token
from src.security.auth import get_authenticated_user, get_current_user
from src.tests.routers.mka_compliance_world import add_attributes, add_user

NOW = str(datetime.now())
BASE = "/api/v1/mka/courses"
ADMIN, LEARNER = 1, 2
MAAL = dict(level="local", department="maal", role="nazim_dept", majlis="Albany", region="Northeast")


@pytest.fixture(autouse=True)
def flag_on(monkeypatch):
    monkeypatch.setenv("MKA_COURSE_AUDIENCE_ENABLED", "true")


@pytest.fixture
async def world(db, org, other_org, admin_user, regular_user):
    await add_user(db, org.id, 10, "maal@example.invalid")
    await add_attributes(db, 10, "maal@example.invalid", **MAAL)
    await add_user(db, org.id, 11, "plain@example.invalid")
    await add_attributes(db, 11, "plain@example.invalid", status="not_applicable", is_officeholder=False)
    db.add(Course(id=1, name="C1", description="d", public=True, published=True, open_to_contributors=False, org_id=org.id,
                  course_uuid="course_1", creation_date=NOW, update_date=NOW))
    db.add(Course(id=2, name="C2", description="d", public=True, published=True, open_to_contributors=False, org_id=other_org.id,
                  course_uuid="course_2", creation_date=NOW, update_date=NOW))
    await db.commit()


def client(db, principal):
    from src.router import v1_router

    app = FastAPI()
    app.include_router(v1_router)
    app.dependency_overrides[get_db_session] = lambda: db
    for dep in (get_current_user, get_authenticated_user, require_authenticated_user_or_api_token):
        app.dependency_overrides[dep] = lambda: principal
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


def user(uid):
    return PublicUser(id=uid, username=f"u{uid}", first_name="F", last_name="L", email=f"u{uid}@x.invalid", user_uuid=f"user_{uid}")


def token(org_id=1, **rights):
    return APITokenUser(org_id=org_id, rights={"courses": rights}, token_name="t")


BODY = {"audience": "custom", "mode": "required", "rule": {"departments": ["maal"]}}


async def test_get_without_audience(db, world):
    async with client(db, user(ADMIN)) as c:
        r = await c.get(f"{BASE}/course_1/audience")
    assert r.status_code == 200 and r.json() == {"audience": None}


async def test_preview_put_get_delete_roundtrip(db, world):
    async with client(db, user(ADMIN)) as c:
        p = await c.post(f"{BASE}/course_1/audience/preview", json=BODY)
        assert p.status_code == 200
        assert p.json() == {"matched_count": 1, "sample": [{"user_id": 10, "name": "F L", "email": "maal@example.invalid"}], "would_enroll": 1}
        put = await c.put(f"{BASE}/course_1/audience", json=BODY)
        assert put.json() == {"memberships_added": 1, "memberships_removed": 0, "enrolled": 1, "enroll_queued": 0, "enroll_failed": 0, "matched_count": 1}
        g = (await c.get(f"{BASE}/course_1/audience")).json()
        assert g["audience"] == "custom" and g["mode"] == "required" and g["matched_count"] == 1
        assert g["rule"] == {"departments": ["maal"], "levels": [], "roles": []} and isinstance(g["usergroup_id"], int)
        d = await c.delete(f"{BASE}/course_1/audience")
        assert d.status_code == 200 and (await c.get(f"{BASE}/course_1/audience")).json() == {"audience": None}


async def test_preview_writes_nothing(db, world):
    from sqlalchemy import select

    from src.db.mka_course_audience import MkaCourseAudience
    from src.db.trail_runs import TrailRun

    async with client(db, user(ADMIN)) as c:
        await c.post(f"{BASE}/course_1/audience/preview", json=BODY)
    assert (await db.execute(select(MkaCourseAudience))).scalars().all() == []
    assert (await db.execute(select(TrailRun))).scalars().all() == []


async def test_validation_errors(db, world):
    async with client(db, user(ADMIN)) as c:
        for body in (
            {"audience": "nope", "mode": "required"},
            {"audience": "custom", "mode": "required"},
            {"audience": "custom", "mode": "required", "rule": {"departments": ["zzz"]}},
            {"audience": "custom", "mode": "optin", "rule": {"x": 1}},
        ):
            assert (await c.put(f"{BASE}/course_1/audience", json=body)).status_code == 422


async def test_learner_forbidden_and_unknown_course_404(db, world):
    async with client(db, user(LEARNER)) as c:
        assert (await c.get(f"{BASE}/course_1/audience")).status_code == 403
        assert (await c.put(f"{BASE}/course_1/audience", json=BODY)).status_code == 403
        assert (await c.get(f"{BASE}/nope/audience")).status_code == 404


async def test_cross_org_admin_denied(db, world):
    async with client(db, user(ADMIN)) as c:  # admin of org 1 against org 2's course
        assert (await c.get(f"{BASE}/course_2/audience")).status_code == 403
        assert (await c.put(f"{BASE}/course_2/audience", json=BODY)).status_code == 403


async def test_api_token_rules(db, world):
    async with client(db, token(action_update=True, action_read=True)) as c:
        assert (await c.put(f"{BASE}/course_1/audience", json=BODY)).status_code == 200
        assert (await c.put(f"{BASE}/course_2/audience", json=BODY)).status_code == 403  # other org
    async with client(db, token(action_read=True)) as c:
        assert (await c.get(f"{BASE}/course_1/audience")).status_code == 200
        assert (await c.put(f"{BASE}/course_1/audience", json=BODY)).status_code == 403  # no update right
    async with client(db, token(org_id=2, action_update=True, action_read=True)) as c:
        assert (await c.get(f"{BASE}/course_1/audience")).status_code == 403


async def test_flag_off_get_works_writes_404(db, world, monkeypatch):
    monkeypatch.setenv("MKA_COURSE_AUDIENCE_ENABLED", "false")
    async with client(db, user(ADMIN)) as c:
        assert (await c.get(f"{BASE}/course_1/audience")).status_code == 200
        assert (await c.put(f"{BASE}/course_1/audience", json=BODY)).status_code == 404
        assert (await c.delete(f"{BASE}/course_1/audience")).status_code == 404
    from sqlalchemy import select

    from src.db.mka_course_audience import MkaCourseAudience

    assert (await db.execute(select(MkaCourseAudience))).scalars().all() == []


async def test_options(db, world):
    async with client(db, user(LEARNER)) as c:
        r = await c.get(f"{BASE}/audience/options", params={"org_id": 1})
        assert r.status_code == 200
        body = r.json()
        assert {"key": "maal", "name": "Maal"} in body["departments"] or any(d["key"] == "maal" for d in body["departments"])
        assert [x["key"] for x in body["levels"]] == ["national", "regional", "local"]
        assert any(x["key"] == "qaid" for x in body["roles"])
        assert (await c.get(f"{BASE}/audience/options", params={"org_id": 2})).status_code == 403
