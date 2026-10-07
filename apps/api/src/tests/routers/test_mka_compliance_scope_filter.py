"""MKA fork seam C: attribute-based compliance scope (spec 2026-10-07 3.C). A Mohtamim / Qaid (and their Naibs) gets the
Compliance data of their department / region / Majlis ONLY: JSON, CSV, overview and Remind. Synthetic ``example.invalid``
world from ``mka_compliance_world`` (roster: Northeast = l1 l2 l3 l4 crossorg rq.ne; Albany = l1 l3 crossorg;
tabligh = l1 l2 ghost1 crossorg head.tabligh; Southwest = ghost1 ghost2)."""

import csv
import io

import pytest
from sqlmodel import select

from src.db.mka_automation import MkaAutomationSendLog
from src.db.mka_compliance import MkaComplianceExpected
from src.tests.routers.mka_compliance_world import add_attributes, add_user
from src.tests.routers.test_mka_automation_reminders_router import (  # noqa: F401  (fixtures: env is autouse)
    GENERAL, TABLIGH, count, env, on, real, transport, world,
)
from src.tests.routers.test_mka_compliance_router import BASE, client_for, freeze_today, q  # noqa: F401

E = "@example.invalid"
NE = {"l1", "l2", "l3", "l4", "crossorg", "rq.ne"}
ALBANY = {"l1", "l3", "crossorg"}
TABLIGH_PEOPLE = {"l1", "l2", "ghost1", "crossorg", "head.tabligh"}
SOUTHWEST = {"ghost1", "ghost2"}
EVERYONE = {"l1", "l2", "l3", "l4", "ghost1", "ghost2", "crossorg", "head.tabligh", "rq.ne", "ex"}

# name -> (uid, effective attributes, expected scope field, visible roster, kind label)
VIEWERS = {
    "regional_qaid": (50, dict(level="regional", role="regional_qaid", region="Northeast"), "region", NE),
    "regional_naib_qaid": (51, dict(level="regional", role="naib_qaid", region="Northeast"), "region", NE),
    "majlis_qaid": (52, dict(level="local", role="qaid", majlis="Albany", region="Northeast"), "majlis", ALBANY),
    "majlis_naib_qaid": (53, dict(level="local", role="naib_qaid", majlis="Albany", region="Northeast"), "majlis", ALBANY),
    "mohtamim": (54, dict(level="national", role="mohtamim", department="tabligh"), "department", TABLIGH_PEOPLE),
    "naib_mohtamim": (55, dict(level="national", role="naib_mohtamim", department="tabligh"), "department", TABLIGH_PEOPLE),
    "southwest_qaid": (56, dict(level="regional", role="regional_qaid", region="Southwest"), "region", SOUTHWEST),
}


@pytest.fixture
async def viewers(db, org, world):
    for name, (uid, eff, _field, _rows) in VIEWERS.items():
        email = f"{name}{E}"
        await add_user(db, org.id, uid, email, 4)
        await add_attributes(db, uid, email, **eff)
    # no usable unit: a Majlis Qaid without a Majlis, a Mohtamim without a department, an unproven address
    await add_user(db, org.id, 60, "qaid.nomajlis@example.invalid", 4)
    await add_attributes(db, 60, "qaid.nomajlis@example.invalid", level="local", role="qaid", region="Northeast")
    await add_user(db, org.id, 61, "mohtamim.nodept@example.invalid", 4)
    await add_attributes(db, 61, "mohtamim.nodept@example.invalid", level="national", role="mohtamim")
    await add_user(db, org.id, 62, "qaid.unproven@example.invalid", 4)
    await add_attributes(db, 62, "qaid.unproven@example.invalid", level="local", role="qaid", majlis="Albany", email_seen="other@example.invalid")
    return world


def locals_of(items):
    return {i["email"].split("@")[0] for i in items}


async def learners(c, org, uuid="course_general", **extra):
    r = await c.get(f"{BASE}/courses/{uuid}/learners", params=q(org, page_size=200, **extra))
    assert r.status_code == 200, r.text
    return r.json()


