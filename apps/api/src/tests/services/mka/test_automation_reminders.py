"""MKA fork: seam C reminders + digest run (spec 2026-10-05 section 2C).

The transport is ALWAYS mocked; every address is ``example.invalid``. The seeded world is the compliance world:
org 1 cycle 2026-27 (2026-11-01 .. 2026-12-01, tz America/New_York), 10 roster rows; at the "as of" dates used here
l1 and ex are attested, everybody else still has something outstanding (8 people).
"""

import logging
import threading
from datetime import datetime, timezone

import pytest
from sqlmodel import select

from src.db.mka_automation import MkaAutomationSendLog
from src.db.mka_compliance import MkaComplianceExpected
from src.services.mka import automation_reminders as rem
from src.services.mka import automation_send as send
from src.tests.routers.mka_compliance_world import build_world, expected  # noqa: F401  (expected used below)

TESTER = "owner@example.invalid"
FLAGS = (
    "MKA_AUTOMATION_ENABLED", "MKA_RECEIPTS_ENABLED", "MKA_REMINDERS_ENABLED", "MKA_AUTOMATION_TEST_RECIPIENT",
    "MKA_AUTOMATION_CONTACT_EMAIL", "MKA_AUTOMATION_WEEKLY_REMINDER_CAP", "MKA_COMPLIANCE_TZ",
    "MKA_REMINDER_SCHEDULE", "MKA_AUTOMATION_RUN_SEND_CAP", "MKA_AUTOMATION_MAX_CONSECUTIVE_FAILURES",
    "MKA_REMINDER_EXCLUDED_DEPARTMENTS", "LEARNHOUSE_PLATFORM_URL",
)
CANDIDATES = 8  # everybody on org 1's roster except l1 and ex (attested)


def utc(y, m, d, h=15):
    return datetime(y, m, d, h, 0, tzinfo=timezone.utc)


class Transport:
    def __init__(self):
        self.calls = []
        self.fail = False
        self.threads = []

    def __call__(self, to, subject, body, headers=None, sender_name=None):
        self.threads.append(threading.current_thread())
        self.calls.append({"to": to, "subject": subject, "body": body, "headers": headers})
        if self.fail:
            raise RuntimeError("smtp down")


@pytest.fixture(autouse=True)
def env(monkeypatch):
    for name in FLAGS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MKA_AUTOMATION_SEND_DELAY_SECONDS", "0")
    monkeypatch.setenv("LEARNHOUSE_PLATFORM_URL", "https://ilm.example.invalid")


@pytest.fixture
def transport(monkeypatch):
    t = Transport()
    monkeypatch.setattr(send.email_utils, "send_email", t)
    return t


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv("MKA_AUTOMATION_ENABLED", "true")
    monkeypatch.setenv("MKA_REMINDERS_ENABLED", "true")


@pytest.fixture
def test_mode(monkeypatch):
    monkeypatch.setenv("MKA_AUTOMATION_TEST_RECIPIENT", TESTER)


@pytest.fixture
async def world(db, org, other_org, admin_user, regular_user):
    return await build_world(db, org, other_org, admin_user, regular_user)


async def go(db, now, org, **kw):
    """Run for all orgs and return org 1's report (the full report is returned under ``_all``)."""
    kw.setdefault("dry_run", True)
    kw.setdefault("kind", "reminder")
    report = await rem.run_all(db, now=now, **kw)
    mine = next(o for o in report["orgs"] if o["org_id"] == org.id)
    return {**mine, "_all": report}


async def log_rows(db, **where):
    stmt = select(MkaAutomationSendLog).order_by(MkaAutomationSendLog.id)
    return [r for r in (await db.execute(stmt)).scalars().all() if all(getattr(r, k) == v for k, v in where.items())]


# --- schedule: boundary dates + cycle timezone ----------------------------------------------------------------


