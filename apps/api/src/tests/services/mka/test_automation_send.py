"""MKA fork: the central automation send function (kill switch, test-mode redirect, claim-before-send, caps).

The transport is ALWAYS mocked: no test here can send real email. Addresses are ``example.invalid``."""

import logging
import threading
from datetime import datetime, timezone

import pytest
from sqlmodel import select

from src.db.mka_automation import MkaAutomationSendLog
from src.services.mka import automation_send as send
from src.services.mka.automation_send import SendBudget, send_automation_email

REAL = "person@example.invalid"
TESTER = "owner@example.invalid"
FLAGS = ("MKA_AUTOMATION_ENABLED", "MKA_RECEIPTS_ENABLED", "MKA_REMINDERS_ENABLED", "MKA_AUTOMATION_TEST_RECIPIENT",
         "MKA_AUTOMATION_CONTACT_EMAIL", "MKA_AUTOMATION_WEEKLY_REMINDER_CAP", "MKA_COMPLIANCE_TZ")


class Transport:
    def __init__(self):
        self.calls = []
        self.fail_with = None
        self.threads = []

    def __call__(self, to, subject, body, headers=None, sender_name=None):
        self.threads.append(threading.current_thread())
        self.calls.append({"to": to, "subject": subject, "body": body, "headers": headers, "sender_name": sender_name})
        if self.fail_with is not None:
            raise self.fail_with


@pytest.fixture(autouse=True)
def env(monkeypatch):
    for name in FLAGS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def transport(monkeypatch):
    t = Transport()
    monkeypatch.setattr(send.email_utils, "send_email", t)
    return t


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv("MKA_AUTOMATION_ENABLED", "true")
    monkeypatch.setenv("MKA_RECEIPTS_ENABLED", "true")
    monkeypatch.setenv("MKA_REMINDERS_ENABLED", "true")


def kw(org, **over):
    base = dict(org_id=org.id, kind="receipt", dedupe_key="receipt:a1:7", to_email=REAL, subject="Hello",
                html_body="<p>Hi</p>", dry_run=False)
    base.update(over)
    return base


async def rows(db):
    return (await db.execute(select(MkaAutomationSendLog).order_by(MkaAutomationSendLog.id))).scalars().all()


# --- dry run -----------------------------------------------------------------------------------------------


async def test_dry_run_is_the_default_and_touches_nothing(db, org, transport, on):
    args = kw(org)
    args.pop("dry_run")
    res = await send_automation_email(db, **args)
    assert res.status == "dry_run" and res.to == REAL and res.subject == "Hello" and not res.test_mode
    assert transport.calls == [] and await rows(db) == []


async def test_dry_run_works_even_with_the_kill_switch_off_and_shows_the_redirect(db, org, transport, monkeypatch):
    monkeypatch.setenv("MKA_AUTOMATION_TEST_RECIPIENT", TESTER)
    res = await send_automation_email(db, **kw(org, dry_run=True))
    assert res.status == "dry_run" and res.to == TESTER and res.subject.startswith("[TEST → person@example.invalid]")
    assert res.test_mode and transport.calls == [] and await rows(db) == []


# --- kill switch ------------------------------------------------------------------------------------------


async def test_disabled_by_default_sends_nothing_and_logs_nothing(db, org, transport):
    res = await send_automation_email(db, **kw(org))
    assert res.status == "disabled" and transport.calls == [] and await rows(db) == []


@pytest.mark.parametrize("kind,flag", [("receipt", "MKA_RECEIPTS_ENABLED"), ("allset", "MKA_RECEIPTS_ENABLED"),
                                       ("reminder", "MKA_REMINDERS_ENABLED"), ("digest", "MKA_REMINDERS_ENABLED")])
async def test_feature_flag_needs_the_master_switch(db, org, transport, monkeypatch, kind, flag):
    monkeypatch.setenv(flag, "true")  # feature on, master off
    assert (await send_automation_email(db, **kw(org, kind=kind))).status == "disabled"
    monkeypatch.setenv("MKA_AUTOMATION_ENABLED", "true")
    monkeypatch.setenv(flag, "false")  # master on, feature off
    assert (await send_automation_email(db, **kw(org, kind=kind))).status == "disabled"
    assert transport.calls == [] and await rows(db) == []