async def csv_people(c, org, uuid="course_general", **extra):
    r = await c.get(f"{BASE}/courses/{uuid}/learners.csv", params=q(org, **extra))
    assert r.status_code == 200, r.text
    rows = list(csv.DictReader(io.StringIO(r.text.lstrip("﻿"))))
    return {row["Mailbox"].split("@")[0] for row in rows}, r.text


# ---------------------------------------------------------------------------------------------------------
# /scope
# ---------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("name", VIEWERS)
async def test_scope_reports_the_filter_and_stays_backward_compatible(db, org, viewers, name):
    uid, _eff, field, _rows = VIEWERS[name]
    async with client_for(db, uid) as c:
        r = await c.get(f"{BASE}/scope", params=q(org))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["scope"] == "own"  # legacy string: limited, NEVER 'all'
    assert body["kind"] == "filtered"
    flt = body["filter"]
    assert flt["field"] == field and flt[field] == flt["value"] and flt["label"].startswith("Your ")
    assert body["cycle"]["label"] == "2026-27" and body["courses"]
    assert r.headers["cache-control"] == "private, no-store"


async def test_scope_labels(db, org, viewers):
    async with client_for(db, 52) as c:
        assert (await c.get(f"{BASE}/scope", params=q(org))).json()["filter"] == {
            "field": "majlis", "value": "Albany", "majlis": "Albany", "label": "Your Majlis: Albany"}
    async with client_for(db, 50) as c:
        assert (await c.get(f"{BASE}/scope", params=q(org))).json()["filter"]["label"] == "Your region: Northeast"
    async with client_for(db, 54) as c:
        body = (await c.get(f"{BASE}/scope", params=q(org))).json()
    assert body["filter"]["label"] == "Your department: tabligh"
    # a department-filtered viewer sees the general course and their own department course, not Maal's
    assert {x["course_uuid"] for x in body["courses"]} == {"course_general", "course_tabligh"}
    assert body["departments"] == ["tabligh"]


async def test_other_viewers_report_no_filter(db, org, viewers):
    async with client_for(db, 1) as c:
        body = (await c.get(f"{BASE}/scope", params=q(org))).json()
    assert body["scope"] == body["kind"] == "all" and body["filter"] is None
    async with client_for(db, 23) as c:  # course author keeps `own`
        body = (await c.get(f"{BASE}/scope", params=q(org))).json()
    assert body["scope"] == body["kind"] == "own" and body["filter"] is None
    async with client_for(db, 2) as c:
        body = (await c.get(f"{BASE}/scope", params=q(org))).json()
    assert body["scope"] == body["kind"] == "none" and body["filter"] is None


@pytest.mark.parametrize("uid", [60, 61, 62, 25])  # no unit, no unit, address not proven, local Sadr
async def test_attribute_holders_without_a_usable_unit_get_nothing(db, org, viewers, uid):
    async with client_for(db, uid) as c:
        body = (await c.get(f"{BASE}/scope", params=q(org))).json()
        assert body["scope"] == body["kind"] == "none" and body["filter"] is None and body["courses"] == []
        assert (await c.get(f"{BASE}/overview", params=q(org))).status_code == 403
        assert (await c.get(f"{BASE}/courses/course_general/learners", params=q(org))).status_code == 403
        assert (await c.get(f"{BASE}/courses/course_general/learners.csv", params=q(org))).status_code == 403


# ---------------------------------------------------------------------------------------------------------
# learners JSON + CSV: never another unit's rows
# ---------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("name", VIEWERS)
async def test_learners_json_and_csv_contain_only_the_viewers_unit(db, org, viewers, name):
    uid, _eff, _field, visible = VIEWERS[name]
    async with client_for(db, uid) as c:
        body = await learners(c, org)
        assert locals_of(body["items"]) == visible and body["total"] == len(visible)
        people, text = await csv_people(c, org)
        assert people <= visible  # the chase list only has the not-yet-attested subset of the unit
    for stranger in EVERYONE - visible:
        assert f"{stranger}@" not in text, f"{name} received {stranger}"


