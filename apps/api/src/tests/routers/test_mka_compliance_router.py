"""MKA fork: /mka/compliance (spec section 6): scope matrix, cross-tenant, out-of-scope 404, aggregation with
not_signed_in, CSV scoping, import idempotency / bad rows, pagination bounds, contact self-check."""

from datetime import datetime

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlmodel import select

from src.core.events.database import get_db_session
from src.db.api_tokens import APIToken
from src.db.mka_compliance import MkaComplianceCycle, MkaComplianceCycleCourse, MkaComplianceExpected
from src.db.organization_config import OrganizationConfig
from src.db.users import PublicUser
from src.security.api_token_utils import require_authenticated_user_or_api_token
from src.security.auth import get_authenticated_user, get_current_user
from src.services.api_tokens.api_tokens import generate_api_token
from src.services.mka import compliance as svc
from src.tests.routers.mka_compliance_world import build_world

BASE = "/api/v1/mka/compliance"
MID = "2026-11-16"


@pytest.fixture
async def world(db, org, other_org, admin_user, regular_user):
    for o in (org, other_org):  # the upstream token pattern reads the org plan from its config
        db.add(OrganizationConfig(org_id=o.id, config={"config_version": "2.0"},
                                  creation_date=str(datetime.now()), update_date=str(datetime.now())))
    await db.commit()
    return await build_world(db, org, other_org, admin_user, regular_user)


@pytest.fixture(autouse=True)
def freeze_today(monkeypatch):
    monkeypatch.setattr(svc, "today", lambda: MID)


def _app(db):
    from src.router import v1_router

    app = FastAPI()
    app.include_router(v1_router)
    app.dependency_overrides[get_db_session] = lambda: db
    return app


def client_for(db, uid):
    from src.db.users import User  # noqa: F401  (ensure mapper)

    app = _app(db)
    user = PublicUser(id=uid, username=f"u{uid}", first_name="F", last_name="L", email=f"u{uid}@x.invalid",
                      user_uuid=f"user_{uid}")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_authenticated_user] = lambda: user
    app.dependency_overrides[require_authenticated_user_or_api_token] = lambda: user
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


@pytest.fixture
async def token_client(db, org, world):
    full, prefix, hashed = generate_api_token()
    db.add(APIToken(name="prov", token_uuid="apitoken_c", token_prefix=prefix, token_hash=hashed,
                    org_id=org.id, created_by_user_id=1,
                    rights={**{r: {"action_read": True, "action_update": True} for r in ("courses", "activities", "assignments", "coursechapters", "usergroups", "certifications")}},
                    creation_date=str(datetime.now()), update_date=str(datetime.now())))
    await db.commit()
    app = _app(db)  # real auth path, no overrides
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t",
                           headers={"Authorization": f"Bearer {full}"}) as c:
        yield c


def q(org, **extra):
    return {"org_id": org.id, **extra}


# ---------------------------------------------------------------------------------------------------------
# scope matrix
# ---------------------------------------------------------------------------------------------------------

ALL_VIEWERS = {
    "admin": 1, "maintainer": 20, "org_update_role": 21, "national_aitmad_attributes": 22,
}
NO_ACCESS = {
    "plain_user": 2, "inactive_author": 24, "reporter_only": 27,
    "local_sadr_attributes": 25,        # a Majlis-level Sadr must NOT see every region
    "stale_national_attributes": 26,    # fail closed
}


@pytest.mark.asyncio
@pytest.mark.parametrize("name,uid", ALL_VIEWERS.items())
async def test_scope_all(db, org, world, name, uid):
    async with client_for(db, uid) as c:
        r = await c.get(f"{BASE}/scope", params=q(org))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["scope"] == "all"
        assert {x["course_uuid"] for x in body["courses"]} == {"course_general", "course_tabligh", "course_maal"}
        assert body["departments"] == ["maal", "tabligh"]
        assert body["cycle"]["label"] == "2026-27"
        assert [c["label"] for c in body["cycles"]] == ["2026-27"]
        assert r.headers["cache-control"] == "private, no-store"
        assert (await c.get(f"{BASE}/overview", params=q(org))).status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("name,uid", NO_ACCESS.items())
async def test_scope_none_and_everything_else_is_403(db, org, world, name, uid):
    async with client_for(db, uid) as c:
        r = await c.get(f"{BASE}/scope", params=q(org))
        assert r.status_code == 200 and r.json() == {"scope": "none", "cycle": r.json()["cycle"], "cycles": r.json()["cycles"], "courses": [], "departments": []}
        assert (await c.get(f"{BASE}/overview", params=q(org))).status_code == 403
        for path in ("summary", "learners", "learners.csv", "trend"):
            assert (await c.get(f"{BASE}/courses/course_tabligh/{path}", params=q(org))).status_code == 403, path