async def test_receipts_flag_does_not_enable_reminders(db, org, transport, monkeypatch):
    monkeypatch.setenv("MKA_AUTOMATION_ENABLED", "true")
    monkeypatch.setenv("MKA_RECEIPTS_ENABLED", "true")
    assert (await send_automation_email(db, **kw(org, kind="reminder", dedupe_key="reminder:2026-W45:x"))).status == "disabled"
    assert transport.calls == []


# --- a real send ------------------------------------------------------------------------------------------


async def test_real_send_goes_to_the_intended_address_and_is_logged(db, org, transport, on, monkeypatch):
    monkeypatch.setenv("MKA_AUTOMATION_CONTACT_EMAIL", "help@example.invalid")
    res = await send_automation_email(db, **kw(org, user_id=5, cycle_id=3, course_id=9, sender_name="MKA"))
    assert res.status == "sent" and res.sent and res.to == REAL and not res.test_mode
    assert transport.calls == [{"to": REAL, "subject": "Hello", "body": "<p>Hi</p>",
                                "headers": {"Reply-To": "help@example.invalid"}, "sender_name": "MKA"}]
    (row,) = await rows(db)
    assert (row.status, row.org_id, row.kind, row.dedupe_key, row.to_email, row.intended_email, row.test_mode,
            row.user_id, row.cycle_id, row.course_id) == ("sent", org.id, "receipt", "receipt:a1:7", REAL, REAL, False, 5, 3, 9)
    assert row.sent_at is not None and row.error is None


async def test_recipient_is_normalised_and_transport_runs_off_the_event_loop(db, org, transport, on):
    await send_automation_email(db, **kw(org, to_email="  Person@Example.INVALID "))
    assert transport.calls[0]["to"] == REAL
    assert transport.threads[0] is not threading.main_thread()  # blocking send_email must not run on the loop


async def test_no_contact_email_means_no_reply_to(db, org, transport, on):
    await send_automation_email(db, **kw(org))
    assert transport.calls[0]["headers"] is None


# --- claim before send / idempotency -------------------------------------------------------------------


async def test_same_key_twice_sends_once(db, org, transport, on):
    assert (await send_automation_email(db, **kw(org))).status == "sent"
    again = await send_automation_email(db, **kw(org))
    assert again.status == "already_handled" and again.log_id is None
    assert len(transport.calls) == 1 and len(await rows(db)) == 1


async def test_claim_is_durable_before_the_transport_is_called(db, org, engine, on, monkeypatch):
    """The 'queued' row must be visible to ANOTHER session while the email is in flight."""
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from sqlmodel.ext.asyncio.session import AsyncSession

    seen = {}

    def spy(to, subject, body, headers=None, sender_name=None):
        seen["status"] = "called"

    monkeypatch.setattr(send.email_utils, "send_email", spy)
    other = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    orig = send._claim

    async def claim_then_peek(session, row):
        out = await orig(session, row)
        async with other() as s2:
            seen["rows"] = [r.status for r in (await s2.execute(select(MkaAutomationSendLog))).scalars().all()]
        return out

    monkeypatch.setattr(send, "_claim", claim_then_peek)
    await send_automation_email(db, **kw(org))
    assert seen["rows"] == ["queued"] and seen["status"] == "called"


async def test_a_stuck_queued_row_is_never_resent(db, org, transport, on):
    db.add(MkaAutomationSendLog(org_id=org.id, kind="receipt", dedupe_key="receipt:a1:7", to_email=REAL,
                                intended_email=REAL, subject="s", status="queued"))
    await db.commit()
    assert (await send_automation_email(db, **kw(org))).status == "already_handled"
    assert transport.calls == []