@pytest.mark.parametrize(
    "now, ran",
    [
        (utc(2026, 11, 7), False),
        (utc(2026, 11, 8), True),
        (utc(2026, 11, 9, 3), True),   # 22:00 on Nov 8 in New York: still the 8th there (UTC date says the 9th)
        (utc(2026, 11, 8, 3), False),  # 22:00 on Nov 7 in New York (UTC date says the 8th)
        (utc(2026, 11, 15), True),
        (utc(2026, 11, 22), True),
        (utc(2026, 11, 28), True),     # the final reminder
        (utc(2026, 11, 29), False),
        (utc(2026, 12, 1), False),     # deadline day: nobody is overdue yet and it is not a scheduled day
        (utc(2026, 12, 2, 1), False),  # 20:00 on Dec 1 in New York: still the deadline day
        (utc(2026, 12, 7), False),
        (utc(2026, 12, 8), True),      # first weekly reminder after the deadline
        (utc(2026, 12, 15), True),
        (utc(2026, 12, 16), False),
    ],
)
async def test_reminder_day_schedule(db, org, world, now, ran):
    rep = await go(db, now, org)
    assert rep["reminder"]["ran"] is ran
    if not ran:
        assert rep["reminder"]["reason"] == "not_a_reminder_day"


async def test_non_reminder_day_does_nothing(db, org, world, transport, on, test_mode):
    rep = await go(db, utc(2026, 11, 10), org, dry_run=False)
    assert rep["reminder"] == {"ran": False, "reason": "not_a_reminder_day"}
    assert transport.calls == [] and await log_rows(db) == []


async def test_nothing_before_the_cycle_starts(db, org, world, monkeypatch):
    monkeypatch.setenv("MKA_REMINDER_SCHEDULE", "10-20")
    rep = await go(db, utc(2026, 10, 20), org)
    assert rep["reminder"] == {"ran": False, "reason": "cycle_not_started"}


async def test_after_the_deadline_people_are_overdue(db, org, world, transport, on, test_mode):
    rep = await go(db, utc(2026, 12, 8), org, dry_run=False)
    assert rep["reminder"]["sent"] == CANDIDATES
    assert all(c["subject"].startswith("[TEST") and "Overdue:" in c["subject"] for c in transport.calls)
    assert all("overdue" in c["body"] for c in transport.calls)


async def test_no_cycle_means_no_run(db, org, other_org):
    rep = await rem.run_all(db, dry_run=True, kind="all", now=utc(2026, 11, 8))
    assert rep["orgs"] == []


# --- recipients ----------------------------------------------------------------------------------------------


async def test_recipients_are_deduped_by_email_and_exclude_attested(db, org, world, transport, on, test_mode):
    rep = await go(db, utc(2026, 11, 15), org, dry_run=False)
    r = rep["reminder"]
    assert (r["candidates"], r["sent"], r["skipped_attested"]) == (CANDIDATES, CANDIDATES, 3)  # l1 x2 + ex
    intended = sorted(row.intended_email for row in await log_rows(db, org_id=org.id, kind="reminder"))
    assert len(intended) == len(set(intended)) == CANDIDATES
    assert "l1@example.invalid" not in intended and "ex@example.invalid" not in intended
    # multi-role person: ONE e-mail naming both courses (general + tabligh)
    l2 = [c for c in transport.calls if "l2@example.invalid" in c["subject"]]
    assert len(l2) == 1
    assert "General 2026-27" in l2[0]["body"] and "Tabligh 2026-27" in l2[0]["body"]


async def test_excluded_departments_are_skipped(db, org, world, transport, on, test_mode):
    db.add(expected(org.id, world.cycle.id, "kid@example.invalid", "atfal", "local", "Albany", "Northeast", "Nazim Atfal", "Kid"))
    await db.commit()
    rep = await go(db, utc(2026, 11, 15), org, dry_run=False)
    assert rep["reminder"]["skipped_excluded"] >= 1 and rep["reminder"]["sent"] == CANDIDATES
    assert all("kid@example.invalid" not in c["subject"] for c in transport.calls)


async def test_excluded_departments_are_configurable(db, org, world, monkeypatch):
    monkeypatch.setenv("MKA_REMINDER_EXCLUDED_DEPARTMENTS", "maal")
    rep = await go(db, utc(2026, 11, 15), org)
    assert rep["reminder"]["would_send"] == CANDIDATES - 3  # l3, l4, ghost2 are maal; their general course is skipped too