@pytest.mark.asyncio
async def test_scope_own_for_active_author_sees_only_their_course(db, org, world):
    async with client_for(db, 23) as c:  # ACTIVE CREATOR of the tabligh course
        body = (await c.get(f"{BASE}/scope", params=q(org))).json()
        assert body["scope"] == "own"
        assert [x["course_uuid"] for x in body["courses"]] == ["course_tabligh"]
        assert body["departments"] == ["tabligh"]
        assert (await c.get(f"{BASE}/overview", params=q(org))).status_code == 403  # scope all only
        assert (await c.get(f"{BASE}/courses/course_tabligh/summary", params=q(org))).status_code == 200
        assert (await c.get(f"{BASE}/courses/course_tabligh/learners", params=q(org))).status_code == 200
        assert (await c.get(f"{BASE}/courses/course_tabligh/learners.csv", params=q(org))).status_code == 200
        assert (await c.get(f"{BASE}/courses/course_tabligh/trend", params=q(org))).status_code == 200


@pytest.mark.asyncio
async def test_contributor_of_general_course_is_own_scope(db, org, world):
    async with client_for(db, 28) as c:
        body = (await c.get(f"{BASE}/scope", params=q(org))).json()
        assert body["scope"] == "own" and [x["course_uuid"] for x in body["courses"]] == ["course_general"]


@pytest.mark.asyncio
async def test_out_of_scope_course_is_404_and_looks_like_a_missing_one(db, org, world):
    async with client_for(db, 23) as c:
        for path in ("summary", "learners", "learners.csv", "trend"):
            other = await c.get(f"{BASE}/courses/course_maal/{path}", params=q(org))              # real, not mine
            missing = await c.get(f"{BASE}/courses/course_does_not_exist/{path}", params=q(org))  # not real
            foreign = await c.get(f"{BASE}/courses/course_o2_general/{path}", params=q(org))      # other org
            assert other.status_code == missing.status_code == foreign.status_code == 404, path
            assert other.json() == missing.json() == foreign.json()


@pytest.mark.asyncio
async def test_non_member_cannot_use_an_org(db, org, other_org, world):
    async with client_for(db, 40) as c:  # org-2 admin
        assert (await c.get(f"{BASE}/scope", params=q(org))).status_code == 403
        assert (await c.get(f"{BASE}/overview", params=q(org))).status_code == 403
        assert (await c.get(f"{BASE}/scope", params={"org_slug": org.slug})).status_code == 403


@pytest.mark.asyncio
async def test_org_is_required_and_unauthenticated_is_401(db, org, world):
    async with client_for(db, 1) as c:
        assert (await c.get(f"{BASE}/scope")).status_code == 422
    async with AsyncClient(transport=ASGITransport(app=_app(db)), base_url="http://t") as c:
        assert (await c.get(f"{BASE}/scope", params={"org_id": org.id})).status_code == 401


@pytest.mark.asyncio
async def test_token_is_scope_all_for_its_own_org_only(token_client, org, other_org):
    r = await token_client.get(f"{BASE}/scope", params={"org_slug": org.slug})
    assert r.status_code == 200 and r.json()["scope"] == "all"
    assert (await token_client.get(f"{BASE}/overview", params={"org_slug": org.slug})).status_code == 200
    assert (await token_client.get(f"{BASE}/scope", params={"org_slug": other_org.slug})).status_code == 403
    assert (await token_client.get(f"{BASE}/overview", params={"org_slug": other_org.slug})).status_code == 403
    assert (await token_client.get(f"{BASE}/scope")).status_code == 422
    # a token never gets 'own', and a foreign org_id next to its own slug is refused (upstream org-boundary check)
    assert (await token_client.get(f"{BASE}/scope", params={"org_slug": org.slug, "org_id": other_org.id})).status_code == 403
    assert (await token_client.get(f"{BASE}/courses/course_o2_general/summary", params={"org_slug": org.slug})).status_code == 404


# ---------------------------------------------------------------------------------------------------------
# cross-tenant
# ---------------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cross_tenant_reads(db, org, other_org, world):
    async with client_for(db, 40) as c:  # org-2 admin
        ov = (await c.get(f"{BASE}/overview", params=q(other_org))).json()
        assert ov["totals"]["expected"] == 3                       # only org 2's roster
        assert ov["totals"]["attested"] == 1                       # o2.l1 attested in org 2's course
        assert {d["department"] for d in ov["departments"]} == {"executive"}
        # org 1's cycle id / course uuid are invisible to org 2
        assert (await c.get(f"{BASE}/overview", params=q(other_org, cycle_id=world.cycle.id))).status_code == 404
        for path in ("summary", "learners", "learners.csv", "trend"):
            assert (await c.get(f"{BASE}/courses/course_general/{path}", params=q(other_org))).status_code == 404
        sc = (await c.get(f"{BASE}/scope", params=q(other_org))).json()
        assert [x["course_uuid"] for x in sc["courses"]] == ["course_o2_general"]


