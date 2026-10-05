"""MKA fork: seam C endpoints: the cron run (secret auth) and the manual "Remind" button (scope matrix, 24 h limit,
cross-org, token 403). The transport is mocked; every address is ``example.invalid``."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlmodel import select

from src.core.events.database import get_db_session
from src.db.api_tokens import APIToken
from src.db.mka_automation import MkaAutomationEvent, MkaAutomationSendLog
from src.db.organization_config import OrganizationConfig
from src.db.users import PublicUser
from src.security.api_token_utils import require_authenticated_user_or_api_token
from src.security.auth import get_authenticated_user, get_current_user
from src.services.api_tokens.api_tokens import generate_api_token
from src.services.mka import automation_reminders as rem
from src.services.mka import automation_send as send
from src.services.mka import compliance as svc
from src.tests.routers.mka_compliance_world import build_world

RUN = "/api/v1/mka/automation/reminders/run"
BASE = "/api/v1/mka/compliance"
SECRET = "s3cret-for-tests-only"
TESTER = "owner@example.invalid"
FLAGS = (
    "MKA_AUTOMATION_ENABLED", "MKA_REMINDERS_ENABLED", "MKA_AUTOMATION_TEST_RECIPIENT", "MKA_AUTOMATION_CRON_SECRET",
    "MKA_REMINDER_SCHEDULE", "MKA_REMINDER_EXCLUDED_DEPARTMENTS", "MKA_COMPLIANCE_TZ",
)
MON = datetime(2026, 11, 16, 15, 0, tzinfo=timezone.utc)  # a Monday; not a scheduled reminder day


class Transport:
    def __init__(self):
        self.calls = []

    def __call__(self, to, subject, body, headers=None, sender_name=None):
        self.calls.append({"to": to, "subject": subject, "body": body})


@pytest.fixture(autouse=True)
def env(monkeypatch):
    for name in FLAGS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MKA_AUTOMATION_SEND_DELAY_SECONDS", "0")
    monkeypatch.setenv("LEARNHOUSE_PLATFORM_URL", "https://ilm.example.invalid")
    monkeypatch.setattr(svc, "today", lambda: "2026-11-16")
    monkeypatch.setattr(rem, "current_instant", lambda: MON)


@pytest.fixture
def transport(monkeypatch):
    t = Transport()
    monkeypatch.setattr(send.email_utils, "send_email", t)
    return t


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv("MKA_AUTOMATION_ENABLED", "true")
    monkeypatch.setenv("MKA_REMINDERS_ENABLED", "true")
    monkeypatch.setenv("MKA_AUTOMATION_TEST_RECIPIENT", TESTER)


@pytest.fixture
async def world(db, org, other_org, admin_user, regular_user):
    for o in (org, other_org):
        db.add(OrganizationConfig(org_id=o.id, config={"config_version": "2.0"},
                                  creation_date=str(datetime.now()), update_date=str(datetime.now())))
    await db.commit()
    return await build_world(db, org, other_org, admin_user, regular_user)


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


def anon(db):
    return AsyncClient(transport=ASGITransport(app=_app(db)), base_url="http://t")


@pytest.fixture
async def token_client(db, org, world):
    full, prefix, hashed = generate_api_token()
    db.add(APIToken(name="prov", token_uuid="apitoken_r", token_prefix=prefix, token_hash=hashed, org_id=org.id,
                    created_by_user_id=1,
                    rights={r: {"action_read": True, "action_update": True} for r in
                            ("courses", "activities", "assignments", "coursechapters", "usergroups", "certifications")},
                    creation_date=str(datetime.now()), update_date=str(datetime.now())))
    await db.commit()
    async with AsyncClient(transport=ASGITransport(app=_app(db)), base_url="http://t",
                           headers={"Authorization": f"Bearer {full}"}) as c:
        yield c


def q(org, **extra):
    return {"org_id": org.id, **extra}


async def real(c, path, org, **extra):
    """What the dialog does: preview first, then send with the digest the preview returned. A preview that is itself
    refused (24 h limit, not current cycle, ...) is the answer, exactly as it is for the person at the keyboard."""
    shown = await c.post(path, params=q(org, **extra))
    if shown.status_code != 200:
        return shown
    return await c.post(path, params=q(org, dry_run="false", preview_digest=shown.json()["preview_digest"], **extra))


async def count(db, model):
    return len((await db.execute(select(model))).scalars().all())


# ---------------------------------------------------------------------------------------------------------
# cron endpoint: the secret
# ---------------------------------------------------------------------------------------------------------


async def test_unset_secret_never_opens_the_endpoint(db, world, transport):
    async with anon(db) as c:
        for headers in ({}, {"X-MKA-Cron-Secret": ""}, {"X-MKA-Cron-Secret": SECRET}):
            assert (await c.post(RUN, headers=headers)).status_code == 503
    assert transport.calls == [] and await count(db, MkaAutomationSendLog) == 0


async def test_wrong_or_missing_secret_is_401(db, world, transport, monkeypatch):
    monkeypatch.setenv("MKA_AUTOMATION_CRON_SECRET", SECRET)
    async with anon(db) as c:
        assert (await c.post(RUN)).status_code == 401
        assert (await c.post(RUN, headers={"X-MKA-Cron-Secret": "nope"})).status_code == 401
        assert (await c.post(RUN, headers={"X-MKA-Cron-Secret": SECRET + "x"})).status_code == 401
    assert transport.calls == []


async def test_an_admin_session_or_org_token_is_not_enough(db, world, token_client, monkeypatch):
    monkeypatch.setenv("MKA_AUTOMATION_CRON_SECRET", SECRET)
    async with client_for(db, 1) as c:
        assert (await c.post(RUN)).status_code == 401
    assert (await token_client.post(RUN)).status_code == 401


async def test_the_secret_runs_a_dry_run_by_default_and_leaks_nothing(db, world, transport, monkeypatch):
    monkeypatch.setenv("MKA_AUTOMATION_CRON_SECRET", SECRET)
    monkeypatch.setenv("MKA_REMINDER_SCHEDULE", "11-16")
    async with anon(db) as c:
        r = await c.post(RUN, headers={"X-MKA-Cron-Secret": SECRET})
    assert r.status_code == 200 and r.headers["cache-control"] == "private, no-store"
    body = r.json()
    assert body["dry_run"] is True and body["kind"] == "all"
    org1 = next(o for o in body["orgs"] if o["reminder"].get("ran"))
    assert org1["reminder"]["would_send"] > 0 and org1["reminder"]["sent"] == 0
    assert "example.invalid" not in r.text and SECRET not in r.text
    assert transport.calls == [] and await count(db, MkaAutomationSendLog) == 0


async def test_kind_is_validated(db, world, monkeypatch):
    monkeypatch.setenv("MKA_AUTOMATION_CRON_SECRET", SECRET)
    async with anon(db) as c:
        assert (await c.post(RUN, params={"kind": "weekly"}, headers={"X-MKA-Cron-Secret": SECRET})).status_code == 422


async def test_a_real_run_through_the_endpoint_redirects_to_the_test_address(db, world, transport, on, monkeypatch):
    monkeypatch.setenv("MKA_AUTOMATION_CRON_SECRET", SECRET)
    monkeypatch.setenv("MKA_REMINDER_SCHEDULE", "11-16")
    async with anon(db) as c:
        r = await c.post(RUN, params={"dry_run": "false", "kind": "reminder"}, headers={"X-MKA-Cron-Secret": SECRET})
    assert r.status_code == 200 and r.json()["test_mode"] is True
    assert transport.calls and {call["to"] for call in transport.calls} == {TESTER}


# ---------------------------------------------------------------------------------------------------------
# manual button: who may press it
# ---------------------------------------------------------------------------------------------------------

TABLIGH = f"{BASE}/courses/course_tabligh/remind"
GENERAL = f"{BASE}/courses/course_general/remind"


@pytest.mark.parametrize("name,uid", {"admin": 1, "maintainer": 20, "org_update_role": 21, "national_aitmad": 22}.items())
async def test_org_wide_viewers_get_a_preview(db, org, world, transport, name, uid):
    async with client_for(db, uid) as c:
        r = await c.post(TABLIGH, params=q(org))
    assert r.status_code == 200, name
    body = r.json()
    # tabligh roster: l1 attested; l2 completed, ghost1, crossorg, head.tabligh outstanding
    assert body["dry_run"] is True and body["would_send"] == 4 and body["skipped_attested"] == 1
    assert body["sent"] == 0 and body["skipped_recent"] == 0
    assert transport.calls == [] and await count(db, MkaAutomationSendLog) == 0
    assert await count(db, MkaAutomationEvent) == 0  # a preview takes no 24 h slot


async def test_a_course_author_may_remind_their_own_course_only(db, org, world, transport):
    async with client_for(db, 23) as c:  # CREATOR of the tabligh course only
        assert (await c.post(TABLIGH, params=q(org))).status_code == 200
        other = await c.post(GENERAL, params=q(org))
        missing = await c.post(f"{BASE}/courses/course_nope/remind", params=q(org))
    assert other.status_code == missing.status_code == 404 and other.json() == missing.json()
    async with client_for(db, 28) as c:  # CONTRIBUTOR of the general course only
        assert (await c.post(GENERAL, params=q(org))).status_code == 200
        assert (await c.post(TABLIGH, params=q(org))).status_code == 404


@pytest.mark.parametrize("uid", [2, 24, 25, 26, 27, 31])  # plain user, inactive author, local sadr, stale attrs, reporter, learner
async def test_learners_and_everyone_without_scope_are_refused(db, org, world, transport, on, uid):
    async with client_for(db, uid) as c:
        for dry in ("true", "false"):
            r = await c.post(TABLIGH, params=q(org, dry_run=dry))
            assert r.status_code in (403, 404)
    assert transport.calls == [] and await count(db, MkaAutomationSendLog) == 0 and await count(db, MkaAutomationEvent) == 0


async def test_api_tokens_are_403_even_with_full_rights(db, org, world, token_client, transport, on):
    r = await token_client.post(TABLIGH, params={"org_slug": org.slug, "dry_run": "false"})
    assert r.status_code == 403
    assert transport.calls == [] and await count(db, MkaAutomationEvent) == 0


async def test_cross_org_is_refused(db, org, other_org, world, transport, on):
    async with client_for(db, 40) as c:  # admin of org 2
        assert (await c.post(TABLIGH, params=q(org))).status_code == 403  # not a member of org 1
        assert (await c.post(TABLIGH, params=q(other_org))).status_code == 404  # org 1's course does not exist in org 2
    async with client_for(db, 1) as c:  # org 1 admin pointing at org 2
        assert (await c.post(f"{BASE}/courses/course_o2_general/remind", params=q(other_org))).status_code in (403, 404)
        assert (await c.post(f"{BASE}/courses/course_o2_general/remind", params=q(org))).status_code == 404
    assert transport.calls == []


async def test_unauthenticated_is_401(db, org, world):
    async with anon(db) as c:
        assert (await c.post(TABLIGH, params=q(org))).status_code == 401


# ---------------------------------------------------------------------------------------------------------
# manual button: sending, caps
# ---------------------------------------------------------------------------------------------------------


async def test_a_real_send_goes_only_to_the_test_address_and_counts(db, org, world, transport, on):
    async with client_for(db, 1) as c:
        r = await real(c, TABLIGH, org)
    assert r.status_code == 200
    body = r.json()
    assert body["sent"] == 4 and body["would_send"] == 0 and body["test_mode"] is True and body["failed"] == 0
    assert {call["to"] for call in transport.calls} == {TESTER} and len(transport.calls) == 4
    # only THIS course is listed, never the general one
    assert all("Tabligh 2026-27" in call["body"] and "General 2026-27" not in call["body"] for call in transport.calls)
    rows = (await db.execute(select(MkaAutomationEvent))).scalars().all()
    assert len(rows) == 1 and rows[0].event == "manual_remind" and rows[0].status == "processed" and rows[0].user_id == 1
    assert "example.invalid" not in (rows[0].note or "")


async def test_at_most_one_manual_remind_per_course_per_24h(db, org, world, transport, on, monkeypatch):
    async with client_for(db, 1) as c:
        assert (await real(c, TABLIGH, org)).status_code == 200
        again = await real(c, TABLIGH, org)
        preview = await c.post(TABLIGH, params=q(org, dry_run="true"))
        other_course = await real(c, GENERAL, org)  # another course is its own allowance
        assert again.status_code == 429 and preview.status_code == 429
        assert int(again.headers["retry-after"]) > 0
        assert other_course.status_code == 200
        monkeypatch.setattr(rem, "current_instant", lambda: MON + timedelta(hours=25))
        later = await real(c, TABLIGH, org)
    assert later.status_code == 200
    assert await count(db, MkaAutomationEvent) == 3
    assert later.json()["sent"] == 0 and later.json()["skipped_recent"] == 4  # same ISO week: the weekly cap holds


async def test_the_weekly_per_person_cap_is_honoured(db, org, world, transport, on, monkeypatch):
    """Manual reminders are their own allowance per person AND course (review M3): a second remind of the SAME
    course in the same week reaches nobody again, while another course is a separate email."""
    monkeypatch.delenv("MKA_AUTOMATION_TEST_RECIPIENT")  # real mode: the cap counts real reminders
    async with client_for(db, 1) as c:
        first = await real(c, GENERAL, org)
        assert first.json()["sent"] == 8
        monkeypatch.setattr(rem, "current_instant", lambda: MON + timedelta(hours=25))  # past the 24 h course limit
        preview = await c.post(GENERAL, params=q(org))  # a preview takes no slot
        again = await real(c, GENERAL, org)
        other_course = await real(c, TABLIGH, org)  # another course: its own email
    assert again.status_code == 200 and again.json()["sent"] == 0 and again.json()["skipped_recent"] == 8
    assert preview.json()["would_send"] == 0 and preview.json()["skipped_recent"] == 8
    assert other_course.json()["sent"] == 4 and other_course.json()["skipped_attested"] == 1
    assert len(transport.calls) == 8 + 4


async def test_a_disabled_feature_cannot_send_and_does_not_burn_the_24h_slot(db, org, world, transport, monkeypatch):
    monkeypatch.setenv("MKA_AUTOMATION_TEST_RECIPIENT", TESTER)  # flags stay off
    async with client_for(db, 1) as c:
        preview = await c.post(TABLIGH, params=q(org))
        blocked = await real(c, TABLIGH, org)
        monkeypatch.setenv("MKA_AUTOMATION_ENABLED", "true")
        monkeypatch.setenv("MKA_REMINDERS_ENABLED", "true")
        after = await real(c, TABLIGH, org)
    assert preview.status_code == 200 and preview.json()["enabled"] is False
    assert blocked.status_code == 409
    assert after.status_code == 200 and after.json()["sent"] == 4
    assert len(transport.calls) == 4


async def test_an_invalid_test_recipient_sends_nothing_and_keeps_the_slot(db, org, world, transport, on, monkeypatch):
    monkeypatch.setenv("MKA_AUTOMATION_TEST_RECIPIENT", "bad, address")
    async with client_for(db, 1) as c:
        r = await real(c, TABLIGH, org)
    assert r.status_code == 409 and transport.calls == []
    rows = (await db.execute(select(MkaAutomationEvent))).scalars().all()
    assert [e.status for e in rows] == ["ignored"]


async def test_excluded_departments_are_skipped_by_the_button_too(db, org, world, transport, on, monkeypatch):
    monkeypatch.setenv("MKA_REMINDER_EXCLUDED_DEPARTMENTS", "tabligh")
    async with client_for(db, 1) as c:
        r = await c.post(TABLIGH, params=q(org))
    assert r.json()["would_send"] == 0 and r.json()["skipped_excluded"] >= 1


async def test_a_concurrent_second_click_backs_out(db, org, world, transport, on):
    """The earlier claim row wins: a row inserted just before ours makes us return 429 and mark ours ignored."""
    db.add(MkaAutomationEvent(org_id=org.id, event="manual_remind", course_uuid="course_tabligh", user_id=1,
                              status="received", received_at=datetime(2026, 11, 16, 14, 59)))
    await db.commit()
    async with client_for(db, 1) as c:
        r = await real(c, TABLIGH, org)
    assert r.status_code == 429 and transport.calls == []
