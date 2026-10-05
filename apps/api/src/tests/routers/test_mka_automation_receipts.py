"""MKA fork: seam B, the LearnHouse webhook receiver and the receipts sweep (spec 2026-10-05 section 2B).

The transport is ALWAYS mocked; every address is ``example.invalid``; no test uses a session cookie (the endpoints
authenticate by signature / cron secret only)."""

import json
import logging
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlmodel import select

from src.core.events.database import get_db_session
from src.db.courses.assignments import AssignmentUserSubmissionStatus
from src.db.mka_automation import MkaAutomationEvent, MkaAutomationSendLog
from src.db.mka_compliance import MkaComplianceCycle, MkaComplianceCycleCourse
from src.db.user_organizations import UserOrganization
from src.services.email import utils as email_utils
from src.services.mka import automation_send as send
from src.services.mka.automation_auth import compute_signature
from src.tests.routers.mka_compliance_world import (
    add_assignment,
    add_attributes,
    add_course,
    add_user,
    attest,
    expected,
)

WEBHOOK = "/api/v1/mka/automation/webhooks/learnhouse"
SWEEP = "/api/v1/mka/automation/receipts/sweep"
SECRET = "local-hook-secret"
CRON = "local-cron-secret"
TESTER = "owner@example.invalid"
ENV = ("MKA_AUTOMATION_ENABLED", "MKA_RECEIPTS_ENABLED", "MKA_REMINDERS_ENABLED", "MKA_AUTOMATION_TEST_RECIPIENT",
       "MKA_AUTOMATION_WEBHOOK_SECRET", "MKA_AUTOMATION_CRON_SECRET", "MKA_AUTOMATION_RUN_SEND_CAP",
       "MKA_AUTOMATION_SEND_DELAY_SECONDS", "MKA_AUTOMATION_CONTACT_EMAIL", "MKA_COMPLIANCE_TZ")
TODAY = datetime.now(timezone.utc).date().isoformat()

L1 = "l1@example.invalid"      # user 31: tabligh local  -> general + tabligh sign-offs required
EX = "ex@example.invalid"      # user 32: executive      -> general only
UNPROVEN = "unproven@example.invalid"  # user 33: on the roster, identity not proven
STRANGER = "stranger@example.invalid"  # user 34: not on the roster
O2 = "o2.l1@example.invalid"   # user 41: member of org 2 only


class Transport:
    def __init__(self):
        self.calls = []

    def __call__(self, to, subject, body, headers=None, sender_name=None):
        self.calls.append({"to": to, "subject": subject, "body": body, "headers": headers})


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ENV:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def transport(monkeypatch):
    t = Transport()
    monkeypatch.setattr(send.email_utils, "send_email", t)

    async def base(slug, request=None, db_session=None, org_id=None):
        return f"https://{slug}.lms.example.invalid"

    monkeypatch.setattr(email_utils, "get_org_signup_base_url", base)
    return t


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv("MKA_AUTOMATION_ENABLED", "true")
    monkeypatch.setenv("MKA_RECEIPTS_ENABLED", "true")
    monkeypatch.setenv("MKA_AUTOMATION_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("MKA_AUTOMATION_CRON_SECRET", CRON)
    monkeypatch.setenv("MKA_AUTOMATION_SEND_DELAY_SECONDS", "0")


@pytest.fixture
async def world(db, org, other_org):
    """Org 1: cycle 2026-27 = general (sign-off asg 5001) + tabligh (sign-off 5002, contact-check 5003). Org 2: one
    general course (sign-off 6001) and one learner."""
    for uid, email in ((31, L1), (32, EX), (33, UNPROVEN), (34, STRANGER)):
        await add_user(db, org.id, uid, email)
    for uid, email in ((31, L1), (32, EX)):
        await add_attributes(db, uid, email)
    await add_user(db, other_org.id, 41, O2)
    await add_attributes(db, 41, O2)

    await add_course(db, org.id, 101, "course_general", "General 2026-27", 2, 0, base=1000)
    await add_assignment(db, org.id, 101, 1005, 5001)
    await add_course(db, org.id, 102, "course_tabligh", "Tabligh 2026-27", 2, 0, base=1010)
    await add_assignment(db, org.id, 102, 1015, 5002)
    await add_assignment(db, org.id, 102, 1016, 5003)
    await add_assignment(db, org.id, 101, 1006, 9001)  # NOT a cycle assignment
    await add_course(db, other_org.id, 201, "course_o2_general", "Other general", 2, 0, base=2000)
    await add_assignment(db, other_org.id, 201, 2005, 6001)

    c1 = MkaComplianceCycle(org_id=org.id, label="2026-27", starts_on=date(2026, 11, 1), deadline_on=date(2026, 12, 1))
    c2 = MkaComplianceCycle(org_id=other_org.id, label="2026-27", starts_on=date(2026, 11, 1), deadline_on=date(2026, 12, 1))
    db.add_all([c1, c2])
    await db.commit()
    for cid, uuid, kind, dept, so, cc in (
        (101, "course_general", "general", None, 5001, None),
        (102, "course_tabligh", "department", "tabligh", 5002, 5003),
    ):
        db.add(MkaComplianceCycleCourse(org_id=org.id, cycle_id=c1.id, course_id=cid, course_uuid=uuid, kind=kind,
                                        department=dept, signoff_assignment_id=so, contact_check_assignment_id=cc))
    db.add(MkaComplianceCycleCourse(org_id=other_org.id, cycle_id=c2.id, course_id=201, course_uuid="course_o2_general",
                                    kind="general", signoff_assignment_id=6001))
    db.add_all([
        expected(org.id, c1.id, L1, "tabligh", "local", "Albany", "Northeast", "Nazim Tabligh", "L One"),
        expected(org.id, c1.id, EX, "", "national", None, None, "Sadr", "Exec One"),
        expected(org.id, c1.id, UNPROVEN, "tabligh", "local", "Boston", "Northeast", "Nazim Tabligh", "Un Proven"),
        expected(other_org.id, c2.id, O2, "", "national", None, None, "Sadr", "O2"),
    ])
    await db.commit()
    return {"cycle": c1, "cycle2": c2}


def make_client(db):
    from src.router import v1_router

    app = FastAPI()
    app.include_router(v1_router)
    app.dependency_overrides[get_db_session] = lambda: db  # NOTE: no auth override at all: no session is ever sent
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


def payload(event="assignment_submitted", *, user_uuid="user_31", assignment="assignment_5001", course="course_general",
            delivery="dlv_0001", org_id=1, age=timedelta(0), email="attacker@example.invalid", name="Mallory"):
    stamp = (datetime.now(timezone.utc) - age).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "event": event, "delivery_id": delivery, "timestamp": stamp, "org_id": org_id,
        "data": {"user": {"user_uuid": user_uuid, "email": email, "username": name},
                 "assignment": {"assignment_uuid": assignment}, "course": {"course_uuid": course, "name": "x"},
                 "attempt_number": 1},
    }