@pytest.mark.asyncio
async def test_roster_email_of_a_user_in_another_org_stays_not_signed_in(db, org, world):
    async with client_for(db, 1) as c:
        items = (await c.get(f"{BASE}/courses/course_tabligh/learners", params=q(org, q="crossorg"))).json()["items"]
    assert len(items) == 1 and items[0]["signed_in"] is False and items[0]["stage"] == "not_signed_in"


@pytest.mark.asyncio
async def test_org1_admin_cannot_pass_org2_id(db, org, other_org, world):
    async with client_for(db, 1) as c:
        assert (await c.get(f"{BASE}/overview", params=q(other_org))).status_code == 403


@pytest.mark.asyncio
async def test_other_orgs_progress_never_counts(db, org, world):
    """o2.l1 attested in org 2 does not leak into org 1 (different org, different roster)."""
    async with client_for(db, 1) as c:
        ov = (await c.get(f"{BASE}/overview", params=q(org))).json()
    assert ov["totals"]["expected"] == 10


# ---------------------------------------------------------------------------------------------------------
# aggregation correctness (incl. not_signed_in)
# ---------------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_overview_totals_departments_cells_and_attention(db, org, world):
    async with client_for(db, 1) as c:
        ov = (await c.get(f"{BASE}/overview", params=q(org))).json()
    assert ov["cycle"]["label"] == "2026-27" and ov["as_of"] == MID
    assert ov["totals"] == {"expected": 10, "not_signed_in": 5, "not_started": 1, "in_progress": 1,
                            "completed": 1, "attested": 2, "overdue": 0}
    depts = {d["department"]: d for d in ov["departments"]}
    assert set(depts) == {"tabligh", "maal", "executive"}
    t = depts["tabligh"]  # l1 attested, l2 completed, ghost1/crossorg/head never signed in
    assert (t["expected"], t["attested"], t["completed"], t["not_signed_in"]) == (5, 1, 1, 3)
    assert t["attested_pct"] == 20.0 and t["expected_attested_pct"] == 50.0
    assert t["rag"] in ("amber", "red") and any("never signed in" in r for r in t["reasons"])
    assert t["contact_mismatches"] == 2
    m = depts["maal"]  # l3 in progress, l4 not started, ghost2 never signed in
    assert (m["expected"], m["in_progress"], m["not_started"], m["not_signed_in"]) == (3, 1, 1, 1)
    ex = depts["executive"]     # exec: general course only; ex attested, rq.ne never signed in
    assert (ex["expected"], ex["attested"], ex["not_signed_in"]) == (2, 1, 1)
    cells = {(x["department"], x["region"]): x for x in ov["cells"]}
    assert cells[("tabligh", "Northeast")]["expected"] == 3          # l1, l2, crossorg twin
    assert cells[("tabligh", "Southwest")]["expected"] == 1          # ghost1
    assert cells[("maal", "Northeast")]["expected"] == 2             # l3, l4
    assert sum(x["expected"] for x in ov["cells"]) == 10
    assert ov["attention"] and ov["attention"][0]["rag"] in ("red", "amber")
    assert set(ov["attention"][0]) == {"department", "department_name", "region", "rag", "score", "reasons", "expected", "attested",
                                       "attested_pct", "overdue", "not_signed_in", "not_started"}
    assert {c["rag"] for c in ov["cells"]} <= {"green", "amber", "red", "none"}
    assert all(a["rag"] in ("red", "amber") for a in ov["attention"])


@pytest.mark.asyncio
async def test_overview_after_the_deadline_marks_everyone_not_attested_overdue(db, org, world, monkeypatch):
    monkeypatch.setattr(svc, "today", lambda: "2026-12-05")
    async with client_for(db, 1) as c:
        ov = (await c.get(f"{BASE}/overview", params=q(org))).json()
    assert ov["totals"]["overdue"] == 8 and ov["totals"]["attested"] == 2
    assert any(d["rag"] == "red" and any("overdue" in r for r in d["reasons"]) for d in ov["departments"])


@pytest.mark.asyncio
async def test_course_summary_breakdowns(db, org, world):
    async with client_for(db, 1) as c:
        s = (await c.get(f"{BASE}/courses/course_tabligh/summary", params=q(org))).json()
    assert s["course"] == {"course_uuid": "course_tabligh", "name": "Tabligh 2026-27", "kind": "department",
                           "department": "tabligh", "department_name": "Tabligh"}
    assert s["lessons_total"] == 2  # unpublished + assignment activities excluded
    assert s["totals"] == {"expected": 5, "not_signed_in": 3, "not_started": 0, "in_progress": 0,
                           "completed": 1, "attested": 1, "overdue": 0}
    by_region = {r["region"]: r for r in s["by_region"]}
    assert by_region["Northeast"]["expected"] == 3 and by_region["Southwest"]["expected"] == 1 and by_region[None]["expected"] == 1
    assert {m["majlis"] for m in s["by_majlis"]} == {"Albany", "Boston", "Dallas", None}
    assert {lv["level"] for lv in s["by_level"]} == {"local", "national"}
    assert s["rag"] in ("amber", "red") and s["reasons"]