async def test_a_regional_qaid_cannot_read_another_regions_learners_or_csv(db, org, viewers):
    async with client_for(db, 50) as c:  # Northeast
        # asking for the other region (or its people) can only narrow the view, it never widens it
        assert (await learners(c, org, region="Southwest"))["items"] == []
        assert (await learners(c, org, q="ghost"))["items"] == []
        assert (await learners(c, org, department="maal", region="Southwest"))["total"] == 0
        people, text = await csv_people(c, org, region="Southwest")
        assert people == set() and "ghost" not in text
        people, text = await csv_people(c, org)
        assert "ghost" not in text and "ex@" not in text and "head.tabligh" not in text
    async with client_for(db, 56) as c:  # Southwest sees exactly the Southwest rows
        assert locals_of((await learners(c, org))["items"]) == SOUTHWEST
        assert (await learners(c, org, region="Northeast"))["items"] == []


async def test_a_majlis_qaid_cannot_widen_to_the_region_or_other_majlis(db, org, viewers):
    async with client_for(db, 52) as c:
        assert (await learners(c, org, majlis="Boston"))["items"] == []
        assert locals_of((await learners(c, org, region="Northeast"))["items"]) == ALBANY
        assert locals_of((await learners(c, org, q="l"))["items"]) <= ALBANY


async def test_a_mohtamim_sees_their_department_only_and_other_department_courses_404(db, org, viewers):
    async with client_for(db, 54) as c:
        assert locals_of((await learners(c, org, "course_tabligh"))["items"]) == TABLIGH_PEOPLE
        assert locals_of((await learners(c, org))["items"]) == TABLIGH_PEOPLE  # the general course, still only their rows
        maal = await c.get(f"{BASE}/courses/course_maal/learners", params=q(org))
        missing = await c.get(f"{BASE}/courses/course_nope/learners", params=q(org))
        assert maal.status_code == missing.status_code == 404 and maal.json() == missing.json()
        assert (await c.get(f"{BASE}/courses/course_maal/learners.csv", params=q(org))).status_code == 404
        assert (await c.get(f"{BASE}/courses/course_maal/summary", params=q(org))).status_code == 404
        assert (await c.get(f"{BASE}/courses/course_maal/trend", params=q(org))).status_code == 404
        assert (await learners(c, org, department="maal"))["items"] == []


# ---------------------------------------------------------------------------------------------------------
# overview / summary / trend are computed from the filtered roster
# ---------------------------------------------------------------------------------------------------------

async def test_overview_summary_and_trend_count_only_the_unit(db, org, viewers):
    async with client_for(db, 1) as c:
        whole = (await c.get(f"{BASE}/overview", params=q(org))).json()
        whole_sum = (await c.get(f"{BASE}/courses/course_general/summary", params=q(org))).json()
    async with client_for(db, 52) as c:  # Majlis Qaid Albany: 3 people
        ov = await c.get(f"{BASE}/overview", params=q(org))
        assert ov.status_code == 200
        ov = ov.json()
        assert ov["totals"]["expected"] == 3 < whole["totals"]["expected"]
        regions = {cell["region"] for cell in ov["cells"]}
        assert regions <= {"Northeast", None}
        summ = (await c.get(f"{BASE}/courses/course_general/summary", params=q(org))).json()
        assert summ["totals"]["expected"] == 3 < whole_sum["totals"]["expected"]
        assert {b["name"] if "name" in b else b.get("majlis") for b in summ["by_majlis"]} <= {"Albany"}
        assert (await c.get(f"{BASE}/courses/course_general/trend", params=q(org))).json()["expected"] == 3
    async with client_for(db, 54) as c:  # Mohtamim Tabligh: 5 people, only their department course in the overview
        ov = (await c.get(f"{BASE}/overview", params=q(org))).json()
        assert ov["totals"]["expected"] == 5
        assert {d["department"] for d in ov["departments"]} == {"tabligh"}
        assert (await c.get(f"{BASE}/courses/course_tabligh/summary", params=q(org))).json()["totals"]["expected"] == 5
    async with client_for(db, 50) as c:  # regional Qaid Northeast: 6 people, no Southwest cell
        ov = (await c.get(f"{BASE}/overview", params=q(org))).json()
        assert ov["totals"]["expected"] == 6
        assert {cell["region"] for cell in ov["cells"]} <= {"Northeast"}


