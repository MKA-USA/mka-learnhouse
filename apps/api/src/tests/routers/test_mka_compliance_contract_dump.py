"""MKA fork: API<->UI contract fixtures.

Dumps the REAL JSON of every /mka/compliance read endpoint (synthetic ``*.invalid`` world) into
``apps/web/tests/fixtures/mka-compliance/*.json``; the web test ``mka-compliance-contract.test.mjs`` validates them against
``services/mka/compliance.types.ts`` and feeds them to the UI helpers.

Normal run: asserts the committed fixtures still match what the API returns (drift = the UI contract changed).
Regenerate: ``MKA_DUMP_CONTRACT=1 uv run --with greenlet pytest src/tests/routers/test_mka_compliance_contract_dump.py``."""

import json
import os
from pathlib import Path

import pytest
from sqlmodel import delete

from src.db.mka_compliance import MkaComplianceCycle, MkaComplianceCycleCourse, MkaComplianceExpected
from src.tests.routers.test_mka_compliance_router import BASE, client_for, freeze_today, q, world  # noqa: F401

FIXTURES = Path(__file__).resolve().parents[3].parent / "web" / "tests" / "fixtures" / "mka-compliance"
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


async def _get(c, org, name, path, **extra):
    resp = await c.get(f"{BASE}/{path}", params=q(org, **extra))
    _emit(name, resp, path)
    return resp


@pytest.mark.asyncio
async def test_dump_happy_paths(db, org, world):  # noqa: F811  (pytest fixture imported from another test module)
    async with client_for(db, 1) as c:  # org admin: scope all
        assert (await _get(c, org, "scope_all", "scope")).status_code == 200
        assert (await _get(c, org, "overview", "overview")).status_code == 200
        assert (await _get(c, org, "course_summary_tabligh", "courses/course_tabligh/summary")).status_code == 200
        assert (await _get(c, org, "course_summary_general", "courses/course_general/summary")).status_code == 200
        assert (await _get(c, org, "learners_tabligh", "courses/course_tabligh/learners", page_size=200)).status_code == 200
        assert (await _get(c, org, "learners_general_page2", "courses/course_general/learners", page=2, page_size=4)).status_code == 200
        assert (await _get(c, org, "learners_general_filtered", "courses/course_general/learners",
                           status="not_signed_in", level="local", q="ghost")).status_code == 200
        assert (await _get(c, org, "trend_general", "courses/course_general/trend")).status_code == 200
    async with client_for(db, 23) as c:  # active author of the tabligh course: scope own
        assert (await _get(c, org, "scope_own", "scope")).status_code == 200
        assert (await _get(c, org, "learners_tabligh_as_author", "courses/course_tabligh/learners")).status_code == 200
    async with client_for(db, 2) as c:  # plain learner: scope none (200, empty)
        assert (await _get(c, org, "scope_none", "scope")).status_code == 200
    # a Majlis Qaid (seam C): legacy scope 'own', kind 'filtered', the unit in `filter`; the overview works and is limited
    from src.tests.routers.mka_compliance_world import add_attributes, add_user

    await add_user(db, org.id, 52, "majlis.qaid@example.invalid", 4)
    await add_attributes(db, 52, "majlis.qaid@example.invalid", level="local", role="qaid", majlis="Albany", region="Northeast")
    async with client_for(db, 52) as c:
        assert (await _get(c, org, "scope_filtered", "scope")).status_code == 200
        assert (await _get(c, org, "overview_filtered", "overview")).status_code == 200
        assert (await _get(c, org, "learners_general_filtered_scope", "courses/course_general/learners", page_size=200)).status_code == 200


@pytest.mark.asyncio
async def test_dump_error_shapes(db, org, world):  # noqa: F811  (pytest fixture imported from another test module)
    async with client_for(db, 23) as c:
        assert (await _get(c, org, "err_403_overview_as_author", "overview")).status_code == 403
        assert (await _get(c, org, "err_404_out_of_scope_course", "courses/course_maal/summary")).status_code == 404
    async with client_for(db, 2) as c:
        assert (await _get(c, org, "err_403_learners_as_plain_user", "courses/course_tabligh/learners")).status_code in (403, 404)
    async with client_for(db, 1) as c:
        resp = await c.get(f"{BASE}/scope")  # org missing
        _emit("err_422_org_required", resp, "scope")
        assert resp.status_code == 422
    async with client_for(db, 40) as c:  # admin of ANOTHER org
        assert (await _get(c, org, "err_403_non_member", "scope")).status_code == 403


@pytest.mark.asyncio
async def test_dump_no_cycle(db, org, other_org, world):  # noqa: F811  (pytest fixture imported from another test module)
    for model in (MkaComplianceCycleCourse, MkaComplianceExpected, MkaComplianceCycle):
        await db.execute(delete(model).where(model.org_id == other_org.id))
    await db.commit()
    async with client_for(db, 40) as c:  # org-2 admin, org has no cycle yet
        assert (await _get(c, other_org, "nocycle_scope", "scope")).status_code == 200
        assert (await _get(c, other_org, "nocycle_overview", "overview")).status_code == 200
        await _get(c, other_org, "nocycle_summary", "courses/course_o2_general/summary")
        await _get(c, other_org, "nocycle_learners", "courses/course_o2_general/learners")