@pytest.mark.asyncio
async def test_general_course_covers_everyone_with_per_course_status(db, org, world):
    async with client_for(db, 1) as c:
        body = (await c.get(f"{BASE}/courses/course_general/learners", params=q(org, page_size=200))).json()
    assert body["total"] == 10
    by = {i["email"]: i for i in body["items"]}
    assert by["l1@example.invalid"]["status"] == "attested" and by["l1@example.invalid"]["lessons_done"] == 3
    assert by["l1@example.invalid"]["lessons_total"] == 3
    assert by["l2@example.invalid"]["status"] == "completed"
    assert by["l3@example.invalid"]["status"] == "in_progress" and by["l3@example.invalid"]["lessons_done"] == 1
    assert by["l4@example.invalid"]["status"] == "not_started" and by["l4@example.invalid"]["signed_in"] is True
    assert by["ghost1@example.invalid"]["status"] == "not_signed_in" and by["ghost1@example.invalid"]["lessons_total"] == 3
    assert by["ex@example.invalid"]["status"] == "attested"


@pytest.mark.asyncio
async def test_learners_filters_search_sort_and_pagination(db, org, world):
    async with client_for(db, 23) as c:  # tabligh author
        p = lambda **kw: q(org, **kw)  # noqa: E731
        base = f"{BASE}/courses/course_tabligh/learners"
        allrows = (await c.get(base, params=p())).json()
        assert allrows["total"] == 5 and allrows["page"] == 1 and allrows["page_size"] == 50
        assert {i["department"] for i in allrows["items"]} == {"tabligh"}      # never another department's rows
        assert "l3@example.invalid" not in {i["email"] for i in allrows["items"]}
        nsi = (await c.get(base, params=p(status="not_signed_in"))).json()
        assert nsi["total"] == 3
        assert (await c.get(base, params=p(status="attested,completed"))).json()["total"] == 2
        assert (await c.get(base, params=p(region="Southwest"))).json()["total"] == 1
        assert (await c.get(base, params=p(majlis="albany"))).json()["total"] == 2   # l1 + crossorg twin
        assert (await c.get(base, params=p(level="national"))).json()["total"] == 1
        assert (await c.get(base, params=p(q="jane doe"))).json()["items"][0]["email"] == "head.tabligh@example.invalid"
        page1 = (await c.get(base, params=p(page_size=2, sort="name"))).json()
        page3 = (await c.get(base, params=p(page_size=2, page=3, sort="name"))).json()
        assert len(page1["items"]) == 2 and len(page3["items"]) == 1 and page1["total"] == 5
        desc = (await c.get(base, params=p(sort="-name", page_size=1))).json()["items"][0]["email"]
        asc = (await c.get(base, params=p(sort="name", page_size=1))).json()["items"][0]["email"]
        assert desc > asc
        assert (await c.get(base, params=p(sort="nonsense"))).status_code == 200      # unknown sort falls back, no 500
        worst = (await c.get(base, params=p())).json()["items"]                      # default: most urgent first
        assert worst[0]["stage"] == "not_signed_in" and worst[-1]["status"] == "attested"
        assert (await c.get(base, params=p(sort="progress"))).json()["items"][-1]["lessons_done"] == 2
        # bare uuid is accepted too, and the response always carries the prefixed LearnHouse uuid
        r = await c.get(f"{BASE}/courses/tabligh/summary", params=p())
        assert r.status_code == 200 and r.json()["course"]["course_uuid"] == "course_tabligh"


@pytest.mark.asyncio
async def test_pagination_and_input_bounds(db, org, world):
    async with client_for(db, 1) as c:
        base = f"{BASE}/courses/course_general/learners"
        assert (await c.get(base, params=q(org, page_size=200))).status_code == 200
        assert (await c.get(base, params=q(org, page_size=201))).status_code == 422
        assert (await c.get(base, params=q(org, page_size=0))).status_code == 422
        assert (await c.get(base, params=q(org, page=0))).status_code == 422
        assert (await c.get(base, params=q(org, q="x" * 101))).status_code == 422
        assert (await c.get(base, params=q(org, status="x" * 201))).status_code == 422