async def test_a_failed_row_is_reclaimed_and_retried_once(db, org, transport, on):
    transport.fail_with = RuntimeError("boom for person@example.invalid")
    res = await send_automation_email(db, **kw(org))
    assert res.status == "failed" and res.error == "RuntimeError"
    (row,) = await rows(db)
    assert row.status == "failed" and "person@example.invalid" not in (row.error or "")
    transport.fail_with = None
    retry = await send_automation_email(db, **kw(org))
    assert retry.status == "sent" and retry.log_id == row.id
    again = await send_automation_email(db, **kw(org))
    assert again.status == "already_handled"
    (row,) = await rows(db)
    assert row.status == "sent" and row.error is None and len(transport.calls) == 2


async def test_http_exception_failure_records_the_status_code_only(db, org, transport, on):
    from fastapi import HTTPException

    transport.fail_with = HTTPException(status_code=503, detail="provider said person@example.invalid is bad")
    res = await send_automation_email(db, **kw(org))
    assert res.error == "HTTPException 503"


async def test_same_key_in_another_org_is_independent(db, org, other_org, transport, on):
    assert (await send_automation_email(db, **kw(org))).status == "sent"
    assert (await send_automation_email(db, **kw(other_org))).status == "sent"
    assert len(transport.calls) == 2


async def test_same_key_with_different_kind_is_independent(db, org, transport, on):
    assert (await send_automation_email(db, **kw(org))).status == "sent"
    assert (await send_automation_email(db, **kw(org, kind="allset"))).status == "sent"


async def test_pending_caller_work_survives_a_lost_claim(db, org, other_org, transport, on):
    await send_automation_email(db, **kw(org))
    db.add(MkaAutomationSendLog(org_id=other_org.id, kind="digest", dedupe_key="keep", to_email=REAL,
                                intended_email=REAL, subject="s", status="sent"))  # pending in the session
    assert (await send_automation_email(db, **kw(org))).status == "already_handled"
    await db.commit()
    assert {r.dedupe_key for r in await rows(db)} == {"receipt:a1:7", "keep"}


# --- test-mode redirect -----------------------------------------------------------------------------------


async def test_test_mode_redirects_prefixes_and_marks_the_row(db, org, transport, on, monkeypatch):
    monkeypatch.setenv("MKA_AUTOMATION_TEST_RECIPIENT", TESTER.upper())
    res = await send_automation_email(db, **kw(org))
    assert res.status == "sent" and res.test_mode and res.to == TESTER
    (call,) = transport.calls
    assert call["to"] == TESTER
    assert call["subject"] == "[TEST → person@example.invalid] Hello"
    assert "person@example.invalid" in call["body"] and call["body"].endswith("<p>Hi</p>")
    (row,) = await rows(db)
    assert (row.to_email, row.intended_email, row.test_mode, row.subject) == (TESTER, REAL, True, call["subject"])


async def test_test_mode_never_contacts_anyone_else_even_with_reply_to_and_contact(db, org, transport, on, monkeypatch):
    monkeypatch.setenv("MKA_AUTOMATION_TEST_RECIPIENT", TESTER)
    monkeypatch.setenv("MKA_AUTOMATION_CONTACT_EMAIL", "help@example.invalid")
    await send_automation_email(db, **kw(org, headers={"Reply-To": "someone.else@example.invalid", "X-MKA-Kind": "receipt"}))
    (call,) = transport.calls
    assert call["to"] == TESTER
    assert call["headers"] is None  # no Reply-To, no custom headers: nothing that could reach another address
    flat = repr(call["headers"]) + call["to"]
    assert "help@example.invalid" not in flat and "someone.else" not in flat


@pytest.mark.parametrize("header", ["Cc", "BCC", "bcc", "To", "From", "Sender", "Return-Path", "Resent-To",
                                    "List-Unsubscribe", "Disposition-Notification-To", "Errors-To", "X-Anything"])
@pytest.mark.parametrize("test_mode", [True, False])
async def test_forbidden_headers_are_rejected_before_anything_is_claimed_or_sent(db, org, transport, on, monkeypatch, header, test_mode):
    if test_mode:
        monkeypatch.setenv("MKA_AUTOMATION_TEST_RECIPIENT", TESTER)
    with pytest.raises(ValueError):
        await send_automation_email(db, **kw(org, headers={header: "x@example.invalid"}))
    assert transport.calls == [] and await rows(db) == []