async def test_self_check_verdicts_do_not_depend_on_the_viewer(db, org, viewers):
    """The 'who should you name' index is built from the whole roster, so a Majlis Qaid sees the same mismatches for
    their own people as an admin does (the regional Qaid row is NOT in their filtered roster)."""
    async with client_for(db, 1) as c:
        admin = {i["email"]: i for i in (await learners(c, org, "course_tabligh"))["items"]}
    async with client_for(db, 52) as c:
        mine = {i["email"]: i for i in (await learners(c, org, "course_tabligh"))["items"]}
    assert set(mine) == {"l1@example.invalid", "crossorg@example.invalid"}
    for email, item in mine.items():
        assert item == admin[email]


async def test_the_database_is_not_changed_by_reads(db, org, viewers):
    before = len((await db.execute(select(MkaComplianceExpected))).scalars().all())
    async with client_for(db, 52) as c:
        await learners(c, org)
    assert len((await db.execute(select(MkaComplianceExpected))).scalars().all()) == before


# ---------------------------------------------------------------------------------------------------------
# Remind is limited to the filtered set
# ---------------------------------------------------------------------------------------------------------

async def test_remind_preview_counts_only_the_viewers_unit(db, org, viewers, transport, on):
    # general course, outstanding (not attested) per unit: admin 9 people minus attested l1 / ex; Albany = l3 + crossorg
    async with client_for(db, 1) as c:
        everyone = (await c.post(GENERAL, params=q(org))).json()
    async with client_for(db, 52) as c:
        albany = (await c.post(GENERAL, params=q(org))).json()
    async with client_for(db, 50) as c:
        northeast = (await c.post(GENERAL, params=q(org))).json()
    assert albany["would_send"] == 2  # l3 + crossorg (l1 attested)
    assert albany["would_send"] < northeast["would_send"] < everyone["would_send"]
    assert albany["candidates"] == 2 and everyone["candidates"] > northeast["candidates"]
    assert transport.calls == [] and await count(db, MkaAutomationSendLog) == 0


async def test_a_real_remind_reaches_only_the_viewers_unit(db, org, viewers, transport, on):
    async with client_for(db, 52) as c:  # Majlis Qaid Albany
        r = await real(c, GENERAL, org)
    assert r.status_code == 200, r.text
    assert r.json()["sent"] == 2
    logs = (await db.execute(select(MkaAutomationSendLog))).scalars().all()
    assert {row.intended_email for row in logs} == {"l3@example.invalid", "crossorg@example.invalid"}
    assert len(transport.calls) == 2


async def test_a_mohtamim_remind_is_limited_to_their_department(db, org, viewers, transport, on):
    async with client_for(db, 54) as c:
        assert (await c.post(f"{BASE}/courses/course_maal/remind", params=q(org))).status_code == 404
        r = await real(c, TABLIGH, org)
    assert r.status_code == 200, r.text
    logs = (await db.execute(select(MkaAutomationSendLog))).scalars().all()
    assert {row.intended_email.split("@")[0] for row in logs} <= TABLIGH_PEOPLE and logs


async def test_remind_cannot_be_widened_by_a_different_region_or_course(db, org, viewers, transport, on):
    async with client_for(db, 56) as c:  # Southwest: ghost1 + ghost2, nothing from Northeast
        r = await real(c, GENERAL, org)
    assert r.status_code == 200, r.text
    logs = (await db.execute(select(MkaAutomationSendLog))).scalars().all()
    assert {row.intended_email.split("@")[0] for row in logs} == SOUTHWEST