@pytest.mark.asyncio
async def test_contact_self_check(db, org, world):
    async with client_for(db, 1) as c:
        items = {i["email"]: i for i in (await c.get(f"{BASE}/courses/course_tabligh/learners", params=q(org))).json()["items"]}
        general = {i["email"]: i for i in (await c.get(f"{BASE}/courses/course_general/learners", params=q(org, page_size=200))).json()["items"]}
    ok = items["l1@example.invalid"]["contact_check"]
    assert ok["mismatch"] is False and ok["answers"] == {"majlis": "Albany", "regional_qaid": "Rob Qaid", "dept_head": "Jane Doe"}
    bad = items["l2@example.invalid"]["contact_check"]  # picked Albany but is Boston; named the wrong Regional Qaid
    assert bad["mismatch"] is True and sorted(bad["mismatch_fields"]) == ["majlis", "regional_qaid"]
    assert items["ghost1@example.invalid"]["contact_check"] == {"answers": None, "mismatch": None}  # not answered
    # the general course has no contact-check assignment configured
    assert general["l1@example.invalid"]["contact_check"] == {"answers": None, "mismatch": None}


@pytest.mark.asyncio
async def test_trend_is_cumulative_and_stops_at_today(db, org, world):
    async with client_for(db, 1) as c:
        t = (await c.get(f"{BASE}/courses/course_tabligh/trend", params=q(org))).json()
    s = {p["date"]: p for p in t["series"]}
    assert t["series"][0]["date"] == "2026-11-01" and t["series"][-1]["date"] == MID and t["expected"] == 5
    assert s["2026-11-04"]["completed"] == 0
    assert s["2026-11-05"]["completed"] == 1           # l1 finished the last lesson on 11-05
    assert s["2026-11-09"]["completed"] == 2           # l2 on 11-09
    assert s["2026-11-06"]["attested"] == 0 and s["2026-11-07"]["attested"] == 1
    assert s[MID]["attested"] == 1 and s[MID]["expected_attested"] == pytest.approx(2.5)


@pytest.mark.asyncio
async def test_no_cycle_yet_gives_empty_states_not_errors(db, org, other_org, admin_user, regular_user):
    async with client_for(db, 1) as c:
        sc = (await c.get(f"{BASE}/scope", params=q(org))).json()
        ov = (await c.get(f"{BASE}/overview", params=q(org))).json()
        course = await c.get(f"{BASE}/courses/anything/summary", params=q(org))
    assert sc == {"scope": "all", "cycle": None, "cycles": [], "courses": [], "departments": []}
    assert ov["cycle"] is None and ov["totals"]["expected"] == 0 and ov["departments"] == [] and ov["cells"] == []
    assert course.status_code == 404


@pytest.mark.asyncio
async def test_cycle_with_no_roster_reads_as_zero_expected(db, org, world):
    await db.execute(MkaComplianceExpected.__table__.delete().where(MkaComplianceExpected.org_id == org.id))
    await db.commit()
    async with client_for(db, 1) as c:
        ov = (await c.get(f"{BASE}/overview", params=q(org))).json()
        lr = (await c.get(f"{BASE}/courses/course_general/learners", params=q(org))).json()
    assert ov["totals"]["expected"] == 0 and lr["total"] == 0 and lr["items"] == []


# ---------------------------------------------------------------------------------------------------------
# CSV (chase list)
# ---------------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_csv_is_scoped_filtered_and_injection_safe(db, org, world):
    async with client_for(db, 23) as c:
        r = await c.get(f"{BASE}/courses/course_tabligh/learners.csv", params=q(org))
        none_owned = await c.get(f"{BASE}/courses/course_maal/learners.csv", params=q(org))
    assert r.status_code == 200 and none_owned.status_code == 404
    assert r.headers["content-type"].startswith("text/csv")
    assert r.headers["cache-control"] == "private, no-store" and r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["content-disposition"] == 'attachment; filename="chase-list-course_tabligh.csv"'
    lines = r.text.strip().split("\r\n")
    assert lines[0].lstrip("\ufeff").startswith("Department,Role,Level,Region,Majlis,Name,Mailbox,Status")
    emails = [ln for ln in lines[1:]]
    body = "\r\n".join(lines[1:])
    # attested learner is not on the chase list; other departments never appear; the rest of this course does
    assert "l1@example.invalid" not in body
    for other in ("l3@example.invalid", "l4@example.invalid", "ghost2@example.invalid", "ex@example.invalid"):
        assert other not in body
    for mine in ("l2@example.invalid", "ghost1@example.invalid", "crossorg@example.invalid", "head.tabligh@example.invalid"):
        assert mine in body
    assert len(emails) == 4
    # CSV/formula injection: the name that starts with '=' is prefixed with a quote (and quoted for the comma)
    assert "\"'=HYPERLINK(" in body and ",=HYPERLINK" not in body


