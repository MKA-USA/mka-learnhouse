"""MKA fork: API<->UI contract fixtures for the manual "Remind" endpoint (seam C).

Same mechanism as ``test_mka_compliance_contract_dump.py`` but only for the remind responses, which the web test
``mka-compliance-remind.test.mjs`` validates against ``services/mka/compliance.types.ts`` (``RemindResponse``) and feeds to
the dialog. Regenerate: ``MKA_DUMP_CONTRACT=1 uv run --with greenlet pytest src/tests/routers/test_mka_remind_contract_dump.py``."""

import json
import os
from datetime import date
from pathlib import Path

import pytest

from src.db.mka_compliance import MkaComplianceCycle, MkaComplianceCycleCourse

from src.tests.routers.test_mka_automation_reminders_router import (  # noqa: F401
    GENERAL, TABLIGH, client_for, env, on, q, real, transport, world,
)

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


@pytest.mark.asyncio
async def test_dump_remind_responses(db, org, world, transport, on):  # noqa: F811  (fixtures imported from another module)
    async with client_for(db, 1) as c:  # org admin
        _emit("remind_preview_tabligh", await c.post(TABLIGH, params=q(org)), "courses/course_tabligh/remind?dry_run=true")
        _emit("remind_sent_tabligh", await real(c, TABLIGH, org), "courses/course_tabligh/remind?dry_run=false")
        _emit("err_429_remind_again", await c.post(TABLIGH, params=q(org)), "courses/course_tabligh/remind")
        _emit(  # a real send whose list no longer matches the preview (review M4)
            "err_409_remind_preview_changed",
            await c.post(GENERAL, params=q(org, dry_run="false", preview_digest="0" * 40)),
            "courses/course_general/remind?dry_run=false&preview_digest=<stale>",
        )
        past = MkaComplianceCycle(org_id=org.id, label="2025-26", starts_on=date(2025, 11, 1), deadline_on=date(2025, 12, 1))
        db.add(past)
        await db.commit()
        db.add(MkaComplianceCycleCourse(org_id=org.id, cycle_id=past.id, course_id=102, course_uuid="course_tabligh",
                                        kind="department", department="tabligh", signoff_assignment_id=5002))
        await db.commit()
        _emit(  # last year's cycle (review H1)
            "err_409_remind_not_current_cycle",
            await c.post(TABLIGH, params=q(org, cycle_id=past.id)),
            "courses/course_tabligh/remind?cycle_id=<past>",
        )
    async with client_for(db, 23) as c:  # author of the tabligh course only
        _emit("err_404_remind_other_course", await c.post(GENERAL, params=q(org)), "courses/course_general/remind")
    async with client_for(db, 2) as c:  # plain learner
        _emit("err_403_remind_as_learner", await c.post(TABLIGH, params=q(org)), "courses/course_tabligh/remind")