async def test_role_mailbox_is_addressed_by_role_and_majlis(db, org, world, transport, on, test_mode, monkeypatch):
    monkeypatch.setattr(rem, "is_role_mailbox", lambda email: email == "l3@example.invalid")
    await go(db, utc(2026, 11, 15), org, dry_run=False)
    l3 = next(c for c in transport.calls if "l3@example.invalid" in c["subject"])
    assert "Hello Nazim Maal, Albany," in l3["body"]
    l4 = next(c for c in transport.calls if "l4@example.invalid" in c["subject"])
    assert "Hello L," in l4["body"]  # a personal account gets its first name


# --- dry run -------------------------------------------------------------------------------------------------


async def test_dry_run_sends_nothing_and_writes_no_send_log(db, org, world, transport, on, test_mode):
    rep = await go(db, utc(2026, 11, 15), org, dry_run=True, kind="all")
    assert rep["reminder"]["would_send"] == CANDIDATES and rep["reminder"]["sent"] == 0
    assert transport.calls == [] and await log_rows(db) == []


async def test_dry_run_needs_no_kill_switch(db, org, world, transport):
    rep = await go(db, utc(2026, 11, 15), org)  # no flags at all
    assert rep["reminder"]["would_send"] == CANDIDATES and transport.calls == []


# --- safety envelope -----------------------------------------------------------------------------------------


async def test_test_mode_never_emails_an_intended_recipient(db, org, world, transport, on, test_mode):
    rep = await go(db, utc(2026, 11, 16), org, dry_run=False, kind="all")  # reminder? Monday: digest day only
    await go(db, utc(2026, 11, 15), org, dry_run=False, kind="all")
    assert transport.calls, "something must have been sent for this test to mean anything"
    assert {c["to"] for c in transport.calls} == {TESTER}
    assert all(not c["headers"] for c in transport.calls)  # no Reply-To/Cc/Bcc survive test mode
    rows = await log_rows(db)
    assert rows and all(r.test_mode and r.to_email == TESTER for r in rows)
    assert rep["_all"]["test_mode"] is True


async def test_kill_switches(db, org, world, transport, monkeypatch):
    monkeypatch.setenv("MKA_AUTOMATION_TEST_RECIPIENT", TESTER)
    rep = await go(db, utc(2026, 11, 15), org, dry_run=False)  # nothing on
    assert rep["reminder"] == {"ran": False, "reason": "feature_off"}
    monkeypatch.setenv("MKA_REMINDERS_ENABLED", "true")  # feature on, master off
    rep = await go(db, utc(2026, 11, 15), org, dry_run=False)
    assert rep["reminder"]["reason"] == "feature_off"
    monkeypatch.delenv("MKA_REMINDERS_ENABLED")
    monkeypatch.setenv("MKA_AUTOMATION_ENABLED", "true")  # master on, feature off
    rep = await go(db, utc(2026, 11, 15), org, dry_run=False)
    assert rep["reminder"]["reason"] == "feature_off"
    assert transport.calls == [] and await log_rows(db) == []


async def test_invalid_test_recipient_refuses_the_whole_run(db, org, world, transport, on, monkeypatch):
    monkeypatch.setenv("MKA_AUTOMATION_TEST_RECIPIENT", "not an address, x@y.invalid")
    rep = await go(db, utc(2026, 11, 15), org, dry_run=False)
    assert rep["reminder"]["sent"] == 0 and rep["reminder"]["disabled_reason"] == "invalid_test_recipient"
    assert transport.calls == []


async def test_missing_frontend_url_fails_closed(db, org, world, transport, on, test_mode, monkeypatch):
    monkeypatch.delenv("LEARNHOUSE_PLATFORM_URL")
    monkeypatch.setattr(rem.email_utils, "_configured_frontend_base_url", lambda: None)
    rep = await go(db, utc(2026, 11, 15), org, dry_run=False)
    assert rep["reminder"] == {"ran": False, "reason": "no_frontend_url"} and transport.calls == []


# --- weekly cap, claim-before-send ------------------------------------------------------------------------------


