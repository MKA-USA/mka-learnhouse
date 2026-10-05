"""Regression tests for the final integration review (M1, M2, contact-check Motamid, L3 redundant checks)."""

from datetime import datetime

import pytest
from sqlmodel import select

from src.db.mka_compliance import MkaComplianceCycleCourse, MkaComplianceExpected
from src.db.mka_user_attributes import MkaUserAttributes
from src.db.users import User
from src.services.mka import attributes as attrs
from src.services.mka import compliance as svc
from src.tests.routers.mka_compliance_world import add_attributes, add_user, expected
from src.tests.routers.test_mka_compliance_review import token_with
from src.tests.routers.test_mka_compliance_router import (  # noqa: F401  (fixtures + helpers)
    BASE, _app, client_for, freeze_today, q, world,
)
from src.tests.routers.test_mka_compliance_review import REAL_TODAY
from src.tests.conftest import other_org  # noqa: F401

ATTR = "/api/v1/mka/attributes"
NATIONAL = {"level": "national", "department": "aitmad", "role": "motamid"}


# ---- M1: a roster row alone never grants scope `all` -------------------------------------------------------

@pytest.mark.asyncio
async def test_m1_token_written_roster_row_cannot_grant_all_to_an_unproven_account(db, org, world):
    await add_user(db, org.id, 60, "attacker.person@gmail.com", 4, signup="google")
    u = await db.get(User, 60)
    await attrs.refresh_attributes(db, u)           # a normal not_applicable row, no Workspace proof
    await db.commit()
    async with client_for(db, 60) as c:
        assert (await c.get(f"{BASE}/scope", params=q(org))).json()["scope"] == "none"
    async with await token_with(db, org, {"organizations": {"action_update": True}}, "apitoken_m1") as t:
        r = await t.put(f"{ATTR}/roster/attacker.person@gmail.com", params={"org_slug": org.slug},
                        json={"attributes": NATIONAL, "note": "x"})
        assert r.status_code == 200, r.text
    async with client_for(db, 60) as c:
        assert (await c.get(f"{BASE}/scope", params=q(org))).json()["scope"] == "none"
        assert (await c.get(f"{BASE}/overview", params=q(org))).status_code == 403


@pytest.mark.asyncio
async def test_m1_proven_workspace_national_officer_still_gets_all(db, org, world):
    await add_user(db, org.id, 61, "national.officer@ws.example.invalid", 4, signup="google")
    await add_attributes(db, 61, "national.officer@ws.example.invalid", level="national", department="aitmad", role="motamid")
    async with client_for(db, 61) as c:
        assert (await c.get(f"{BASE}/scope", params=q(org))).json()["scope"] == "all"


# ---- M2: a rules-version bump must not invalidate identity proof or hide progress ------------------------------

@pytest.mark.asyncio
async def test_m2_rules_version_bump_keeps_matched_learners_and_their_attestations(db, org, world):
    async def snapshot():
        async with client_for(db, 1) as c:
            ov = (await c.get(f"{BASE}/overview", params=q(org))).json()["totals"]
            items = (await c.get(f"{BASE}/courses/course_general/learners", params=q(org, page_size=200))).json()["items"]
        return ov, {i["email"]: i["stage"] for i in items}

    before_totals, before_stages = await snapshot()
    assert before_totals["attested"] >= 1 and before_totals["not_signed_in"] < before_totals["expected"]
    rows = (await db.execute(select(MkaUserAttributes))).scalars().all()
    for row in rows:                                    # an older rules version on every stored row
        row.rules_version = "2025.0"
        db.add(row)
    await db.commit()
    after_totals, after_stages = await snapshot()
    assert after_totals == before_totals
    assert after_stages == before_stages
    u = await db.get(User, 31)
    assert attrs.is_address_proven(await attrs.get_row(db, 31), u)                 # proof is about the mailbox only
    assert attrs.read_effective_from_row(await attrs.get_row(db, 31), u)[1] is True  # attributes are still marked for refresh


# ---- contact check: Aitmad's national officer is titled "National Motamid" ------------------------------------

def test_contact_check_recognises_national_motamid_as_department_head():
    roster = [expected(1, 1, "head@example.invalid", "aitmad", "national", None, None, "National Motamid", "Head Person"),
              expected(1, 1, "mem@example.invalid", "aitmad", "local", "Albany", "Northeast", "Nazim Aitmad", "Mem Ber")]
    idx = svc.expected_contacts(roster)
    assert idx["dept_head"] == {"aitmad": ["Head Person"]}
    assert svc.classify_question("Name of the National Motamid") == "dept_head"
    check = svc.self_check_for(roster[1], {"majlis": "Albany", "regional_qaid": None, "dept_head": "Someone Else"}, idx)
    assert check["mismatches"] == ["dept_head"]                                 # a wrong head is now flagged for Aitmad
    ok = svc.self_check_for(roster[1], {"majlis": "Albany", "regional_qaid": None, "dept_head": "Head Person"}, idx)
    assert ok["mismatches"] == []


# ---- L3: tests for the redundant defence-in-depth checks --------------------------------------------------------

@pytest.mark.asyncio
async def test_l3_proven_python_recheck_rejects_proof_for_another_domain(db, org, world):
    """SQL only requires a non-null verified_hd; the Python re-check also binds it to the address's own domain."""
    row = await attrs.get_row(db, 31)
    row.verified_hd = "other.example.invalid"
    db.add(row)
    await db.commit()
    async with client_for(db, 1) as c:
        items = (await c.get(f"{BASE}/courses/course_general/learners", params=q(org, page_size=200))).json()["items"]
    assert {i["email"]: i["stage"] for i in items}["l1@example.invalid"] == "not_signed_in"


@pytest.mark.asyncio
async def test_l3_own_scope_requires_the_upstream_update_check(db, org, world, monkeypatch):
    from fastapi import HTTPException
    from src.services.mka import compliance_scope as scope_mod

    async def deny(*a, **k):
        raise HTTPException(status_code=403, detail="no")

    monkeypatch.setattr(scope_mod, "authorization_verify_based_on_roles_and_authorship", deny)
    async with client_for(db, 23) as c:  # ACTIVE creator of course_tabligh, but upstream denies `update`
        assert (await c.get(f"{BASE}/scope", params=q(org))).json()["scope"] == "none"


@pytest.mark.asyncio
async def test_l3_course_that_moved_org_is_not_served_from_the_old_org(db, org, other_org, world):
    from src.db.courses.courses import Course

    course = (await db.execute(select(Course).where(Course.course_uuid == "course_tabligh"))).scalars().first()
    course.org_id = other_org.id          # the link row still says org 1
    db.add(course)
    await db.commit()
    async with client_for(db, 1) as c:
        assert (await c.get(f"{BASE}/courses/course_tabligh/summary", params=q(org))).status_code == 404


def test_l3_default_cycle_timezone_is_new_york_and_deadline_day_ends_at_midnight_there(monkeypatch):
    import os
    from datetime import timezone

    if not os.environ.get("MKA_COMPLIANCE_TZ"):
        assert svc.CYCLE_TIMEZONE == "America/New_York"

    class FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):  # 23:30 ET on 2026-12-01 == 04:30 UTC on 2026-12-02
            return datetime(2026, 12, 2, 4, 30, tzinfo=timezone.utc).astimezone(tz)

    monkeypatch.setattr(svc, "datetime", FakeDT)
    assert REAL_TODAY() == "2026-12-01"
