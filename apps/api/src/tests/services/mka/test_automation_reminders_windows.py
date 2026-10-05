"""MKA fork: review H2, fair / resumable / non-timing-out reminder runs.

* a scheduled date opens a reminder WINDOW (``MKA_REMINDER_WINDOW_DAYS``): runs inside it continue with the people
  not yet reminded, a run outside every window does nothing;
* the people already reminded are dropped BEFORE the per-run cap is applied, the rest go least-recently-reminded
  first, so every run makes progress;
* a run stops at ``MKA_AUTOMATION_RUN_TIME_BUDGET_SECONDS`` and reports ``remaining`` / ``time_budget_hit``.

The transport is mocked; every address is ``example.invalid``."""

import time
from datetime import date

import pytest

from src.services.mka import automation_config as cfg
from src.services.mka import automation_reminders as rem
from src.services.mka import automation_send as send
from src.tests.routers.mka_compliance_world import expected
from src.tests.services.mka.test_automation_reminders import (  # noqa: F401
    CANDIDATES, TESTER, Transport, env, go, log_rows, on, test_mode, transport, utc, world,
)

BIG = 1400


# --- the window itself (pure) ----------------------------------------------------------------------------------


def test_a_scheduled_date_opens_a_window_of_the_configured_length():
    schedule = cfg.parse_schedule("11-08,11-15")
    start = lambda d, n: cfg.reminder_window_start(d, None, schedule, n)  # noqa: E731
    assert start(date(2026, 11, 8), 4) == date(2026, 11, 8)
    assert start(date(2026, 11, 11), 4) == date(2026, 11, 8)  # day 4 of the window
    assert start(date(2026, 11, 12), 4) is None  # outside every window
    assert start(date(2026, 11, 9), 1) is None  # a one-day window is the plain per-date schedule
    assert start(date(2026, 11, 16), 4) == date(2026, 11, 15)


def test_the_window_length_is_configurable_and_bounded(monkeypatch):
    monkeypatch.delenv("MKA_REMINDER_WINDOW_DAYS")  # the imported autouse env fixture pins one-day windows
    assert cfg.reminder_window_days() == 4
    monkeypatch.setenv("MKA_REMINDER_WINDOW_DAYS", "2")
    assert cfg.reminder_window_days() == 2
    for bad in ("0", "-3", "abc"):
        monkeypatch.setenv("MKA_REMINDER_WINDOW_DAYS", bad)
        assert cfg.reminder_window_days() == 4
    monkeypatch.setenv("MKA_REMINDER_WINDOW_DAYS", "30")
    assert cfg.reminder_window_days() == 7  # never longer than a week: windows must not overlap


def test_the_time_budget_default_is_90_seconds(monkeypatch):
    assert cfg.run_time_budget_seconds() == 90.0
    monkeypatch.setenv("MKA_AUTOMATION_RUN_TIME_BUDGET_SECONDS", "30")
    assert cfg.run_time_budget_seconds() == 30.0


# --- window days vs. non-window days -----------------------------------------------------------------------------


@pytest.fixture
def windowed(monkeypatch):
    monkeypatch.setenv("MKA_REMINDER_WINDOW_DAYS", "4")
    monkeypatch.setenv("MKA_REMINDER_SCHEDULE", "11-08")


async def test_a_window_day_continues_and_a_non_window_day_does_nothing(db, org, world, transport, on, test_mode, windowed, monkeypatch):  # noqa: F811
    monkeypatch.setenv("MKA_AUTOMATION_RUN_SEND_CAP", "5")
    first = await go(db, utc(2026, 11, 8), org, dry_run=False)  # the scheduled date
    assert first["reminder"]["sent"] == 5 and first["reminder"]["remaining"] == CANDIDATES - 5
    third = await go(db, utc(2026, 11, 10), org, dry_run=False)  # day 3 of the window: continues
    assert third["reminder"]["ran"] is True and third["reminder"]["sent"] == CANDIDATES - 5
    assert third["reminder"]["remaining"] == 0
    outside = await go(db, utc(2026, 11, 12), org, dry_run=False)  # the window closed
    assert outside["reminder"] == {"ran": False, "reason": "not_a_reminder_day"}
    assert len(await log_rows(db, org_id=org.id, kind="reminder")) == CANDIDATES