def body_of(obj) -> bytes:
    return json.dumps(obj, separators=(",", ":")).encode()


async def post(c, obj, secret=SECRET, raw=None):
    raw = body_of(obj) if raw is None else raw
    return await c.post(WEBHOOK, content=raw, headers={"X-Webhook-Signature": compute_signature(raw, secret),
                                                       "Content-Type": "application/json"})


async def logs(db, **where):
    stmt = select(MkaAutomationSendLog)
    for k, v in where.items():
        stmt = stmt.where(getattr(MkaAutomationSendLog, k) == v)
    return list((await db.execute(stmt)).scalars().all())


async def events(db):
    return list((await db.execute(select(MkaAutomationEvent))).scalars().all())


# --- signature ---------------------------------------------------------------------------------------------


async def test_valid_signature_is_accepted_and_sends_one_receipt_to_the_account(db, world, transport, on):
    await attest(db, 31, 5001, TODAY)
    async with make_client(db) as c:
        r = await post(c, payload())
    assert r.status_code == 200 and r.json() == {"status": "processed"}
    assert [m["to"] for m in transport.calls] == [L1]
    assert "General 2026-27" in transport.calls[0]["body"] and "Tabligh 2026-27" in transport.calls[0]["body"]  # what remains
    rows = await logs(db, kind="receipt")
    assert [(x.dedupe_key, x.status, x.org_id) for x in rows] == [("receipt:assignment_5001:31", "sent", 1)]


async def test_missing_signature_is_401_with_no_detail(db, world, transport, on):
    async with make_client(db) as c:
        r = await c.post(WEBHOOK, content=body_of(payload()), headers={"Content-Type": "application/json"})
    assert r.status_code == 401 and r.content == b"" and transport.calls == []
    assert await events(db) == []


async def test_wrong_secret_is_401(db, world, transport, on):
    await attest(db, 31, 5001, TODAY)
    async with make_client(db) as c:
        r = await post(c, payload(), secret="not-the-secret")
    assert r.status_code == 401 and r.content == b"" and transport.calls == []


async def test_body_altered_after_signing_is_401(db, world, transport, on):
    await attest(db, 31, 5001, TODAY)
    signed = body_of(payload(user_uuid="user_31"))
    tampered = signed.replace(b"user_31", b"user_32")
    async with make_client(db) as c:
        r = await c.post(WEBHOOK, content=tampered, headers={"X-Webhook-Signature": compute_signature(signed, SECRET)})
    assert r.status_code == 401 and transport.calls == [] and await events(db) == []