@pytest.mark.asyncio
async def test_csv_respects_filters_and_orders_overdue_first(db, org, world, monkeypatch):
    monkeypatch.setattr(svc, "today", lambda: "2026-12-05")
    async with client_for(db, 1) as c:
        r = await c.get(f"{BASE}/courses/course_tabligh/learners.csv", params=q(org, stage="not_signed_in", region="Southwest"))
    rows = r.text.strip().split("\r\n")
    assert len(rows) == 2 and "ghost1@example.invalid" in rows[1] and ",overdue," in rows[1]


@pytest.mark.asyncio
async def test_csv_for_another_org_or_missing_course_is_404(db, org, other_org, world):
    async with client_for(db, 40) as c:
        assert (await c.get(f"{BASE}/courses/course_tabligh/learners.csv", params=q(other_org))).status_code == 404


# ---------------------------------------------------------------------------------------------------------
# import
# ---------------------------------------------------------------------------------------------------------

def cycle_payload():
    """The shape of the provisioner's out/cycle-courses.json (with its extra keys)."""
    return {
        "cycle": "2027-28", "deadline": "2027-12-01", "generatedAt": "2026-10-05T02:50:15.750Z",
        "courses": [
            {"kind": "general", "department": "", "course_uuid": "course_general", "activities": [{"key": "plan"}],
             "signoff": {"activity_uuid": "activity_1005", "assignment_uuid": "assignment_5001", "task_uuids": {"confirm": "x"}},
             "contact_check": None},
            {"kind": "department", "department": "Tabligh", "course_uuid": "course_tabligh",
             "signoff": {"assignment_uuid": "assignment_5002"},
             "contact_check": {"assignment_uuid": "assignment_5003", "task_uuids": {"name-contacts": "y"}}},
        ],
    }


@pytest.mark.asyncio
async def test_import_cycle_session_admin_idempotent(db, org, world):
    async with client_for(db, 1) as c:
        first = (await c.post(f"{BASE}/cycles", params=q(org), json=cycle_payload())).json()
        again = (await c.post(f"{BASE}/cycles", params=q(org), json=cycle_payload())).json()
    assert first["cycle"]["action"] == "created" and first["ok"] == 2 and first["failed"] == 0
    assert [r["action"] for r in first["courses"]] == ["created", "created"]
    assert again["cycle"]["action"] == "updated" and again["cycle"]["id"] == first["cycle"]["id"]
    assert [r["action"] for r in again["courses"]] == ["updated", "updated"]
    cycles = (await db.execute(select(MkaComplianceCycle).where(MkaComplianceCycle.org_id == org.id))).scalars().all()
    assert sorted(c.label for c in cycles) == ["2026-27", "2027-28"]
    new = next(c for c in cycles if c.label == "2027-28")
    assert new.deadline_on.isoformat() == "2027-12-01" and new.starts_on.isoformat() == "2027-11-01"  # 30-day default
    links = (await db.execute(select(MkaComplianceCycleCourse).where(MkaComplianceCycleCourse.cycle_id == new.id))).scalars().all()
    assert len(links) == 2 and all(lk.org_id == org.id for lk in links)
    t = next(lk for lk in links if lk.course_uuid == "course_tabligh")
    assert (t.department, t.signoff_assignment_id, t.contact_check_assignment_id) == ("tabligh", 5002, 5003)


@pytest.mark.asyncio
async def test_import_cycle_bad_courses_are_per_row_errors(db, org, other_org, world):
    payload = cycle_payload()
    payload["courses"] += [
        {"kind": "department", "department": "maal", "course_uuid": "course_o2_general"},            # other org's course
        {"kind": "department", "department": "maal", "course_uuid": "course_maal",
         "signoff": {"assignment_uuid": "assignment_5002"}},                                            # assignment of another course
        {"kind": "weird", "course_uuid": "course_maal"},
        {"kind": "department", "course_uuid": "course_maal"},                                          # department missing
        "not an object",
        {"kind": "department", "department": "maal", "course_uuid": "course_maal",
         "signoff": {"assignment_uuid": "assignment_5004"}},                                            # good one after the bad ones
    ]
    async with client_for(db, 1) as c:
        body = (await c.post(f"{BASE}/cycles", params=q(org), json=payload)).json()
    assert body["ok"] == 3 and body["failed"] == 5
    errors = {r["row"]: r["error"] for r in body["courses"] if not r["ok"]}
    assert "not found in this organization" in errors[2]
    assert "assignment not found in this course" in errors[3]
    assert set(errors) == {2, 3, 4, 5, 6}