async def test_a_dry_run_inside_the_window_previews_only_who_is_left(db, org, world, transport, on, test_mode, windowed, monkeypatch):  # noqa: F811
    monkeypatch.setenv("MKA_AUTOMATION_RUN_SEND_CAP", "3")
    await go(db, utc(2026, 11, 8), org, dry_run=False)
    preview = await go(db, utc(2026, 11, 9), org, dry_run=True)
    assert preview["reminder"]["would_send"] == CANDIDATES - 3 and preview["reminder"]["skipped_recent"] == 3
    assert len(transport.calls) == 3  # a preview sends nothing


# --- 1,400 people, cap 400 -----------------------------------------------------------------------------------------


async def test_1400_people_with_a_cap_of_400_are_each_reminded_exactly_once_across_the_window(
    db, org, world, transport, on, test_mode, windowed, monkeypatch  # noqa: F811
):
    monkeypatch.setenv("MKA_AUTOMATION_RUN_SEND_CAP", "400")
    for i in range(BIG - CANDIDATES):  # the world already has CANDIDATES outstanding people
        db.add(expected(org.id, world.cycle.id, f"p{i:04d}@example.invalid", "tabligh", "local", "Albany",
                        "Northeast", "Nazim Tabligh", f"P {i}"))
    await db.commit()

    # 11-08 is a Sunday (ISO week 45), 11-09..11-11 are in week 46: the window straddles two ISO weeks
    days = [utc(2026, 11, 8), utc(2026, 11, 9), utc(2026, 11, 10), utc(2026, 11, 11)]
    reports = [(await go(db, day, org, dry_run=False))["reminder"] for day in days]
    assert [r["candidates"] for r in reports] == [BIG] * 4
    assert [r["sent"] for r in reports] == [400, 400, 400, 200]
    assert [r["remaining"] for r in reports] == [1000, 600, 200, 0]  # three runs leave 200: 1,400 needs a fourth
    assert [r["stopped"] for r in reports] == ["send_cap_reached"] * 3 + [None]

    rows = await log_rows(db, org_id=org.id, kind="reminder")
    assert len(rows) == BIG and len({r.intended_email for r in rows}) == BIG  # everybody once, nobody twice
    assert {r.dedupe_key.split(":")[2] for r in rows} == {"2026-W45"}  # one key week for the whole window


# --- fairness ------------------------------------------------------------------------------------------------------


async def test_people_not_yet_reminded_go_before_the_ones_reminded_last_time(db, org, world, transport, on, test_mode, monkeypatch):  # noqa: F811
    monkeypatch.setenv("MKA_REMINDER_SCHEDULE", "11-08,11-22")
    monkeypatch.setenv("MKA_AUTOMATION_RUN_SEND_CAP", "3")
    first = await go(db, utc(2026, 11, 8), org, dry_run=False)
    head = {r.intended_email for r in await log_rows(db, org_id=org.id, kind="reminder")}
    assert first["reminder"]["sent"] == 3 and len(head) == 3
    second = await go(db, utc(2026, 11, 22), org, dry_run=False)  # two weeks later, the same cap
    now_reminded = {r.intended_email for r in await log_rows(db, org_id=org.id, kind="reminder")}
    assert second["reminder"]["sent"] == 3
    assert len(now_reminded) == 6 and head < now_reminded  # three NEW people: the old alphabetical head did not hog the cap