async def test_a_reserialised_body_does_not_verify(db, world, transport, on):
    """The signature covers the exact raw bytes, not the parsed JSON (spaces change the bytes)."""
    await attest(db, 31, 5001, TODAY)
    compact = body_of(payload())
    spaced = json.dumps(json.loads(compact)).encode()
    assert compact != spaced
    async with make_client(db) as c:
        r = await c.post(WEBHOOK, content=spaced, headers={"X-Webhook-Signature": compute_signature(compact, SECRET)})
    assert r.status_code == 401


@pytest.mark.parametrize("secret_env", [None, "", "   "])
async def test_an_unconfigured_or_empty_secret_always_rejects(db, world, transport, monkeypatch, secret_env):
    monkeypatch.setenv("MKA_AUTOMATION_ENABLED", "true")
    monkeypatch.setenv("MKA_RECEIPTS_ENABLED", "true")
    if secret_env is not None:
        monkeypatch.setenv("MKA_AUTOMATION_WEBHOOK_SECRET", secret_env)
    await attest(db, 31, 5001, TODAY)
    raw = body_of(payload())
    async with make_client(db) as c:
        for secret in ("", "x", SECRET):  # even a signature made with the empty key
            r = await c.post(WEBHOOK, content=raw, headers={"X-Webhook-Signature": compute_signature(raw, secret)})
            assert r.status_code == 401
    assert transport.calls == []


@pytest.mark.parametrize("header", ["", "sha256=", "SHA256=" + "a" * 64, "abc", "sha256=" + "g" * 64])
async def test_malformed_signature_headers_are_401(db, world, transport, on, header):
    async with make_client(db) as c:
        r = await c.post(WEBHOOK, content=body_of(payload()), headers={"X-Webhook-Signature": header})
    assert r.status_code == 401


async def test_signature_is_checked_before_the_body_is_parsed(db, world, transport, on):
    """Garbage with a bad signature is 401 (never the 400 a parse failure would give)."""
    async with make_client(db) as c:
        r = await c.post(WEBHOOK, content=b"{not json", headers={"X-Webhook-Signature": "sha256=" + "0" * 64})
    assert r.status_code == 401
    raw = b"{not json"
    async with make_client(db) as c:  # correctly signed garbage: authenticated, then rejected as unusable
        r = await post(c, None, raw=raw)
    assert r.status_code == 400 and await events(db) == []


async def test_signed_non_object_json_is_400(db, world, transport, on):
    async with make_client(db) as c:
        r = await post(c, None, raw=b"[1,2,3]")
    assert r.status_code == 400


# --- replay / duplicates -----------------------------------------------------------------------------------


async def test_old_timestamp_is_rejected(db, world, transport, on):
    await attest(db, 31, 5001, TODAY)
    async with make_client(db) as c:
        r = await post(c, payload(age=timedelta(minutes=11)))
    assert r.status_code == 400 and transport.calls == [] and await events(db) == []


async def test_future_timestamp_beyond_skew_is_rejected_and_small_skew_is_fine(db, world, transport, on):
    await attest(db, 31, 5001, TODAY)
    async with make_client(db) as c:
        assert (await post(c, payload(age=timedelta(minutes=-5)))).status_code == 400
        assert (await post(c, payload(delivery="dlv_ok", age=timedelta(seconds=-20)))).status_code == 200
        assert (await post(c, payload(delivery="dlv_edge", age=timedelta(minutes=9)))).status_code == 200


async def test_missing_or_garbled_timestamp_or_delivery_id_is_400(db, world, transport, on):
    async with make_client(db) as c:
        for mutate in (lambda p: p.pop("timestamp"), lambda p: p.update(timestamp="yesterday"),
                       lambda p: p.pop("delivery_id"), lambda p: p.update(delivery_id="x" * 200),
                       lambda p: p.update(delivery_id="a b"), lambda p: p.pop("event")):
            p = payload()
            mutate(p)
            assert (await post(c, p)).status_code == 400
    assert transport.calls == []


async def test_duplicate_delivery_id_is_200_with_no_side_effects(db, world, transport, on):
    await attest(db, 31, 5001, TODAY)
    async with make_client(db) as c:
        first = await post(c, payload())
        second = await post(c, payload())
    assert first.json() == {"status": "processed"}
    assert second.status_code == 200 and second.json() == {"status": "duplicate"}
    assert len(transport.calls) == 1 and len(await events(db)) == 1


async def test_same_delivery_id_in_two_orgs_does_not_collide(db, world, transport, on):
    await attest(db, 31, 5001, TODAY)
    await attest(db, 41, 6001, TODAY)
    async with make_client(db) as c:
        a = await post(c, payload(delivery="dlv_same"))
        b = await post(c, payload(user_uuid="user_41", assignment="assignment_6001", course="course_o2_general",
                                  delivery="dlv_same", org_id=2))
    assert a.json()["status"] == b.json()["status"] == "processed"
    assert sorted(e.org_id for e in await events(db)) == [1, 2]


