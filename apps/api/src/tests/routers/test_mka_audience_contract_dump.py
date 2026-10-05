"""MKA fork: API<->UI contract fixtures for the audience block.

Dumps the REAL JSON of the audience routes (synthetic ``example.invalid`` world) into
``apps/web/tests/fixtures/mka-audience/*.json`` as ``{path, status, body}``; the web test ``mka-audience-contract.test.mjs``
validates them against ``components/mka/audience/types.ts``.

Normal run: asserts the committed fixtures still match what the API returns (drift = the UI contract changed).
Regenerate: ``MKA_DUMP_CONTRACT=1 uv run --with greenlet pytest src/tests/routers/test_mka_audience_contract_dump.py``."""

import json
import os
from pathlib import Path

import pytest
from sqlmodel import delete

from src.db.mka_compliance import MkaComplianceCycle, MkaComplianceCycleCourse, MkaComplianceExpected
from src.tests.routers.test_mka_audience_router import (  # noqa: F401
    BASE,
    LOCAL_RULE,
    add_viewer,
    client_for,
    world,
)

FIXTURES = Path(__file__).resolve().parents[3].parent / "web" / "tests" / "fixtures" / "mka-audience"
DUMP = os.environ.get("MKA_DUMP_CONTRACT") == "1"


def _emit(name: str, resp, path: str) -> None:
    doc = {"path": path, "status": resp.status_code, "body": resp.json()}
    text = json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    target = FIXTURES / f"{name}.json"
    if DUMP:
        FIXTURES.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    else:
        assert target.exists(), f"missing contract fixture {name}.json (run with MKA_DUMP_CONTRACT=1)"
        assert target.read_text() == text, f"contract fixture {name}.json drifted from the API response"


@pytest.mark.asyncio
async def test_dump_happy_paths(db, world):  # noqa: F811  (pytest fixture imported from another test module)
    async with client_for(db, 50) as c:  # local Nazim Tabligh, Albany: matched viewer
        r = await c.get(f"{BASE}/me", params={"course_uuid": "course_tabligh"})
        assert r.status_code == 200
        _emit("me", r, "me?course_uuid=course_tabligh")
        r = await c.get(f"{BASE}/me/counterparts")
        assert r.status_code == 200
        _emit("counterparts", r, "me/counterparts")
    async with client_for(db, 23) as c:  # author of THIS course: can_view_all via the author branch
        r = await c.get(f"{BASE}/me", params={"course_uuid": "course_tabligh"})
        assert r.status_code == 200 and r.json()["can_view_all"] is True
        _emit("me_author", r, "me?course_uuid=course_tabligh")
    async with client_for(db, 2) as c:  # no attribute row: unknown
        r = await c.get(f"{BASE}/me")
        assert r.status_code == 200
        _emit("me_unrecognized", r, "me")
        r = await c.get(f"{BASE}/me/counterparts")
        assert r.status_code == 200
        _emit("counterparts_unrecognized", r, "me/counterparts")
    await add_viewer(db, 70, "murabbi@example.invalid", level="local", department="atfal", role="murabbi_atfal",
                     role_title="Murabbi Atfal", majlis="Syracuse-Binghamton", region="Northeast")
    async with client_for(db, 70) as c:
        r = await c.get(f"{BASE}/me/counterparts")
        assert r.status_code == 200 and len(r.json()["counterparts"]) == 3
        _emit("counterparts_atfal", r, "me/counterparts")
    async with client_for(db, 53) as c:  # regional Qaid: no department
        r = await c.get(f"{BASE}/me/counterparts")
        assert r.status_code == 200 and r.json()["reason"] == "no_department"
        _emit("counterparts_no_department", r, "me/counterparts")
    async with client_for(db, 1) as c:  # org admin
        r = await c.get(f"{BASE}/options", params={"org_id": 1})
        assert r.status_code == 200
        _emit("options", r, "options?org_id=1")
        r = await c.post(f"{BASE}/audience/count", json={"org_id": 1, "rule": LOCAL_RULE})
        assert r.status_code == 200 and r.json()["expected"] is not None
        _emit("count", r, "audience/count")


@pytest.mark.asyncio
async def test_dump_error_shapes(db, world):  # noqa: F811  (pytest fixture imported from another test module)
    async with client_for(db, 31) as c:  # learner
        r = await c.post(f"{BASE}/audience/count", json={"org_id": 1, "rule": LOCAL_RULE})
        assert r.status_code == 403
        _emit("err_403_count_learner", r, "audience/count")
    async with client_for(db, 1) as c:
        r = await c.post(f"{BASE}/audience/count", json={"org_id": 1, "rule": {"v": 1, "mode": "maybe", "groups": [{}]}})
        assert r.status_code == 422
        _emit("err_422_count_invalid_rule", r, "audience/count")
    async with client_for(db, 40) as c:  # admin of ANOTHER org
        r = await c.get(f"{BASE}/options", params={"org_id": 1})
        assert r.status_code == 403
        _emit("err_403_options_non_member", r, "options?org_id=1")


@pytest.mark.asyncio
async def test_dump_no_cycle(db, world, other_org):  # noqa: F811  (pytest fixture imported from another test module)
    for model in (MkaComplianceCycleCourse, MkaComplianceExpected, MkaComplianceCycle):
        await db.execute(delete(model).where(model.org_id == other_org.id))
    await db.commit()
    async with client_for(db, 40) as c:  # org-2 admin, org has no cycle yet
        r = await c.post(f"{BASE}/audience/count", json={"org_id": 2, "rule": LOCAL_RULE})
        assert r.status_code == 200 and r.json()["expected"] is None
        _emit("count_no_cycle", r, "audience/count")
