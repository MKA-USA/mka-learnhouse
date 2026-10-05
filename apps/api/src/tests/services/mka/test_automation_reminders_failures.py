"""MKA fork: review round 2, N1. A few permanently rejected addresses must not starve the whole roster.

Runs in REAL mode (no test recipient) with a mocked transport, so the weekly cap is enforced too."""

from datetime import datetime

import pytest

from src.db.mka_automation import MkaAutomationSendLog
from src.services.mka import automation_send as send
from src.tests.routers.mka_compliance_world import expected
from src.tests.services.mka.test_automation_reminders import (  # noqa: F401
    CANDIDATES, env, go, log_rows, on, transport, utc, world,
)

BAD = [f"a{i}@example.invalid" for i in range(5)]  # sort before every other address


@pytest.fixture
async def with_bad_addresses(db, org, world, monkeypatch):  # noqa: F811
    for email in BAD:
        db.add(expected(org.id, world.cycle.id, email, "tabligh", "local", "Albany", "Northeast", "Nazim Tabligh", "Bad"))
    await db.commit()
    monkeypatch.setenv("MKA_REMINDER_SCHEDULE", "11-08,11-22")
    monkeypatch.setenv("MKA_REMINDER_WINDOW_DAYS", "4")
    monkeypatch.setenv("MKA_REMINDER_COOLDOWN_DAYS", "1")


@pytest.fixture
def rejecting(monkeypatch):
    """A transport that rejects the BAD mailboxes and delivers everything else."""
    delivered = []
    state = {"outage_over": False}

    def transport(to, subject, body, headers=None, sender_name=None):  # noqa: F811
        if to in BAD and not state["outage_over"]:
            raise RuntimeError(f"recipient rejected: {to}")
        delivered.append(to)

    monkeypatch.setattr(send.email_utils, "send_email", transport)
    return type("T", (), {"delivered": delivered, "state": state})


async def test_five_permanently_failing_addresses_do_not_stop_later_runs(db, org, with_bad_addresses, on, rejecting):  # noqa: F811
    others = CANDIDATES
    day1 = (await go(db, utc(2026, 11, 8), org, dry_run=False))["reminder"]
    # nothing is known about the bad addresses yet: they come first and trip the consecutive-failure stop
    assert day1["sent"] == 0 and day1["failed"] == 5 and day1["stopped"] == "too_many_consecutive_failures"

    day2 = (await go(db, utc(2026, 11, 9), org, dry_run=False))["reminder"]
    # now they are known to be failing: everybody else is reminded FIRST
    assert day2["sent"] == others and set(rejecting.delivered).isdisjoint(BAD) and len(rejecting.delivered) == others

    await go(db, utc(2026, 11, 10), org, dry_run=False)  # the third failure each
    day4 = (await go(db, utc(2026, 11, 11), org, dry_run=False))["reminder"]
    assert day4["quarantined"] == 5 and day4["failed"] == 0 and day4["stopped"] is None and day4["remaining"] == 0
    sent_rows = await log_rows(db, status="sent")
    assert len({(r.org_id, r.intended_email) for r in sent_rows}) == len(sent_rows)  # nobody reminded twice


async def test_the_quarantine_ends_and_the_next_window_still_sends(db, org, with_bad_addresses, on, rejecting):  # noqa: F811
    for day in (8, 9, 10, 11):
        await go(db, utc(2026, 11, day), org, dry_run=False)
    rejecting.state["outage_over"] = True  # the provider accepts the addresses again
    nxt = (await go(db, utc(2026, 11, 22), org, dry_run=False))["reminder"]
    assert nxt["quarantined"] == 0 and nxt["failed"] == 0
    assert nxt["sent"] == CANDIDATES + 5  # everybody, the formerly bad addresses included


async def test_the_consecutive_failure_stop_never_counts_quarantined_addresses(db, org, with_bad_addresses, on, rejecting, monkeypatch):  # noqa: F811
    monkeypatch.setenv("MKA_AUTOMATION_MAX_CONSECUTIVE_FAILURES", "2")
    now = utc(2026, 11, 8)
    for email in BAD:  # already at the limit
        db.add(MkaAutomationSendLog(org_id=org.id, kind="reminder", dedupe_key=f"reminder:2026-W44:{email}", to_email=email,
                                    intended_email=email, subject="s", status="failed", error="X [fails=3]",
                                    created_at=datetime(2026, 11, 5, 12, 0)))
    await db.commit()
    rep = (await go(db, now, org, dry_run=False))["reminder"]
    assert rep["quarantined"] == 5 and rep["failed"] == 0 and rep["stopped"] is None and rep["sent"] == CANDIDATES


async def test_failures_are_counted_per_attempt_not_per_row(db, org, with_bad_addresses, on, rejecting):  # noqa: F811
    await go(db, utc(2026, 11, 8), org, dry_run=False)
    await go(db, utc(2026, 11, 9), org, dry_run=False)
    counts = await send.failing_addresses(db, org.id, test_mode=False, now=utc(2026, 11, 9))
    assert {counts[e] for e in BAD} == {2}  # one row each, two failed attempts


async def test_the_digest_names_the_failing_mailbox_for_the_supervisor(db, org, world, on, transport, monkeypatch):  # noqa: F811
    monkeypatch.setenv("MKA_REMINDER_WINDOW_DAYS", "1")
    db.add(MkaAutomationSendLog(org_id=org.id, kind="reminder", dedupe_key="reminder:2026-W45:l2@example.invalid",
                                to_email="l2@example.invalid", intended_email="l2@example.invalid", subject="s",
                                status="failed", error="X [fails=3]", created_at=datetime(2026, 11, 12, 12, 0)))
    await db.commit()
    rep = await go(db, utc(2026, 11, 16), org, dry_run=False, kind="digest")  # a Monday
    assert rep["digest"]["sent"] >= 1
    assert any("(address failing)" in call["body"] for call in transport.calls)


async def test_the_run_totals_report_newly_quarantined_and_the_last_window_day(db, org, with_bad_addresses, on, rejecting):  # noqa: F811
    newly = []
    last_flags = []
    for day in (8, 9, 10, 11):
        rep = (await go(db, utc(2026, 11, day), org, dry_run=False))["_all"]
        newly.append(rep["newly_quarantined"])
        last_flags.append(rep["last_window_day"])
    assert newly == [0, 0, 5, 0]  # the third failed attempt of each of the 5 addresses, reported once
    assert last_flags == [False, False, False, True]


async def test_a_disabled_run_says_why_in_the_totals(db, org, world, monkeypatch):  # noqa: F811
    monkeypatch.setenv("MKA_AUTOMATION_ENABLED", "true")
    monkeypatch.setenv("MKA_REMINDERS_ENABLED", "true")
    monkeypatch.setenv("MKA_AUTOMATION_TEST_RECIPIENT", "not an address, x@y.invalid")
    rep = (await go(db, utc(2026, 11, 15), org, dry_run=False))["_all"]
    assert rep["sent"] == 0 and rep["disabled_reason"] == "invalid_test_recipient"