# --- flags -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("env", [{}, {"MKA_AUTOMATION_ENABLED": "true"}, {"MKA_RECEIPTS_ENABLED": "true"}])
async def test_flags_off_is_disabled_after_verifying_the_signature(db, world, transport, monkeypatch, env):
    monkeypatch.setenv("MKA_AUTOMATION_WEBHOOK_SECRET", SECRET)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    await attest(db, 31, 5001, TODAY)
    async with make_client(db) as c:
        ok = await post(c, payload())
        bad = await post(c, payload(), secret="wrong")
    assert ok.status_code == 200 and ok.json() == {"status": "disabled"}
    assert bad.status_code == 401  # signature still verified first
    assert transport.calls == [] and await events(db) == [] and await logs(db) == []


# --- which events / assignments count ----------------------------------------------------------------------


async def test_unknown_event_is_ignored_and_recorded(db, world, transport, on):
    async with make_client(db) as c:
        r = await post(c, payload("user_signed_up"))
    assert r.status_code == 200 and r.json() == {"status": "ignored"}
    (event,) = await events(db)
    assert (event.event, event.status, event.org_id) == ("user_signed_up", "ignored", 1) and transport.calls == []


async def test_unknown_event_for_a_nonexistent_org_records_nothing(db, world, transport, on):
    async with make_client(db) as c:
        r = await post(c, payload("user_signed_up", org_id=999))
    assert r.json() == {"status": "ignored"} and await events(db) == []


async def test_assignment_graded_is_ignored(db, world, transport, on):
    p = {"event": "assignment_graded", "delivery_id": "dlv_g", "timestamp": payload()["timestamp"], "org_id": 1,
         "data": {"user_id": 31, "assignment_uuid": "assignment_5001", "course_uuid": "course_general"}}
    async with make_client(db) as c:
        r = await post(c, p)
    assert r.json() == {"status": "ignored"} and transport.calls == []


async def test_non_cycle_assignment_is_ignored_with_a_recorded_event(db, world, transport, on):
    await attest(db, 31, 9001, TODAY)
    async with make_client(db) as c:
        r = await post(c, payload(assignment="assignment_9001"))
    assert r.json() == {"status": "ignored"} and transport.calls == []
    (event,) = await events(db)
    assert (event.status, event.note) == ("ignored", "not_cycle_assignment")


async def test_unknown_assignment_uuid_is_ignored(db, world, transport, on):
    async with make_client(db) as c:
        r = await post(c, payload(assignment="assignment_nope"))
    assert r.json() == {"status": "ignored"} and transport.calls == []
    (event,) = await events(db)
    assert event.status == "ignored" and event.note == "unknown_entity"


async def test_contact_check_submission_records_but_sends_no_receipt(db, world, transport, on):
    await attest(db, 31, 5003, TODAY)
    async with make_client(db) as c:
        r = await post(c, payload(assignment="assignment_5003", course="course_tabligh"))
    assert r.json() == {"status": "processed"} and transport.calls == [] and await logs(db) == []
    (event,) = await events(db)
    assert (event.status, event.note, event.user_id) == ("processed", "contact_check_no_receipt", 31)


# --- receipts + all-set ------------------------------------------------------------------------------------


async def test_second_delivery_of_the_same_signoff_produces_no_second_receipt(db, world, transport, on):
    await attest(db, 31, 5001, TODAY)
    async with make_client(db) as c:
        await post(c, payload(delivery="dlv_a"))
        await post(c, payload(delivery="dlv_b"))  # LearnHouse re-emits (retry resubmit): new delivery id, same sign-off
    assert len(transport.calls) == 1 and len(await logs(db, kind="receipt")) == 1


async def test_allset_is_sent_once_when_both_signoffs_exist(db, world, transport, on):
    await attest(db, 31, 5001, TODAY)
    async with make_client(db) as c:
        await post(c, payload(delivery="dlv_1"))
        assert [x.kind for x in await logs(db)] == ["receipt"]  # one of two: no all-set yet
        await attest(db, 31, 5002, TODAY)
        await post(c, payload(assignment="assignment_5002", course="course_tabligh", delivery="dlv_2"))
        await post(c, payload(assignment="assignment_5002", course="course_tabligh", delivery="dlv_3"))
        await post(c, payload(delivery="dlv_4"))
    kinds = sorted(x.dedupe_key for x in await logs(db))
    assert kinds == ["allset:1:31", "receipt:assignment_5001:31", "receipt:assignment_5002:31"]
    subjects = [m["subject"] for m in transport.calls]
    assert len(transport.calls) == 3 and sum("all set" in s for s in subjects) == 1