@pytest.mark.asyncio
async def test_import_cycle_validation_and_absent_vs_null_signoff(db, org, world):
    async with client_for(db, 1) as c:
        bad = await c.post(f"{BASE}/cycles", params=q(org), json={"cycle": "x", "deadline": "soon", "courses": []})
        assert bad.status_code == 422
        assert (await c.post(f"{BASE}/cycles", params=q(org), json={"cycle": "x", "courses": []})).status_code == 422
        assert (await c.post(f"{BASE}/cycles", params=q(org), json={"deadline": "2027-01-01", "courses": []})).status_code == 422
        # re-posting the existing cycle WITHOUT a signoff key keeps it; an explicit null clears it
        keep = {"cycle": "2026-27", "deadline": "2026-12-01", "courses": [{"kind": "general", "course_uuid": "course_general"}]}
        await c.post(f"{BASE}/cycles", params=q(org), json=keep)
        link = (await db.execute(select(MkaComplianceCycleCourse).where(MkaComplianceCycleCourse.course_uuid == "course_general"))).scalars().first()
        await db.refresh(link)
        assert link.signoff_assignment_id == 5001
        keep["courses"][0]["signoff"] = None
        await c.post(f"{BASE}/cycles", params=q(org), json=keep)
        await db.refresh(link)
        assert link.signoff_assignment_id is None


@pytest.mark.asyncio
async def test_import_requires_org_admin(db, org, other_org, world):
    for uid in (2, 20, 21, 22, 23):  # plain, maintainer, org-update role, attributes holder, author: none may import
        async with client_for(db, uid) as c:
            assert (await c.post(f"{BASE}/cycles", params=q(org), json=cycle_payload())).status_code == 403, uid
            assert (await c.post(f"{BASE}/expected/import", params=q(org), json={"cycle_id": world.cycle.id, "rows": []})).status_code == 403, uid
            assert (await c.delete(f"{BASE}/cycles/{world.cycle.id}/expected", params=q(org))).status_code == 403, uid
    async with client_for(db, 40) as c:   # an org-2 admin cannot import into org 1
        assert (await c.post(f"{BASE}/cycles", params=q(org), json=cycle_payload())).status_code == 403


@pytest.mark.asyncio
async def test_import_is_org_scoped_cross_tenant(db, org, other_org, world):
    async with client_for(db, 1) as c:
        # org 2's cycle id is unreachable for an org-1 admin
        assert (await c.post(f"{BASE}/expected/import", params=q(org), json={"cycle_id": world.cycle2.id, "rows": []})).status_code == 404
        assert (await c.delete(f"{BASE}/cycles/{world.cycle2.id}/expected", params=q(org))).status_code == 404
        # nor by label via the other org's identity
        assert (await c.post(f"{BASE}/expected/import", params=q(org), json={"cycle": "nope", "rows": []})).status_code == 404
    still = (await db.execute(select(MkaComplianceExpected).where(MkaComplianceExpected.cycle_id == world.cycle2.id))).scalars().all()
    assert len(still) == 3
    # a cycle created through org 2 carries org 2's id on every row
    async with client_for(db, 40) as c:
        pl = {"cycle": "2027-28", "deadline": "2027-12-01", "courses": [{"kind": "general", "course_uuid": "course_o2_general"}]}
        assert (await c.post(f"{BASE}/cycles", params=q(other_org), json=pl)).json()["ok"] == 1
        assert (await c.post(f"{BASE}/cycles", params=q(other_org), json={**pl, "courses": [{"kind": "general", "course_uuid": "course_general"}]})).json()["failed"] == 1


def row(email, **kw):
    return {"email": email, "department": "tabligh", "level": "local", "majlis": "Albany", "region": "Northeast",
            "role_title": "Nazim Tabligh", "person_name": "N", **kw}


@pytest.mark.asyncio
async def test_expected_import_idempotent_upsert_and_bad_rows(db, org, world):
    cid = world.cycle.id
    rows = [
        row("New.One@Example.Invalid"),                          # normalised to lower case
        row("new.two@example.invalid", appointed_on="2026-11-20", department="Maal", role_title="Nazim Maal"),
        row("l1@example.invalid", person_name="L One Renamed"),   # existing key: update, not duplicate
        row("not-an-email"),
        row("bad.level@example.invalid", level="galactic"),
        row("bad.date@example.invalid", appointed_on="yesterday"),
        row("bad.flag@example.invalid", formula_unconfirmed="yes"),
        row("long@example.invalid", role_title="x" * 201),
        "oops",
        row("dup@example.invalid", person_name="first"),
        row("dup@example.invalid", person_name="second"),        # later duplicate in the batch wins
    ]
    async with client_for(db, 1) as c:
        dry = (await c.post(f"{BASE}/expected/import", params=q(org), json={"cycle_id": cid, "rows": rows, "dry_run": True})).json()
        assert dry["dry_run"] is True and dry["created"] == 3 and dry["updated"] == 1 and dry["failed"] == 6
        assert (await db.execute(select(MkaComplianceExpected).where(MkaComplianceExpected.email == "new.one@example.invalid"))).first() is None
        body = (await c.post(f"{BASE}/expected/import", params=q(org), json={"cycle_id": cid, "rows": rows})).json()
        assert body["created"] == 3 and body["updated"] == 1 and body["unchanged"] == 0 and body["failed"] == 6
        assert {e["row"] for e in body["errors"]} == {3, 4, 5, 6, 7, 8}
        assert body["departments_without_course"] == []
        again = (await c.post(f"{BASE}/expected/import", params=q(org), json={"cycle": "2026-27", "rows": rows})).json()
        assert again["created"] == 0 and again["updated"] == 0 and again["unchanged"] == 4 and again["failed"] == 6
    total = (await db.execute(select(MkaComplianceExpected).where(MkaComplianceExpected.cycle_id == cid))).scalars().all()
    assert len(total) == 10 + 3
    new = next(r for r in total if r.email == "new.one@example.invalid")
    assert new.org_id == org.id
    dup = next(r for r in total if r.email == "dup@example.invalid")
    assert dup.person_name == "second"
    appt = next(r for r in total if r.email == "new.two@example.invalid")
    assert appt.department == "maal" and appt.appointed_on.isoformat() == "2026-11-20"