async def test_header_values_with_newlines_are_rejected(db, org, transport, on):
    for headers in ({"Reply-To": "a@example.invalid\r\nBcc: b@example.invalid"}, {"X-MKA-Kind": "a\nBcc: b@example.invalid"}):
        with pytest.raises(ValueError):
            await send_automation_email(db, **kw(org, headers=headers))
    assert transport.calls == []


async def test_reply_to_must_be_a_single_address_in_real_mode(db, org, transport, on):
    with pytest.raises(ValueError):
        await send_automation_email(db, **kw(org, headers={"Reply-To": "a@example.invalid, b@example.invalid"}))
    await send_automation_email(db, **kw(org, headers={"Reply-To": "ok@example.invalid"}))
    assert transport.calls[0]["headers"] == {"Reply-To": "ok@example.invalid"}


@pytest.mark.parametrize("bad", ["a@example.invalid,b@example.invalid", "a@example.invalid\r\nBcc: b@example.invalid",
                                 "a b@example.invalid", "<a@example.invalid>", "nope", "", "a@b"])
async def test_a_malformed_or_multiple_recipient_is_refused(db, org, transport, on, bad):
    with pytest.raises(ValueError):
        await send_automation_email(db, **kw(org, to_email=bad))
    assert transport.calls == []


async def test_subject_newlines_cannot_inject_headers(db, org, transport, on):
    await send_automation_email(db, **kw(org, subject="Hi\r\nBcc: evil@example.invalid"))
    subject = transport.calls[0]["subject"]
    assert "\r" not in subject and "\n" not in subject


async def test_test_banner_escapes_the_intended_address(db, org, transport, on, monkeypatch):
    monkeypatch.setenv("MKA_AUTOMATION_TEST_RECIPIENT", TESTER)
    await send_automation_email(db, **kw(org, to_email="a&b@example.invalid"))
    body = transport.calls[0]["body"]
    assert "a&amp;b@example.invalid" in body and "a&b@example" not in body


@pytest.mark.parametrize("bad", ["garbage", "a@b.invalid,c@d.invalid", "a@b.invalid\r\nBcc: x@y.invalid"])
@pytest.mark.parametrize("dry_run", [True, False])
async def test_malformed_test_recipient_refuses_instead_of_sending_for_real(db, org, transport, on, monkeypatch, bad, dry_run):
    monkeypatch.setenv("MKA_AUTOMATION_TEST_RECIPIENT", bad)
    res = await send_automation_email(db, **kw(org, dry_run=dry_run))
    assert res.status == "disabled" and res.reason == "invalid_test_recipient"
    assert transport.calls == [] and await rows(db) == []


async def test_test_sends_do_not_consume_the_real_dedupe_key(db, org, transport, on, monkeypatch):
    monkeypatch.setenv("MKA_AUTOMATION_TEST_RECIPIENT", TESTER)
    assert (await send_automation_email(db, **kw(org))).status == "sent"
    assert (await send_automation_email(db, **kw(org))).status == "already_handled"  # still deduped within test mode
    monkeypatch.delenv("MKA_AUTOMATION_TEST_RECIPIENT")
    real = await send_automation_email(db, **kw(org))  # the real officeholder must still get the real mail
    assert real.status == "sent" and real.to == REAL
    assert [c["to"] for c in transport.calls] == [TESTER, REAL]
    assert sorted(r.dedupe_key for r in await rows(db)) == ["receipt:a1:7", "test:receipt:a1:7"]
    assert await send.has_real_send(db, org.id, "receipt", "receipt:a1:7")


async def test_has_real_send_ignores_test_rows(db, org, transport, on, monkeypatch):
    monkeypatch.setenv("MKA_AUTOMATION_TEST_RECIPIENT", TESTER)
    await send_automation_email(db, **kw(org))
    assert not await send.has_real_send(db, org.id, "receipt", "receipt:a1:7")
    assert not await send.has_real_send(db, org.id, "receipt", "test:receipt:a1:7")


