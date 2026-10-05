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
    assert check["mismatch"] is True                                  # a wrong head is now flagged for Aitmad
    ok = svc.self_check_for(roster[1], {"majlis": "Albany", "regional_qaid": None, "dept_head": "Head Person"}, idx)
    assert ok["mismatch"] is False