async def test_when_everyone_has_been_reminded_the_oldest_reminder_goes_first(db, org, world, transport, on, test_mode, monkeypatch):  # noqa: F811
    monkeypatch.setenv("MKA_REMINDER_SCHEDULE", "11-08,11-15")
    monkeypatch.setenv("MKA_AUTOMATION_RUN_SEND_CAP", "400")
    await go(db, utc(2026, 11, 8), org, dry_run=False)  # everybody, week 45
    people = {r.intended_email: r for r in await log_rows(db, org_id=org.id, kind="reminder")}
    assert len(people) == CANDIDATES
    # make one person's last reminder much older, then run the next week with room for exactly one send
    oldest = sorted(people)[-1]  # alphabetically LAST: only a recency order can put it first
    people[oldest].created_at = people[oldest].created_at.replace(year=2025)
    await db.commit()
    monkeypatch.setenv("MKA_AUTOMATION_RUN_SEND_CAP", "1")
    await go(db, utc(2026, 11, 15), org, dry_run=False)
    fresh = [r for r in await log_rows(db, org_id=org.id, kind="reminder") if r.created_at.year == 2026 and r.dedupe_key.endswith(":" + oldest) and "W46" in r.dedupe_key]
    assert len(fresh) == 1


# --- time budget ---------------------------------------------------------------------------------------------------


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


async def test_the_run_stops_at_the_time_budget_and_the_next_run_finishes_the_job(db, org, world, on, test_mode, monkeypatch):  # noqa: F811
    clock = FakeClock()

    def slow_transport(to, subject, body, headers=None, sender_name=None):
        clock.t += 10.0  # every send "takes" ten seconds

    monkeypatch.setattr(send.email_utils, "send_email", slow_transport)
    monkeypatch.setattr(rem, "SendBudget", lambda: send.SendBudget(time_budget_seconds=30, delay_seconds=0, clock=clock))
    first = await go(db, utc(2026, 11, 15), org, dry_run=False)
    r = first["reminder"]
    assert r["sent"] == 3 and r["time_budget_hit"] is True and r["stopped"] == "time_budget_reached"
    assert r["remaining"] == CANDIDATES - 3
    total = first["_all"]
    # the budget is shared by every org: the other org's people are "remaining" too
    assert total["sent"] == 3 and total["remaining"] == sum(o["reminder"]["remaining"] for o in total["orgs"])
    assert total["remaining"] >= CANDIDATES - 3 and total["time_budget_hit"] is True
    assert not [x for x in await log_rows(db) if x.status == "queued"]  # a stopped run leaves no claimed-but-unsent rows

    clock.t = 5000.0  # the next call has its own fresh budget
    monkeypatch.setattr(rem, "SendBudget", lambda: send.SendBudget(time_budget_seconds=1000, delay_seconds=0, clock=clock))
    second = await go(db, utc(2026, 11, 15), org, dry_run=False)
    assert second["reminder"]["sent"] == CANDIDATES - 3 and second["reminder"]["time_budget_hit"] is False
    assert second["_all"]["remaining"] == 0 and second["_all"]["time_budget_hit"] is False


async def test_a_slow_transport_with_the_real_clock_cannot_overrun_the_budget(db, org, world, on, test_mode, monkeypatch):  # noqa: F811
    def slow(to, subject, body, headers=None, sender_name=None):
        time.sleep(0.3)

    monkeypatch.setattr(send.email_utils, "send_email", slow)
    monkeypatch.setenv("MKA_AUTOMATION_RUN_TIME_BUDGET_SECONDS", "1")
    started = time.monotonic()
    rep = await go(db, utc(2026, 11, 15), org, dry_run=False)
    elapsed = time.monotonic() - started
    r = rep["reminder"]
    assert 0 < r["sent"] < CANDIDATES and r["time_budget_hit"] is True and r["remaining"] == CANDIDATES - r["sent"]
    assert elapsed < 2.5  # budget 1 s plus at most the one send in flight, never the whole roster


async def test_a_dry_run_ignores_the_budget_and_reports_nothing_remaining(db, org, world, monkeypatch):  # noqa: F811
    monkeypatch.setenv("MKA_AUTOMATION_RUN_SEND_CAP", "1")
    monkeypatch.setenv("MKA_AUTOMATION_RUN_TIME_BUDGET_SECONDS", "0")
    rep = await go(db, utc(2026, 11, 15), org)
    assert rep["reminder"]["would_send"] == CANDIDATES and rep["reminder"]["remaining"] == 0
    assert rep["_all"]["time_budget_hit"] is False


# --- the same rules in REAL mode (the weekly cap and the cooldown are only enforced outside test mode) --------------