async def test_caller_cannot_use_the_reserved_test_namespace(db, org, transport, on):
    with pytest.raises(ValueError):
        await send_automation_email(db, **kw(org, dedupe_key="test:receipt:a1:7"))


@pytest.mark.parametrize("key", ["", "   ", "x" * 256, "a\nb"])
async def test_bad_dedupe_keys_are_refused(db, org, transport, on, key):
    with pytest.raises(ValueError):
        await send_automation_email(db, **kw(org, dedupe_key=key))


async def test_unknown_kind_and_empty_subject_are_refused(db, org, transport, on):
    with pytest.raises(ValueError):
        await send_automation_email(db, **kw(org, kind="marketing"))
    with pytest.raises(ValueError):
        await send_automation_email(db, **kw(org, subject="  \r\n "))


# --- suppressed recipients ------------------------------------------------------------------------------


@pytest.mark.parametrize("addr", ["deleted-user-5@anonymized.example.com", "erased@anonymized.invalid", "kid@demo.example.com"])
async def test_anonymised_and_demo_addresses_are_suppressed_and_never_mailed(db, org, transport, on, addr):
    res = await send_automation_email(db, **kw(org, to_email=addr))
    assert res.status == "suppressed" and transport.calls == []
    (row,) = await rows(db)
    assert row.status == "suppressed"


async def test_suppression_applies_in_test_mode_too(db, org, transport, on, monkeypatch):
    monkeypatch.setenv("MKA_AUTOMATION_TEST_RECIPIENT", TESTER)
    res = await send_automation_email(db, **kw(org, to_email="x@anonymized.invalid"))
    assert res.status == "suppressed" and transport.calls == []


# --- weekly reminder cap ----------------------------------------------------------------------------------

WEEK45 = datetime(2026, 11, 5, 15, 0, tzinfo=timezone.utc)   # Thursday, ISO 2026-W45
WEEK46 = datetime(2026, 11, 12, 15, 0, tzinfo=timezone.utc)


def rem(org, key, **over):
    return kw(org, kind="reminder", dedupe_key=key, subject="Reminder", **over)


async def test_second_reminder_in_the_same_week_is_capped_even_with_a_different_key(db, org, transport, on):
    assert (await send_automation_email(db, **rem(org, "reminder:a"), now=WEEK45)).status == "sent"
    res = await send_automation_email(db, **rem(org, "reminder:b"), now=WEEK45)
    assert res.status == "capped" and res.reason == "weekly_reminder_cap"
    assert len(transport.calls) == 1 and len(await rows(db)) == 1


async def test_cap_resets_next_iso_week(db, org, transport, on, monkeypatch):
    # created_at is real wall-clock "now"; move the row into W45 so the W46 check must not see it
    await send_automation_email(db, **rem(org, "reminder:a"), now=WEEK45)
    (row,) = await rows(db)
    row.created_at = datetime(2026, 11, 5, 15, 0)
    db.add(row)
    await db.commit()
    assert await send.reminded_this_week(db, org.id, REAL, "2026-W45")
    assert not await send.reminded_this_week(db, org.id, REAL, "2026-W46")


async def test_cap_is_per_org_per_person_and_ignores_test_failed_and_other_kinds(db, org, other_org, transport, on, monkeypatch):
    week = send.current_iso_week()
    other_person = "other@example.invalid"
    db.add_all([
        MkaAutomationSendLog(org_id=other_org.id, kind="reminder", dedupe_key="reminder:w:k1", to_email=REAL, intended_email=REAL, subject="s", status="sent"),
        MkaAutomationSendLog(org_id=org.id, kind="reminder", dedupe_key="k2", to_email=TESTER, intended_email=REAL, subject="s", status="sent", test_mode=True),
        MkaAutomationSendLog(org_id=org.id, kind="reminder", dedupe_key="k3", to_email=REAL, intended_email=REAL, subject="s", status="failed"),
        MkaAutomationSendLog(org_id=org.id, kind="digest", dedupe_key="k4", to_email=REAL, intended_email=REAL, subject="s", status="sent"),
        MkaAutomationSendLog(org_id=org.id, kind="reminder", dedupe_key="reminder:w:k5", to_email=other_person, intended_email=other_person, subject="s", status="sent"),
    ])
    await db.commit()
    assert not await send.reminded_this_week(db, org.id, REAL, week)
    assert await send.reminded_this_week(db, org.id, other_person, week)
    assert await send.reminded_this_week(db, other_org.id, REAL, week)


