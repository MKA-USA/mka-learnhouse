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
