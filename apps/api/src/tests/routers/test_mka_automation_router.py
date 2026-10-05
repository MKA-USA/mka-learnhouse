"""MKA fork: /mka/automation router skeleton: GET /status authentication, org scoping, no secrets."""

from datetime import datetime

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.core.events.database import get_db_session
from src.db.api_tokens import APIToken
from src.db.mka_automation import MkaAutomationEvent, MkaAutomationSendLog
from src.db.organization_config import OrganizationConfig
from src.db.users import PublicUser
from src.security.auth import get_authenticated_user, get_current_user
from src.services.api_tokens.api_tokens import generate_api_token

URL = "/api/v1/mka/automation/status"
FLAGS = ("MKA_AUTOMATION_ENABLED", "MKA_RECEIPTS_ENABLED", "MKA_REMINDERS_ENABLED", "MKA_AUTOENROLL_ENABLED",
         "MKA_AUTOMATION_TEST_RECIPIENT", "MKA_AUTOMATION_WEBHOOK_SECRET", "MKA_AUTOMATION_CRON_SECRET")
READ = {r: {"action_read": True} for r in ("courses", "assignments")}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in FLAGS:
        monkeypatch.delenv(name, raising=False)


def _app(db):
    from src.router import v1_router

    app = FastAPI()
    app.include_router(v1_router)
    app.dependency_overrides[get_db_session] = lambda: db
    return app


def session_client(db, uid):
    from src.db.users import User  # noqa: F401  (ensure mapper)

    app = _app(db)
    user = PublicUser(id=uid, username=f"u{uid}", first_name="F", last_name="L", email=f"u{uid}@x.invalid", user_uuid=f"user_{uid}")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_authenticated_user] = lambda: user
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


async def token_client(db, org, rights, n=1):
    db.add(OrganizationConfig(org_id=org.id, config={"config_version": "2.0"}, creation_date=str(datetime.now()), update_date=str(datetime.now())))
    full, prefix, hashed = generate_api_token()
    db.add(APIToken(name="t", token_uuid=f"apitoken_{org.id}_{n}", token_prefix=prefix, token_hash=hashed, org_id=org.id,
                    created_by_user_id=1, rights=rights, creation_date=str(datetime.now()), update_date=str(datetime.now())))
    await db.commit()
    return AsyncClient(transport=ASGITransport(app=_app(db)), base_url="http://t", headers={"Authorization": f"Bearer {full}"})


@pytest.fixture
async def seeded(db, org, other_org, admin_user, regular_user):
    db.add_all([
        MkaAutomationSendLog(org_id=org.id, kind="receipt", dedupe_key="a", to_email="a@example.invalid", intended_email="a@example.invalid", subject="s", status="sent"),
        MkaAutomationSendLog(org_id=org.id, kind="receipt", dedupe_key="b", to_email="o@example.invalid", intended_email="b@example.invalid", subject="s", status="sent", test_mode=True),
        MkaAutomationSendLog(org_id=org.id, kind="reminder", dedupe_key="c", to_email="a@example.invalid", intended_email="a@example.invalid", subject="s", status="failed"),
        MkaAutomationSendLog(org_id=other_org.id, kind="receipt", dedupe_key="a", to_email="z@example.invalid", intended_email="z@example.invalid", subject="s", status="sent"),
        MkaAutomationEvent(org_id=org.id, delivery_id="d1", event="assignment_submitted", status="processed"),
        MkaAutomationEvent(org_id=other_org.id, delivery_id="d1", event="assignment_submitted", status="error"),
    ])
    await db.commit()


# --- authentication ---------------------------------------------------------------------------------------


async def test_unauthenticated_is_401_not_a_leak(db, org, seeded):
    async with AsyncClient(transport=ASGITransport(app=_app(db)), base_url="http://t") as c:
        assert (await c.get(URL, params={"org_id": org.id})).status_code == 401


async def test_org_admin_session_gets_the_status(db, org, seeded):
    async with session_client(db, 1) as c:
        r = await c.get(URL, params={"org_id": org.id})
    assert r.status_code == 200 and r.headers["cache-control"] == "private, no-store"
    body = r.json()
    assert body["config"]["enabled"] is False and body["config"]["test_mode"] is False
    assert body["send_log"] == {"total": 3, "by_status": {"sent": 2, "failed": 1}, "test_mode_rows": 1, "stale_queued": 0, "failing_addresses": 0}
    assert body["events"] == {"total": 1, "by_status": {"processed": 1}}
    assert body["autoenroll"] == {"errors_recent": 0, "window_days": 7}