async def test_executive_with_only_the_general_course_is_all_set_after_one_signoff(db, world, transport, on):
    await attest(db, 32, 5001, TODAY)
    async with make_client(db) as c:
        await post(c, payload(user_uuid="user_32"))
    assert sorted(x.kind for x in await logs(db)) == ["allset", "receipt"]


async def test_receipt_states_the_cycle_timezone_time_and_course(db, world, transport, on, monkeypatch):
    monkeypatch.setenv("MKA_COMPLIANCE_TZ", "America/New_York")
    await attest(db, 31, 5001, "2026-11-06")  # stored 11:00 (naive UTC) -> 7:00 AM EST (UTC-5; DST ended Nov 1)
    async with make_client(db) as c:
        await post(c, payload())
    body = transport.calls[0]["body"]
    assert "General 2026-27" in body and "November 6, 2026 at 6:00 AM" in body


async def test_resubmitted_state_still_counts_when_graded_or_late(db, world, transport, on):
    await attest(db, 31, 5001, TODAY, AssignmentUserSubmissionStatus.GRADED)
    async with make_client(db) as c:
        await post(c, payload())
    assert len(transport.calls) == 1


# --- identity / trust --------------------------------------------------------------------------------------


async def test_user_is_resolved_by_uuid_never_by_payload_email(db, world, transport, on):
    await attest(db, 31, 5001, TODAY)
    async with make_client(db) as c:
        r = await post(c, payload(email=STRANGER, name="Mallory Spoof"))
    assert r.json() == {"status": "processed"}
    assert [m["to"] for m in transport.calls] == [L1]
    assert STRANGER not in transport.calls[0]["body"] and "Mallory" not in transport.calls[0]["body"]


async def test_payload_email_of_a_real_user_cannot_redirect_mail_for_an_unknown_uuid(db, world, transport, on):
    await attest(db, 31, 5001, TODAY)
    async with make_client(db) as c:
        r = await post(c, payload(user_uuid="user_does_not_exist", email=L1))
    assert r.json() == {"status": "ignored"} and transport.calls == []


async def test_user_not_on_the_roster_is_ignored(db, world, transport, on):
    await attest(db, 34, 5001, TODAY)
    async with make_client(db) as c:
        await post(c, payload(user_uuid="user_34"))
    assert transport.calls == [] and await logs(db) == []


async def test_roster_user_without_proof_of_the_address_gets_nothing(db, world, transport, on):
    await attest(db, 33, 5001, TODAY)  # user 33 has no attributes row: identity unproven
    async with make_client(db) as c:
        await post(c, payload(user_uuid="user_33"))
    assert transport.calls == [] and await logs(db) == []


async def test_a_proven_roster_person_who_is_not_an_org_member_gets_nothing_from_webhook_or_sweep(db, world, transport, on):
    """Review M5: the org-membership guard in ``build_context`` had no test (mutating it away left the suite green)."""
    await attest(db, 31, 5001, TODAY)  # user 31 is on the roster, identity proven, sign-off submitted ...
    await db.execute(delete(UserOrganization).where(UserOrganization.user_id == 31))  # ... but no longer a member
    await db.commit()
    async with make_client(db) as c:
        hook = await post(c, payload())
        sweep = await c.post(SWEEP, params={"dry_run": "false"}, headers=cron())
    assert hook.status_code == 200 and sweep.status_code == 200
    assert transport.calls == [] and await logs(db) == []
    assert sweep.json()["results"].get("sent", 0) == 0


async def test_signoff_not_actually_submitted_sends_nothing(db, world, transport, on):
    async with make_client(db) as c:  # no AssignmentUserSubmission row at all: a forged-but-signed delivery
        r = await post(c, payload())
    assert r.json() == {"status": "processed"} and transport.calls == [] and await logs(db) == []


async def test_a_pending_submission_is_not_a_signoff(db, world, transport, on):
    await attest(db, 31, 5001, TODAY, AssignmentUserSubmissionStatus.PENDING)
    async with make_client(db) as c:
        await post(c, payload())
    assert transport.calls == []


async def test_payload_org_that_differs_from_the_assignments_org_is_ignored(db, world, transport, on):
    await attest(db, 31, 5001, TODAY)
    async with make_client(db) as c:
        r = await post(c, payload(org_id=2))
    assert r.json() == {"status": "ignored"} and transport.calls == []
    (event,) = await events(db)
    assert (event.org_id, event.note) == (1, "org_mismatch")  # recorded under the DB org, never the payload's


async def test_user_of_another_org_cannot_trigger_a_receipt_for_this_orgs_assignment(db, world, transport, on):
    await attest(db, 41, 5001, TODAY)
    async with make_client(db) as c:
        await post(c, payload(user_uuid="user_41"))
    assert transport.calls == [] and await logs(db) == []