async def test_weekly_cap_is_configurable(db, org, transport, on, monkeypatch):
    monkeypatch.setenv("MKA_AUTOMATION_WEEKLY_REMINDER_CAP", "2")
    assert (await send_automation_email(db, **rem(org, "reminder:a"))).status == "sent"
    assert (await send_automation_email(db, **rem(org, "reminder:b"))).status == "sent"
    assert (await send_automation_email(db, **rem(org, "reminder:c"))).status == "capped"


async def test_test_mode_reminders_are_not_capped_by_or_counted_toward_the_real_cap(db, org, transport, on, monkeypatch):
    monkeypatch.setenv("MKA_AUTOMATION_TEST_RECIPIENT", TESTER)
    assert (await send_automation_email(db, **rem(org, "reminder:a"))).status == "sent"
    assert (await send_automation_email(db, **rem(org, "reminder:b"))).status == "sent"
    monkeypatch.delenv("MKA_AUTOMATION_TEST_RECIPIENT")
    assert (await send_automation_email(db, **rem(org, "reminder:c"))).status == "sent"


async def test_week_window_uses_the_cycle_timezone(db, org, monkeypatch):
    # Sunday 23:30 New York (EST, UTC-5) == Monday 04:30 UTC: it belongs to the NY week that just ended (W44)
    db.add(MkaAutomationSendLog(org_id=org.id, kind="reminder", dedupe_key="reminder:w:k", to_email=REAL,
                                intended_email=REAL, subject="s", status="sent",
                                created_at=datetime(2026, 11, 2, 4, 30)))
    await db.commit()
    assert await send.reminded_this_week(db, org.id, REAL, "2026-W44")
    assert not await send.reminded_this_week(db, org.id, REAL, "2026-W45")
    monkeypatch.setenv("MKA_COMPLIANCE_TZ", "UTC")
    assert not await send.reminded_this_week(db, org.id, REAL, "2026-W44")
    assert await send.reminded_this_week(db, org.id, REAL, "2026-W45")


def test_iso_week_helpers():
    from datetime import date

    assert send.iso_week_label(date(2026, 11, 5)) == "2026-W45"
    assert send.iso_week_label(date(2027, 1, 1)) == "2026-W53"
    assert send.current_iso_week(datetime(2026, 11, 2, 4, 30)) == "2026-W44"  # naive = UTC, Sunday evening in New York
    assert send.reminder_dedupe_key(" A@B.invalid ", "2026-W45") == "reminder:2026-W45:a@b.invalid"


@pytest.mark.parametrize("bad", ["2026-45", "W45", "", "2026-W99x"])
async def test_bad_iso_week_is_refused(db, org, bad):
    with pytest.raises(ValueError):
        await send.reminded_this_week(db, org.id, REAL, bad)


# --- budget -------------------------------------------------------------------------------------------------


class Sleeper:
    def __init__(self):
        self.slept = []

    async def __call__(self, seconds):
        self.slept.append(seconds)


def keyed(org, n, **over):
    return kw(org, **{"dedupe_key": f"receipt:{n}", "to_email": f"p{n}@example.invalid", **over})


async def test_budget_caps_sends_and_leaves_no_queued_rows_behind(db, org, transport, on):
    budget = SendBudget(max_sends=2, delay_seconds=0, max_consecutive_failures=5)
    out = [await send_automation_email(db, **keyed(org, n), budget=budget) for n in range(4)]
    assert [r.status for r in out] == ["sent", "sent", "budget_exhausted", "budget_exhausted"]
    assert out[2].reason == "send_cap_reached" and budget.stop_reason == "send_cap_reached"
    assert len(transport.calls) == 2 and [r.status for r in await rows(db)] == ["sent", "sent"]


