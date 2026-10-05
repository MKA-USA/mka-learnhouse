"""Regression tests for the W4a review of /mka/compliance (H1, M1-M3 and the Lows)."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient
from sqlmodel import select

from src.db.api_tokens import APIToken
from src.db.mka_compliance import MkaComplianceCycle
from src.services.api_tokens.api_tokens import generate_api_token
from src.services.mka import compliance as svc
from src.tests.routers.mka_compliance_world import add_attributes, add_user, expected, progress
from src.tests.routers.test_mka_compliance_router import (  # noqa: F401  (fixtures + helpers)
    BASE, MID, _app, client_for, freeze_today, q, world, cycle_payload, row,
)

REAL_TODAY = svc.today  # the autouse fixture freezes svc.today; keep the real one for the tz test


async def token_with(db, org, rights, uuid):
    full, prefix, hashed = generate_api_token()
    db.add(APIToken(name=uuid, token_uuid=uuid, token_prefix=prefix, token_hash=hashed, org_id=org.id,
                    created_by_user_id=1, rights=rights, creation_date=str(datetime.now()), update_date=str(datetime.now())))
    await db.commit()
    return AsyncClient(transport=ASGITransport(app=_app(db)), base_url="http://t", headers={"Authorization": f"Bearer {full}"})


# ---- H1 ---------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("rights", [{}, {"courses": {"action_read": True}}, {"courses": {"action_read": False}, "assignments": {"action_read": True}}])
async def test_token_without_the_needed_rights_gets_403_everywhere(db, org, world, rights):  # noqa: F811  (pytest fixture imported from another test module)
    async with await token_with(db, org, rights, "apitoken_none") as c:
        p = {"org_slug": org.slug}
        cid = world.cycle.id
        for path in ("scope", "overview", "courses/course_general/summary", "courses/course_general/learners",
                     "courses/course_general/learners.csv", "courses/course_general/trend"):
            assert (await c.get(f"{BASE}/{path}", params=p)).status_code == 403, path
        assert (await c.post(f"{BASE}/cycles", params=p, json=cycle_payload())).status_code == 403
        assert (await c.post(f"{BASE}/expected/import", params=p, json={"cycle_id": cid, "rows": []})).status_code == 403
        assert (await c.delete(f"{BASE}/cycles/{cid}/expected", params=p)).status_code == 403


@pytest.mark.asyncio
async def test_read_only_token_cannot_import_or_delete_and_write_only_token_cannot_read(db, org, world):  # noqa: F811  (pytest fixture imported from another test module)
    p = {"org_slug": org.slug}
    cid = world.cycle.id
    async with await token_with(db, org, {"courses": {"action_read": True}, "assignments": {"action_read": True}}, "apitoken_ro") as c:
        assert (await c.get(f"{BASE}/overview", params=p)).status_code == 200
        assert (await c.post(f"{BASE}/cycles", params=p, json=cycle_payload())).status_code == 403
        assert (await c.post(f"{BASE}/expected/import", params=p, json={"cycle_id": cid, "rows": []})).status_code == 403
        assert (await c.delete(f"{BASE}/cycles/{cid}/expected", params=p)).status_code == 403
    async with await token_with(db, org, {"courses": {"action_update": True}}, "apitoken_wo") as c:
        assert (await c.get(f"{BASE}/overview", params=p)).status_code == 403
        assert (await c.post(f"{BASE}/expected/import", params=p, json={"cycle_id": cid, "rows": []})).status_code == 200


# ---- M1 ---------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_person_with_two_roles_counts_once(db, org, world):  # noqa: F811  (pytest fixture imported from another test module)
    db.add(expected(org.id, world.cycle.id, "l1@example.invalid", "tabligh", "local", "Albany", "Northeast", "Qaid", "L One"))
    db.add(expected(org.id, world.cycle.id, "l1@example.invalid", "", "local", "Albany", "Northeast", "Majlis Sadr", "L One"))
    await db.commit()
    async with client_for(db, 1) as c:
        ov = (await c.get(f"{BASE}/overview", params=q(org))).json()
        gen = (await c.get(f"{BASE}/courses/course_general/learners", params=q(org, page_size=200))).json()
        tab = (await c.get(f"{BASE}/courses/course_tabligh/learners", params=q(org, page_size=200))).json()
        summ = (await c.get(f"{BASE}/courses/course_general/summary", params=q(org))).json()
        csv = (await c.get(f"{BASE}/courses/course_tabligh/learners.csv", params=q(org, stage="completed"))).text
        trend = (await c.get(f"{BASE}/courses/course_general/trend", params=q(org))).json()
    assert ov["totals"]["expected"] == 10 and summ["totals"]["expected"] == 10 and trend["expected"] == 10
    assert ov["totals"]["attested"] == 2
    assert sum(1 for i in gen["items"] if i["email"] == "l1@example.invalid") == 1 and gen["total"] == 10
    mine = [i for i in tab["items"] if i["email"] == "l1@example.invalid"]
    assert len(mine) == 1 and mine[0]["role_titles"] == ["Nazim Tabligh", "Qaid"] and mine[0]["role_title"] == "Nazim Tabligh / Qaid"
    assert len({i["id"] for i in gen["items"]}) == 10  # unique stable keys
    d = {x["department"]: x for x in ov["departments"]}
    assert d["tabligh"]["expected"] == 5 and d["executive"]["expected"] == 3  # in two departments => counted in each
    assert csv.count("l2@example.invalid") == 1


# ---- M2 ---------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unproven_account_with_a_roster_email_is_not_credited(db, org, world):  # noqa: F811  (pytest fixture imported from another test module)
    await add_user(db, org.id, 60, "ghost1@example.invalid", 4, signup="email")  # no attributes row / no proof
    await progress(db, org.id, 60, 101, [1001, 1002, 1003], "2026-11-03")
    async with client_for(db, 1) as c:
        items = (await c.get(f"{BASE}/courses/course_general/learners", params=q(org, q="ghost1"))).json()["items"]
        assert items[0]["signed_in"] is False and items[0]["lessons_done"] == 0
    await add_attributes(db, 60, "ghost1@example.invalid", level="local")  # proof for that address
    async with client_for(db, 1) as c:
        items = (await c.get(f"{BASE}/courses/course_general/learners", params=q(org, q="ghost1"))).json()["items"]
    assert items[0]["signed_in"] is True and items[0]["lessons_done"] == 3


@pytest.mark.asyncio
async def test_proven_user_who_changes_email_to_a_role_address_is_not_matched(db, org, world):  # noqa: F811  (pytest fixture imported from another test module)
    """a@d proven; profile email changed to the role address (ghost1@) -> must NOT be that officeholder."""
    from src.db.users import User
    await add_user(db, org.id, 61, "a@example.invalid", 4)
    await add_attributes(db, 61, "a@example.invalid", level="local")
    await progress(db, org.id, 61, 101, [1001, 1002, 1003], "2026-11-03")
    u = await db.get(User, 61)
    u.email = "ghost1@example.invalid"      # same domain, unused role address
    db.add(u)
    await db.commit()
    async with client_for(db, 1) as c:
        item = (await c.get(f"{BASE}/courses/course_general/learners", params=q(org, q="ghost1"))).json()["items"][0]
        ov = (await c.get(f"{BASE}/overview", params=q(org))).json()
    assert item["signed_in"] is False and item["stage"] == "not_signed_in" and item["lessons_done"] == 0
    assert ov["totals"]["not_signed_in"] == 5  # unchanged: ghost1 is still never signed in


# ---- M3 ---------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_default_cycle_ignores_a_future_cycle_and_scope_honours_cycle_id(db, org, world):  # noqa: F811  (pytest fixture imported from another test module)
    db.add(MkaComplianceCycle(org_id=org.id, label="2027-28", starts_on=date(2027, 11, 1), deadline_on=date(2027, 12, 1)))
    db.add(MkaComplianceCycle(org_id=org.id, label="2025-26", starts_on=date(2025, 11, 1), deadline_on=date(2025, 12, 1)))
    await db.commit()
    future = (await db.execute(select(MkaComplianceCycle).where(MkaComplianceCycle.label == "2027-28"))).scalars().first()
    async with client_for(db, 1) as c:
        sc = (await c.get(f"{BASE}/scope", params=q(org))).json()
        assert sc["cycle"]["label"] == "2026-27" and len(sc["courses"]) == 3
        assert [x["label"] for x in sc["cycles"]] == ["2027-28", "2026-27", "2025-26"]
        other = (await c.get(f"{BASE}/scope", params=q(org, cycle_id=future.id))).json()
        assert other["cycle"]["label"] == "2027-28" and other["courses"] == []
        assert (await c.get(f"{BASE}/scope", params=q(org, cycle_id=world.cycle2.id))).status_code == 404


@pytest.mark.asyncio
async def test_default_cycle_after_the_window_is_the_latest_started(db, org, world, monkeypatch):  # noqa: F811  (pytest fixture imported from another test module)
    monkeypatch.setattr(svc, "today", lambda: "2027-03-01")
    db.add(MkaComplianceCycle(org_id=org.id, label="2027-28", starts_on=date(2027, 11, 1), deadline_on=date(2027, 12, 1)))
    await db.commit()
    async with client_for(db, 1) as c:
        assert (await c.get(f"{BASE}/scope", params=q(org))).json()["cycle"]["label"] == "2026-27"


# ---- Lows -------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_plain_learner_scope_discloses_no_cycles(db, org, world):  # noqa: F811  (pytest fixture imported from another test module)
    async with client_for(db, 2) as c:
        body = (await c.get(f"{BASE}/scope", params=q(org))).json()
    assert body == {"scope": "none", "cycle": None, "cycles": [], "courses": [], "departments": []}


def test_today_uses_the_cycle_timezone(monkeypatch):
    monkeypatch.setattr(svc, "CYCLE_TIMEZONE", "Pacific/Kiritimati")
    assert REAL_TODAY() == datetime.now(ZoneInfo("Pacific/Kiritimati")).date().isoformat()
    monkeypatch.setattr(svc, "CYCLE_TIMEZONE", "Not/AZone")
    assert len(REAL_TODAY()) == 10  # falls back, never raises
    assert svc.CYCLE_TIMEZONE != "UTC"


def test_contact_question_matching_is_precise():
    assert svc.classify_question("Name of your Majlis Qaid") is None
    assert svc.classify_question("Name of your Regional Qaid") == "regional_qaid"
    assert svc.classify_question("Name of the National Mohtamim Tabligh") == "dept_head"


@pytest.mark.asyncio
async def test_output_labels_nulls_and_truncation_header(db, org, world, monkeypatch):  # noqa: F811  (pytest fixture imported from another test module)
    async with client_for(db, 1) as c:
        ov = (await c.get(f"{BASE}/overview", params=q(org))).json()
        lr = (await c.get(f"{BASE}/courses/course_general/learners", params=q(org, department="executive", page_size=200))).json()
        monkeypatch.setattr(svc, "MAX_CSV_ROWS", 1)
        csv = await c.get(f"{BASE}/courses/course_general/learners.csv", params=q(org))
    ex = next(d for d in ov["departments"] if d["department"] == "executive")
    assert ex["department_name"] == "National leadership"
    assert next(d for d in ov["departments"] if d["department"] == "tabligh")["department_name"] == "Tabligh"
    assert all(c["region"] is None or c["region"] != "" for c in ov["cells"])
    assert {i["email"] for i in lr["items"]} == {"ex@example.invalid", "rq.ne@example.invalid"}
    assert all(i["majlis"] is None for i in lr["items"] if i["email"] == "ex@example.invalid")
    assert csv.headers["x-truncated"] == "true" and "TRUNCATED" not in csv.text.upper()
    assert csv.text.startswith("﻿")


@pytest.mark.asyncio
async def test_duplicate_course_for_a_slot_is_rejected(db, org, world):  # noqa: F811  (pytest fixture imported from another test module)
    from src.tests.routers.mka_compliance_world import add_course
    await add_course(db, org.id, 104, "course_general2", "Second general", 1, 0, base=3000)
    async with client_for(db, 1) as c:
        body = (await c.post(f"{BASE}/cycles", params=q(org), json={
            "cycle": "2026-27", "deadline": "2026-12-01",
            "courses": [{"kind": "general", "course_uuid": "course_general2"}]})).json()
    assert body["failed"] == 1 and "already has a general course" in body["courses"][0]["error"]