async def test_a_plain_member_is_403(db, org, seeded):
    async with session_client(db, 2) as c:
        assert (await c.get(URL, params={"org_id": org.id})).status_code == 403


async def test_a_non_member_and_an_admin_of_another_org_are_403(db, org, other_org, seeded):
    async with session_client(db, 99) as c:
        assert (await c.get(URL, params={"org_id": org.id})).status_code == 403
    async with session_client(db, 1) as c:  # admin of org 1 asking for org 2
        assert (await c.get(URL, params={"org_id": other_org.id})).status_code == 403


async def test_org_is_required(db, org, seeded):
    async with session_client(db, 1) as c:
        assert (await c.get(URL)).status_code == 422


async def test_counts_never_include_another_orgs_rows(db, org, other_org, seeded):
    async with session_client(db, 1) as c:
        body = (await c.get(URL, params={"org_slug": org.slug})).json()
    assert body["send_log"]["total"] == 3 and body["events"]["total"] == 1


async def test_read_only_token_may_read(db, org, seeded):
    async with await token_client(db, org, READ) as c:
        r = await c.get(URL, params={"org_slug": org.slug})
    assert r.status_code == 200 and r.json()["send_log"]["total"] == 3


async def test_token_without_read_rights_or_without_rights_is_403(db, org, seeded):
    async with await token_client(db, org, {"courses": {"action_read": True}}) as c:  # no assignments.action_read
        assert (await c.get(URL, params={"org_slug": org.slug})).status_code == 403
    async with await token_client(db, org, {}, n=2) as c:
        assert (await c.get(URL, params={"org_slug": org.slug})).status_code == 403


async def test_token_must_name_its_org_and_cannot_read_another(db, org, other_org, seeded):
    async with await token_client(db, org, READ) as c:
        assert (await c.get(URL)).status_code == 422
        r = await c.get(URL, params={"org_slug": other_org.slug})
        assert r.status_code in (403, 404)
        assert "z@example" not in r.text


# --- content ----------------------------------------------------------------------------------------------


async def test_status_reports_flags_and_masked_test_address_but_no_secrets(db, org, seeded, monkeypatch):
    monkeypatch.setenv("MKA_AUTOMATION_ENABLED", "true")
    monkeypatch.setenv("MKA_RECEIPTS_ENABLED", "true")
    monkeypatch.setenv("MKA_AUTOMATION_TEST_RECIPIENT", "owner.person@example.invalid")
    monkeypatch.setenv("MKA_AUTOMATION_WEBHOOK_SECRET", "hook-secret-value")
    monkeypatch.setenv("MKA_AUTOMATION_CRON_SECRET", "cron-secret-value")
    async with session_client(db, 1) as c:
        r = await c.get(URL, params={"org_id": org.id})
    cfg = r.json()["config"]
    assert cfg["enabled"] is True and cfg["features"] == {"autoenroll": False, "receipts": True, "reminders": False}
    assert cfg["test_mode"] is True and cfg["test_recipient_masked"] == "o***@example.invalid"
    assert cfg["webhook_secret_configured"] is True and cfg["cron_secret_configured"] is True
    for forbidden in ("hook-secret-value", "cron-secret-value", "owner.person", "a@example.invalid", "b@example.invalid"):
        assert forbidden not in r.text


async def test_status_never_lists_recipients_or_subjects(db, org, seeded):
    async with session_client(db, 1) as c:
        text = (await c.get(URL, params={"org_id": org.id})).text
    assert "example.invalid" not in text and '"subject"' not in text


# --- mounting ----------------------------------------------------------------------------------------------


def test_the_router_is_mounted_without_a_router_level_auth_dependency():
    """Hook guard. Each endpoint authenticates itself (webhook = HMAC, cron = secret). A router-level
    session/token dependency would make those endpoints unreachable for LearnHouse and the scheduler, and the
    upstream hook must stay the small `include_router` block logged in upstream-modifications.md."""
    import re
    from pathlib import Path

    import src.router as upstream_router

    source = Path(upstream_router.__file__).read_text(encoding="utf-8")
    assert "from src.routers import mka_automation as mka_automation_router_module  # MKA fork" in source
    block = re.search(r"v1_router\.include_router\([^\n]*\n\s+mka_automation_router_module\.router,.*?\n\)\n", source, re.S)
    assert block, "mka_automation include_router block not found"
    assert 'prefix="/mka/automation"' in block.group(0)
    assert "dependencies" not in block.group(0).split("#", 1)[1].split("\n", 1)[1]  # comment line excluded