async def test_budget_stops_after_consecutive_failures_and_success_resets_the_streak(db, org, transport, on):
    budget = SendBudget(max_sends=100, delay_seconds=0, max_consecutive_failures=2)
    transport.fail_with = RuntimeError("x")
    assert (await send_automation_email(db, **keyed(org, 0), budget=budget)).status == "failed"
    transport.fail_with = None
    assert (await send_automation_email(db, **keyed(org, 1), budget=budget)).status == "sent"
    assert budget.consecutive_failures == 0
    transport.fail_with = RuntimeError("x")
    assert (await send_automation_email(db, **keyed(org, 2), budget=budget)).status == "failed"
    assert (await send_automation_email(db, **keyed(org, 3), budget=budget)).status == "failed"
    res = await send_automation_email(db, **keyed(org, 4), budget=budget)
    assert res.status == "budget_exhausted" and res.reason == "too_many_consecutive_failures"
    assert budget.summary() == {"attempts": 4, "sent": 1, "failed": 3, "stopped": "too_many_consecutive_failures"}
    assert len(transport.calls) == 4


async def test_budget_paces_between_real_sends_only(db, org, transport, on):
    sleeper = Sleeper()
    budget = SendBudget(max_sends=10, delay_seconds=0.5, max_consecutive_failures=5, sleep=sleeper)
    await send_automation_email(db, **keyed(org, 0), budget=budget)
    assert sleeper.slept == []                                   # never before the first
    await send_automation_email(db, **keyed(org, 0), budget=budget)  # already handled: no pause, no count
    await send_automation_email(db, **keyed(org, 1, dry_run=True), budget=budget)  # dry run: no pause, no count
    assert sleeper.slept == [] and budget.attempts == 1
    await send_automation_email(db, **keyed(org, 1), budget=budget)
    assert sleeper.slept == [0.5] and budget.attempts == 2


async def test_budget_is_not_charged_for_disabled_or_capped_or_suppressed(db, org, transport, on, monkeypatch):
    budget = SendBudget(max_sends=1, delay_seconds=0, max_consecutive_failures=5)
    await send_automation_email(db, **keyed(org, 0, to_email="x@anonymized.invalid"), budget=budget)
    monkeypatch.setenv("MKA_AUTOMATION_ENABLED", "false")
    await send_automation_email(db, **keyed(org, 1), budget=budget)
    assert budget.attempts == 0 and budget.can_send()


def test_budget_defaults_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("MKA_AUTOMATION_RUN_SEND_CAP", "7")
    monkeypatch.setenv("MKA_AUTOMATION_SEND_DELAY_SECONDS", "1.5")
    monkeypatch.setenv("MKA_AUTOMATION_MAX_CONSECUTIVE_FAILURES", "3")
    b = SendBudget()
    assert (b.max_sends, b.delay_seconds, b.max_consecutive_failures) == (7, 1.5, 3)


def test_a_zero_cap_budget_blocks_everything():
    assert not SendBudget(max_sends=0, delay_seconds=0, max_consecutive_failures=5).can_send()


# --- logging ----------------------------------------------------------------------------------------------------


async def test_logs_never_contain_addresses_or_subjects(db, org, transport, on, caplog, monkeypatch):
    monkeypatch.setenv("MKA_AUTOMATION_TEST_RECIPIENT", TESTER)
    caplog.set_level(logging.DEBUG)
    transport.fail_with = RuntimeError("provider rejected person@example.invalid")
    await send_automation_email(db, **kw(org, subject="Secret subject"))
    transport.fail_with = None
    await send_automation_email(db, **kw(org, subject="Secret subject"))
    await send_automation_email(db, **kw(org, dedupe_key="k2", to_email="x@anonymized.invalid"))
    ours = "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("src.services.mka"))
    assert "automation send" in ours  # we do log...
    assert "example.invalid" not in ours and "Secret subject" not in ours  # ...but never addresses or subjects