@pytest.mark.asyncio
async def test_expected_import_reports_departments_without_a_course(db, org, world):
    async with client_for(db, 1) as c:
        body = (await c.post(f"{BASE}/expected/import", params=q(org),
                             json={"cycle_id": world.cycle.id, "rows": [row("a1@example.invalid", department="tarbiyyat")]})).json()
    assert body["departments_without_course"] == ["tarbiyyat"]


@pytest.mark.asyncio
async def test_expected_import_batch_limit_and_unknown_fields(db, org, world):
    async with client_for(db, 1) as c:
        ok = await c.post(f"{BASE}/expected/import", params=q(org), json={"cycle_id": world.cycle.id, "rows": [row(f"b{i}@example.invalid") for i in range(2000)]})
        assert ok.status_code == 200 and ok.json()["created"] == 2000
        too_many = await c.post(f"{BASE}/expected/import", params=q(org), json={"cycle_id": world.cycle.id, "rows": [row(f"c{i}@example.invalid") for i in range(2001)]})
        assert too_many.status_code == 422
        assert (await c.post(f"{BASE}/expected/import", params=q(org), json={"cycle_id": world.cycle.id, "rows": [], "org_id": 2})).status_code == 422
        assert (await c.post(f"{BASE}/expected/import", params=q(org), json={"rows": []})).status_code == 422  # no cycle


@pytest.mark.asyncio
async def test_clear_expected_only_clears_that_cycle(db, org, other_org, world):
    async with client_for(db, 1) as c:
        r = await c.delete(f"{BASE}/cycles/{world.cycle.id}/expected", params=q(org))
        assert r.json() == {"cycle_id": world.cycle.id, "deleted": 10}
        assert (await c.delete(f"{BASE}/cycles/{world.cycle.id}/expected", params=q(org))).json()["deleted"] == 0
    left = (await db.execute(select(MkaComplianceExpected))).scalars().all()
    assert {r.org_id for r in left} == {other_org.id} and len(left) == 3


@pytest.mark.asyncio
async def test_token_can_import_for_its_own_org(token_client, org, other_org, db, world):
    p = {"org_slug": org.slug}
    first = await token_client.post(f"{BASE}/cycles", params=p, json=cycle_payload())
    assert first.status_code == 200, first.text
    assert first.json()["ok"] == 2
    cid = (await token_client.post(f"{BASE}/cycles", params=p, json=cycle_payload())).json()["cycle"]["id"]
    r = await token_client.post(f"{BASE}/expected/import", params=p, json={"cycle_id": cid, "rows": [row("tok@example.invalid")]})
    assert r.status_code == 200 and r.json()["created"] == 1
    assert (await token_client.delete(f"{BASE}/cycles/{cid}/expected", params=p)).json()["deleted"] == 1
    # other org: refused
    assert (await token_client.post(f"{BASE}/cycles", params={"org_slug": other_org.slug}, json=cycle_payload())).status_code == 403
    assert (await token_client.post(f"{BASE}/expected/import", params={"org_slug": other_org.slug}, json={"cycle_id": world.cycle2.id, "rows": []})).status_code == 403


# ---------------------------------------------------------------------------------------------------------
# routing
# ---------------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unauthenticated_everything_is_401(db, org, world):
    async with AsyncClient(transport=ASGITransport(app=_app(db)), base_url="http://t") as c:
        for path in ("scope", "overview", "courses/course_general/summary", "courses/course_general/learners.csv"):
            assert (await c.get(f"{BASE}/{path}", params={"org_id": org.id})).status_code == 401, path
        assert (await c.post(f"{BASE}/cycles", params={"org_id": org.id}, json=cycle_payload())).status_code == 401