async def test_at_most_one_reminder_per_person_per_iso_week(db, org, world, transport, on, monkeypatch):
    monkeypatch.setenv("MKA_REMINDER_SCHEDULE", "11-10,11-11,11-17")  # Tue + Wed of week 46, Tue of week 47
    first = await go(db, utc(2026, 11, 10), org, dry_run=False)
    assert first["reminder"]["sent"] == CANDIDATES
    again = await go(db, utc(2026, 11, 11), org, dry_run=False)  # same ISO week
    assert again["reminder"]["sent"] == 0 and again["reminder"]["skipped_recent"] == CANDIDATES
    assert len(await log_rows(db, org_id=org.id, kind="reminder")) == CANDIDATES  # still one row per person
    # the next ISO week starts a new allowance
    nxt = await go(db, utc(2026, 11, 17), org, dry_run=False)
    assert nxt["reminder"]["sent"] == CANDIDATES


async def test_dry_run_preview_reports_who_was_already_reminded_this_week(db, org, world, transport, on, monkeypatch):
    monkeypatch.setenv("MKA_REMINDER_SCHEDULE", "11-10,11-11")
    await go(db, utc(2026, 11, 10), org, dry_run=False)
    preview = await go(db, utc(2026, 11, 11), org, dry_run=True)
    assert preview["reminder"]["would_send"] == 0 and preview["reminder"]["skipped_recent"] == CANDIDATES


async def test_a_reminder_already_queued_by_a_concurrent_run_is_not_sent_again(db, org, world, transport, on, monkeypatch):
    monkeypatch.setenv("MKA_REMINDER_SCHEDULE", "11-10")
    week = send.current_iso_week(utc(2026, 11, 10))
    db.add(MkaAutomationSendLog(  # the other run claimed it (queued) but has not finished
        org_id=org.id, kind="reminder", dedupe_key=send.reminder_dedupe_key("l3@example.invalid", week),
        to_email="l3@example.invalid", intended_email="l3@example.invalid", subject="s", status="queued",
        created_at=datetime(2026, 11, 10, 14, 0),
    ))
    await db.commit()
    rep = await go(db, utc(2026, 11, 10), org, dry_run=False)
    assert rep["reminder"]["sent"] == CANDIDATES - 1 and rep["reminder"]["skipped_recent"] == 1
    assert all("l3@example.invalid" not in c["to"] and "l3@example.invalid" not in c["subject"] for c in transport.calls)


async def test_a_failed_send_is_retried_by_the_next_run_not_duplicated(db, org, world, transport, on, monkeypatch):
    monkeypatch.setenv("MKA_REMINDER_SCHEDULE", "11-10,11-11")
    monkeypatch.setenv("MKA_AUTOMATION_MAX_CONSECUTIVE_FAILURES", "100")
    transport.fail = True
    bad = await go(db, utc(2026, 11, 10), org, dry_run=False)
    assert bad["reminder"]["failed"] == CANDIDATES and bad["reminder"]["sent"] == 0
    transport.fail = False
    good = await go(db, utc(2026, 11, 11), org, dry_run=False)
    assert good["reminder"]["sent"] == CANDIDATES
    assert len(await log_rows(db, org_id=org.id, kind="reminder")) == CANDIDATES  # re-claimed, not duplicated


# --- budget --------------------------------------------------------------------------------------------------


async def test_run_send_cap_stops_the_run_without_leaving_queued_rows(db, org, world, transport, on, test_mode, monkeypatch):
    monkeypatch.setenv("MKA_AUTOMATION_RUN_SEND_CAP", "3")
    rep = await go(db, utc(2026, 11, 15), org, dry_run=False)
    assert rep["reminder"]["sent"] == 3 and rep["reminder"]["stopped"] == "send_cap_reached"
    assert len(transport.calls) == 3
    assert not [r for r in await log_rows(db) if r.status == "queued"]


async def test_hard_stop_after_consecutive_failures(db, org, world, transport, on, test_mode, monkeypatch):
    monkeypatch.setenv("MKA_AUTOMATION_MAX_CONSECUTIVE_FAILURES", "2")
    transport.fail = True
    rep = await go(db, utc(2026, 11, 15), org, dry_run=False)
    assert rep["reminder"]["failed"] == 2 and rep["reminder"]["stopped"] == "too_many_consecutive_failures"
    assert len(transport.calls) == 2