async def test_cross_org_isolation_receipts_stay_in_their_own_org(db, world, transport, on):
    await attest(db, 31, 5001, TODAY)
    await attest(db, 41, 6001, TODAY)
    async with make_client(db) as c:
        await post(c, payload(delivery="d1"))
        await post(c, payload(user_uuid="user_41", assignment="assignment_6001", course="course_o2_general",
                              delivery="d2", org_id=2))
    assert sorted(m["to"] for m in transport.calls) == sorted([L1, O2, O2])  # O2 is an executive: receipt + all-set
    assert {(x.org_id, x.intended_email) for x in await logs(db, kind="receipt")} == {(1, L1), (2, O2)}
    assert all(x.org_id == 2 for x in await logs(db, intended_email=O2))


# --- test mode ---------------------------------------------------------------------------------------------


async def test_test_mode_only_ever_mails_the_test_recipient(db, world, transport, on, monkeypatch):
    monkeypatch.setenv("MKA_AUTOMATION_TEST_RECIPIENT", TESTER)
    await attest(db, 31, 5001, TODAY)
    await attest(db, 31, 5002, TODAY)
    await attest(db, 32, 5001, TODAY)
    async with make_client(db) as c:
        await post(c, payload(delivery="d1"))
        await post(c, payload(assignment="assignment_5002", course="course_tabligh", delivery="d2"))
        await post(c, payload(user_uuid="user_32", delivery="d3", email="spoof@example.invalid"))
    assert transport.calls and {m["to"] for m in transport.calls} == {TESTER}
    assert all(m["subject"].startswith("[TEST") for m in transport.calls)
    assert all(not m["headers"] for m in transport.calls)  # no Reply-To / Cc that could reach anybody else
    rows = await logs(db)
    assert rows and all(x.test_mode and x.to_email == TESTER for x in rows)
    assert {x.intended_email for x in rows} == {L1, EX}  # intended recipients recorded


async def test_test_mode_rows_do_not_block_the_real_send_later(db, world, transport, on, monkeypatch):
    await attest(db, 31, 5001, TODAY)
    monkeypatch.setenv("MKA_AUTOMATION_TEST_RECIPIENT", TESTER)
    async with make_client(db) as c:
        await post(c, payload(delivery="d1"))
        monkeypatch.delenv("MKA_AUTOMATION_TEST_RECIPIENT")
        await post(c, payload(delivery="d2"))
    assert [m["to"] for m in transport.calls] == [TESTER, L1]


# --- hygiene -----------------------------------------------------------------------------------------------


async def test_events_and_logs_hold_no_pii_or_answers(db, world, transport, on, caplog):
    caplog.set_level(logging.DEBUG)
    await attest(db, 31, 5001, TODAY)
    async with make_client(db) as c:
        await post(c, payload(email="attacker@example.invalid", name="Mallory"))
    (event,) = await events(db)
    dump = " ".join(str(v) for v in event.model_dump().values())
    for forbidden in ("example.invalid", "Mallory", "L One", "answer"):
        assert forbidden not in dump
    for record in (r for r in caplog.records if r.name.startswith("src.")):  # the app's own loggers (not SQL echo)
        text = record.getMessage()
        assert "example.invalid" not in text and "Mallory" not in text and SECRET not in text


async def test_a_transport_failure_is_recorded_and_the_sweep_recovers_it(db, world, transport, on, monkeypatch):
    await attest(db, 31, 5001, TODAY)

    def boom(*a, **k):
        raise RuntimeError("provider down for l1@example.invalid")

    monkeypatch.setattr(send.email_utils, "send_email", boom)
    async with make_client(db) as c:
        r = await post(c, payload())
    assert r.status_code == 200
    (row,) = await logs(db, kind="receipt")
    assert row.status == "failed" and "example.invalid" not in (row.error or "")
    monkeypatch.setattr(send.email_utils, "send_email", transport)
    async with make_client(db) as c:
        sweep = await c.post(SWEEP, params={"dry_run": "false"}, headers={"X-MKA-Cron-Secret": CRON})
    assert sweep.status_code == 200 and [m["to"] for m in transport.calls] == [L1]
    (row,) = await logs(db, kind="receipt")
    assert row.status == "sent"


async def test_course_completed_recovers_a_dropped_signoff_webhook(db, world, transport, on):
    await attest(db, 31, 5001, TODAY)  # the sign-off webhook was dropped; the course_completed one arrives
    async with make_client(db) as c:
        r = await post(c, payload("course_completed", assignment="x", delivery="dlv_cc"))
    assert r.json() == {"status": "processed"} and [m["to"] for m in transport.calls] == [L1]
    async with make_client(db) as c:  # and then the real sign-off webhook shows up: no second mail
        await post(c, payload(delivery="dlv_late"))
    assert len(transport.calls) == 1