async def test_real_mode_window_reminds_each_person_once_across_two_iso_weeks(db, org, world, transport, on, windowed, monkeypatch):  # noqa: F811
    monkeypatch.setenv("MKA_AUTOMATION_RUN_SEND_CAP", "3")
    reports = [(await go(db, utc(2026, 11, d), org, dry_run=False))["reminder"] for d in (8, 9, 10, 11)]  # Sun .. Wed
    assert [r["sent"] for r in reports] == [3, 3, CANDIDATES - 6, 0]
    rows = await log_rows(db, org_id=org.id, kind="reminder")
    assert len(rows) == CANDIDATES and not any(r.test_mode for r in rows)
    assert {m["to"] for m in transport.calls if "example.invalid" in m["to"]} >= {r.intended_email for r in rows}


async def test_real_mode_weekly_cap_blocks_a_second_scheduled_reminder_in_the_same_iso_week(db, org, world, transport, on, monkeypatch):  # noqa: F811
    monkeypatch.setenv("MKA_REMINDER_SCHEDULE", "11-10,11-13")  # Tue and Fri of week 46, one-day windows
    monkeypatch.setenv("MKA_REMINDER_COOLDOWN_DAYS", "1")  # so only the WEEKLY rule can hold the second one back
    first = (await go(db, utc(2026, 11, 10), org, dry_run=False))["reminder"]
    second = (await go(db, utc(2026, 11, 13), org, dry_run=False))["reminder"]
    assert first["sent"] == CANDIDATES and second["sent"] == 0 and second["skipped_recent"] == CANDIDATES
    assert second["skipped_cooldown"] == 0


async def test_real_mode_cooldown_holds_back_a_second_reminder_across_the_week_boundary(db, org, world, transport, on, monkeypatch):  # noqa: F811
    monkeypatch.setenv("MKA_REMINDER_SCHEDULE", "11-15,11-16")  # Sunday (week 46) then Monday (week 47): a NEW week
    first = (await go(db, utc(2026, 11, 15), org, dry_run=False))["reminder"]
    monday = (await go(db, utc(2026, 11, 16), org, dry_run=False))["reminder"]
    assert first["sent"] == CANDIDATES
    assert monday["sent"] == 0 and monday["skipped_cooldown"] == CANDIDATES  # the weekly cap would allow it; the cooldown does not
    monkeypatch.setenv("MKA_REMINDER_COOLDOWN_DAYS", "1")
    later = (await go(db, utc(2026, 11, 16, 16), org, dry_run=False))["reminder"]  # 25 h after the first, new ISO week
    assert later["sent"] == CANDIDATES


# --- overdue reminders stop (round 2 L2) ---------------------------------------------------------------------------


@pytest.mark.parametrize("day, ran", [
    ((2026, 12, 8), True), ((2026, 12, 15), True), ((2026, 12, 22), True), ((2026, 12, 29), True),  # +7 .. +28 days
    ((2027, 1, 5), False), ((2027, 1, 12), False),  # +35, +42: past the 4 overdue weeks
])
async def test_overdue_reminders_stop_four_weeks_after_the_deadline(db, org, world, transport, on, day, ran):  # noqa: F811
    rep = await go(db, utc(*day), org, dry_run=False)
    assert rep["reminder"]["ran"] is ran
    if not ran:
        assert rep["reminder"]["reason"] == "overdue_period_over"


async def test_the_overdue_period_is_configurable_and_the_monday_digest_goes_on(db, org, world, transport, on, monkeypatch):  # noqa: F811
    monkeypatch.setenv("MKA_REMINDER_OVERDUE_WEEKS", "6")
    assert (await go(db, utc(2027, 1, 5), org, dry_run=False))["reminder"]["ran"] is True  # +5 weeks, allowed now
    monkeypatch.setenv("MKA_REMINDER_OVERDUE_WEEKS", "1")
    late = await go(db, utc(2027, 1, 4), org, dry_run=False, kind="all")  # a Monday, well past the overdue period
    assert late["reminder"] == {"ran": False, "reason": "not_a_reminder_day"}
    assert late["digest"]["ran"] is True and late["digest"]["sent"] >= 1  # supervisors still hear about it