async def test_sends_run_off_the_event_loop(db, org, world, transport, on, test_mode):
    await go(db, utc(2026, 11, 15), org, dry_run=False)
    assert transport.threads and all(t is not threading.main_thread() for t in transport.threads)


# --- digest -------------------------------------------------------------------------------------------------


async def test_digest_only_on_mondays(db, org, world, transport, on, test_mode):
    sun = await go(db, utc(2026, 11, 15), org, dry_run=False, kind="digest")
    assert sun["digest"] == {"ran": False, "reason": "not_a_monday"}
    mon = await go(db, utc(2026, 11, 16), org, dry_run=False, kind="digest")
    assert mon["digest"]["ran"] is True and mon["digest"]["sent"] == 2 and "reminder" not in mon


async def test_digest_scoping_mohtamim_sees_only_their_department(db, org, world, transport, on, test_mode):
    await go(db, utc(2026, 11, 16), org, dry_run=False, kind="digest")
    head = next(c for c in transport.calls if "head.tabligh@example.invalid" in c["subject"])
    body = head["body"]
    assert "Nazim Tabligh, Boston" in body and "Nazim Tabligh, Dallas" in body and "Nazim Tabligh, Albany" in body
    assert "Nazim Maal" not in body and "Syracuse" not in body  # another department
    assert "Mohtamim Tabligh" in body  # addressed by role title


async def test_digest_scoping_regional_qaid_sees_only_their_region(db, org, world, transport, on, test_mode):
    await go(db, utc(2026, 11, 16), org, dry_run=False, kind="digest")
    qaid = next(c for c in transport.calls if "rq.ne@example.invalid" in c["subject"])
    body = qaid["body"]
    assert "Syracuse" in body and "Boston" in body  # Northeast
    assert "Dallas" not in body and "Regional Nazim Maal" not in body  # Southwest
    assert "Hello Regional Qaid" in body


async def test_digest_has_role_titles_only_no_names_or_addresses(db, org, world, transport, on, test_mode):
    await go(db, utc(2026, 11, 16), org, dry_run=False, kind="digest")
    for call in transport.calls:
        for private in ("L One", "L Two", "L Three", "Cross Org", "Jane Doe", "Rob Qaid", "HYPERLINK", "l2@example.invalid"):
            assert private not in call["body"]


async def test_digest_is_once_per_week_per_recipient(db, org, world, transport, on, test_mode):
    await go(db, utc(2026, 11, 16), org, dry_run=False, kind="digest")
    again = await go(db, utc(2026, 11, 16), org, dry_run=False, kind="digest")
    assert again["digest"]["sent"] == 0 and again["digest"]["skipped_recent"] == 2


async def test_digest_skips_a_scope_with_nobody_outstanding(db, org, world, transport, on, test_mode):
    rep = await go(db, utc(2026, 11, 16), org, dry_run=True, kind="digest")
    assert rep["digest"]["would_send"] == 2 and rep["digest"]["skipped_nothing_outstanding"] == 0
    for row in (await db.execute(select(MkaComplianceExpected).where(MkaComplianceExpected.org_id == org.id))).scalars().all():
        if row.department == "tabligh" and row.level != "national":
            await db.delete(row)
    await db.commit()
    rep = await go(db, utc(2026, 11, 16), org, dry_run=True, kind="digest")
    assert rep["digest"]["skipped_nothing_outstanding"] >= 1


# --- logs ----------------------------------------------------------------------------------------------------


async def test_no_pii_in_logs_or_the_run_report(db, org, world, transport, on, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG, logger="src")  # our own loggers (the SQL debug logs are not ours)
    rep = await go(db, utc(2026, 11, 15), org, dry_run=False, kind="all")
    await go(db, utc(2026, 11, 16), org, dry_run=False, kind="digest")
    assert rep["reminder"]["sent"] == CANDIDATES
    ours = "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("src"))
    assert ours, "the run must log something for this test to mean anything"
    for private in ("example.invalid", "L One", "L Two", "Cross Org", "Jane Doe", "Rob Qaid"):
        assert private not in ours
        assert private not in repr(rep)