async def test_course_completed_for_a_non_cycle_course_is_ignored(db, world, transport, on):
    async with make_client(db) as c:
        r = await post(c, payload("course_completed", course="course_unknown", delivery="dlv_x"))
    assert r.json() == {"status": "ignored"} and transport.calls == []


# --- sweep -------------------------------------------------------------------------------------------------


def cron(secret=CRON):
    return {"X-MKA-Cron-Secret": secret}


async def test_sweep_requires_the_cron_secret(db, world, transport, on, monkeypatch):
    async with make_client(db) as c:
        assert (await c.post(SWEEP)).status_code == 401
        assert (await c.post(SWEEP, headers=cron("nope"))).status_code == 401
        monkeypatch.delenv("MKA_AUTOMATION_CRON_SECRET")
        assert (await c.post(SWEEP, headers=cron(CRON))).status_code == 503
    assert transport.calls == []


async def test_sweep_dry_run_is_the_default_and_touches_nothing(db, world, transport, on):
    await attest(db, 31, 5001, TODAY)
    await attest(db, 32, 5001, TODAY)
    async with make_client(db) as c:
        r = await c.post(SWEEP, headers=cron())
    body = r.json()
    assert r.status_code == 200 and body["dry_run"] is True and body["candidates"] == 2
    assert body["results"].get("dry_run", 0) >= 2
    assert transport.calls == [] and await logs(db) == []
    assert "example.invalid" not in r.text


async def test_sweep_real_run_sends_missing_receipts_with_the_same_keys_and_is_idempotent(db, world, transport, on):
    await attest(db, 31, 5001, TODAY)
    await attest(db, 32, 5001, TODAY)
    async with make_client(db) as c:
        first = await c.post(SWEEP, params={"dry_run": "false"}, headers=cron())
        second = await c.post(SWEEP, params={"dry_run": "false"}, headers=cron())
    assert first.json()["results"]["sent"] == 3  # 2 receipts + the executive's all-set
    assert second.json()["results"] == {"already_handled": 2}
    assert sorted(m["to"] for m in transport.calls) == sorted([L1, EX, EX])
    assert sorted(x.dedupe_key for x in await logs(db)) == ["allset:1:32", "receipt:assignment_5001:31", "receipt:assignment_5001:32"]


async def test_webhook_then_sweep_sends_nothing_more_and_sweep_then_webhook_too(db, world, transport, on):
    await attest(db, 31, 5001, TODAY)
    await attest(db, 32, 5001, TODAY)
    async with make_client(db) as c:
        await post(c, payload(delivery="d1"))
        await c.post(SWEEP, params={"dry_run": "false"}, headers=cron())
        n = len(transport.calls)
        await post(c, payload(user_uuid="user_32", delivery="d2"))  # sweep got there first for user 32
        await c.post(SWEEP, params={"dry_run": "false"}, headers=cron())
    assert n == 3 and len(transport.calls) == 3  # L1 receipt, EX receipt + all-set, nothing duplicated


async def test_sweep_window_excludes_old_submissions(db, world, transport, on):
    old = (datetime.now(timezone.utc) - timedelta(days=30)).date().isoformat()
    await attest(db, 31, 5001, old)
    await attest(db, 32, 5001, TODAY)
    async with make_client(db) as c:
        week = await c.post(SWEEP, params={"dry_run": "false", "days": 7}, headers=cron())
        assert [m["to"] for m in transport.calls if "all set" not in m["subject"]] == [EX]
        month = await c.post(SWEEP, params={"dry_run": "false", "days": 60}, headers=cron())
    assert week.json()["candidates"] == 1 and month.json()["candidates"] == 2
    assert L1 in [m["to"] for m in transport.calls]


async def test_sweep_respects_the_send_cap(db, world, transport, on, monkeypatch):
    monkeypatch.setenv("MKA_AUTOMATION_RUN_SEND_CAP", "1")
    await attest(db, 31, 5001, TODAY)
    await attest(db, 32, 5001, TODAY)
    async with make_client(db) as c:
        r = await c.post(SWEEP, params={"dry_run": "false"}, headers=cron())
        assert len(transport.calls) == 1
        await c.post(SWEEP, params={"dry_run": "false"}, headers=cron())  # next run continues, never exceeding the cap
        assert len(transport.calls) == 2
    assert r.json()["results"]["sent"] == 1 and r.json()["budget"]["stopped"] == "send_cap_reached"


async def test_sweep_real_run_is_disabled_when_flags_are_off_but_dry_run_still_previews(db, world, transport, monkeypatch):
    monkeypatch.setenv("MKA_AUTOMATION_CRON_SECRET", CRON)
    await attest(db, 31, 5001, TODAY)
    async with make_client(db) as c:
        real = await c.post(SWEEP, params={"dry_run": "false"}, headers=cron())
        dry = await c.post(SWEEP, headers=cron())
    assert real.json() == {"status": "disabled", "dry_run": False}
    assert dry.json()["status"] == "ok" and transport.calls == [] and await logs(db) == []


async def test_sweep_in_test_mode_only_mails_the_tester_and_dry_run_sees_test_rows_as_handled(db, world, transport, on, monkeypatch):
    monkeypatch.setenv("MKA_AUTOMATION_TEST_RECIPIENT", TESTER)
    await attest(db, 31, 5001, TODAY)
    async with make_client(db) as c:
        await c.post(SWEEP, params={"dry_run": "false"}, headers=cron())
        again = await c.post(SWEEP, headers=cron())
    assert {m["to"] for m in transport.calls} == {TESTER} and len(transport.calls) == 1
    assert again.json()["results"] == {"already_handled": 1}


async def test_sweep_is_org_scoped_and_can_be_limited_to_one_org(db, world, transport, on):
    await attest(db, 31, 5001, TODAY)
    await attest(db, 41, 6001, TODAY)
    async with make_client(db) as c:
        r = await c.post(SWEEP, params={"dry_run": "false", "org_id": 2}, headers=cron())
    assert r.json()["candidates"] == 1 and [m["to"] for m in transport.calls if "all set" not in m["subject"]] == [O2]
    assert {x.org_id for x in await logs(db)} == {2}


async def test_sweep_skips_unproven_and_off_roster_people(db, world, transport, on):
    await attest(db, 33, 5001, TODAY)
    await attest(db, 34, 5001, TODAY)
    async with make_client(db) as c:
        r = await c.post(SWEEP, params={"dry_run": "false"}, headers=cron())
    assert transport.calls == [] and await logs(db) == []
    assert r.json()["results"] == {"skipped_not_on_roster_or_unproven": 2}


async def test_sweep_days_is_bounded(db, world, transport, on):
    async with make_client(db) as c:
        assert (await c.post(SWEEP, params={"days": 0}, headers=cron())).status_code == 422
        assert (await c.post(SWEEP, params={"days": 9999}, headers=cron())).status_code == 422


# --- mounting ------------------------------------------------------------------------------------------------


async def test_both_endpoints_work_without_any_session_cookie_or_token(db, world, transport, on):
    await attest(db, 31, 5001, TODAY)
    async with make_client(db) as c:
        assert not c.cookies
        assert (await post(c, payload())).status_code == 200
        assert (await c.post(SWEEP, headers=cron())).status_code == 200


def test_the_receipts_router_is_included_by_one_marked_hook_in_the_fork_router():
    from pathlib import Path

    import src.routers.mka_automation as module

    text = Path(module.__file__).read_text(encoding="utf-8")
    assert "# --- seam B: webhook/receipts ---" in text
    assert text.count("include_router(_receipts_router)") == 1


# --- body size bound (unauthenticated until the HMAC is checked) -----------------------------------------------


async def test_streamed_body_without_content_length_is_cut_off_at_the_cap(db, world, transport, on):
    from src.routers.mka_automation_receipts import MAX_BODY_BYTES

    chunk, read = b"x" * 8192, []

    async def gen():
        for i in range(10_000):  # ~80 MB if fully consumed
            read.append(i)
            yield chunk

    async with make_client(db) as c:
        r = await c.post(WEBHOOK, content=gen(), headers={"X-Webhook-Signature": "sha256=" + "0" * 64})
    assert r.status_code == 413
    assert len(read) * len(chunk) <= MAX_BODY_BYTES + 3 * len(chunk)


async def test_lying_small_content_length_with_a_large_body_is_413(db, world, transport, on):
    from src.routers.mka_automation_receipts import MAX_BODY_BYTES

    big = b"y" * (MAX_BODY_BYTES + 1)
    async with make_client(db) as c:
        r = await c.post(WEBHOOK, content=big, headers={"Content-Length": "10"})
    assert r.status_code in (413, 400)  # server may reject the mismatch itself; never 200/processing
    assert transport.calls == []


async def test_exact_cap_body_with_a_valid_signature_is_still_verified(db, world, transport, on):
    from src.routers.mka_automation_receipts import MAX_BODY_BYTES

    raw = b"[" + b" " * (MAX_BODY_BYTES - 2) + b"]"
    assert len(raw) == MAX_BODY_BYTES
    async with make_client(db) as c:
        r = await post(c, None, raw=raw)
    assert r.status_code == 400  # authenticated (not 401/413), then rejected as a non-object body


async def test_empty_body_is_401(db, world, transport, on):
    async with make_client(db) as c:
        r = await c.post(WEBHOOK, content=b"")
    assert r.status_code == 401
