"""MKA fork: regression tests for the independent review of the combined automation branch (H1, M3, M4).

Each test here FAILED before its fix (the fix commits say which). Fixtures come from the seam C router tests; the
transport is mocked and every address is ``example.invalid``."""

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlmodel import select

from src.db.mka_automation import MkaAutomationEvent, MkaAutomationSendLog
from src.db.mka_compliance import MkaComplianceCycle, MkaComplianceCycleCourse, MkaComplianceExpected
from src.services.mka import automation_reminders as rem
from src.tests.routers.test_mka_automation_reminders_router import (  # noqa: F401
    BASE, GENERAL, MON, TABLIGH, TESTER, client_for, count, env, on, q, real, transport, world,
)


async def add_cycle(db, org, label, starts, deadline, course_id=102, course_uuid="course_tabligh"):
    cycle = MkaComplianceCycle(org_id=org.id, label=label, starts_on=starts, deadline_on=deadline)
    db.add(cycle)
    await db.commit()
    db.add(MkaComplianceCycleCourse(org_id=org.id, cycle_id=cycle.id, course_id=course_id, course_uuid=course_uuid,
                                    kind="department", department="tabligh", signoff_assignment_id=5002))
    db.add(MkaComplianceExpected(org_id=org.id, cycle_id=cycle.id, email="old.officeholder@example.invalid",
                                 department="tabligh", level="local", majlis="Albany", region="Northeast",
                                 role_title="Nazim Tabligh", person_name="Old Holder"))
    await db.commit()
    return cycle


# ---------------------------------------------------------------------------------------------------------
# H1: manual Remind only acts on the CURRENT, already-started cycle
# ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("dry", ["true", "false"])
async def test_last_years_cycle_cannot_be_reminded(db, org, world, transport, on, dry):  # noqa: F811
    past = await add_cycle(db, org, "2025-26", date(2025, 11, 1), date(2025, 12, 1))
    async with client_for(db, 1) as c:
        r = await c.post(TABLIGH, params=q(org, dry_run=dry, cycle_id=past.id))
    assert r.status_code == 409 and "current cycle" in r.json()["detail"]
    assert transport.calls == [] and await count(db, MkaAutomationSendLog) == 0 and await count(db, MkaAutomationEvent) == 0


@pytest.mark.parametrize("dry", ["true", "false"])
async def test_an_early_imported_future_cycle_cannot_be_reminded(db, org, world, transport, on, dry):  # noqa: F811
    future = await add_cycle(db, org, "2027-28", date(2027, 11, 1), date(2027, 12, 1))
    async with client_for(db, 1) as c:
        r = await c.post(TABLIGH, params=q(org, dry_run=dry, cycle_id=future.id))
    assert r.status_code == 409
    assert transport.calls == [] and await count(db, MkaAutomationSendLog) == 0 and await count(db, MkaAutomationEvent) == 0


async def test_the_current_cycle_still_works_with_or_without_an_explicit_id(db, org, world, transport, on):  # noqa: F811
    await add_cycle(db, org, "2025-26", date(2025, 11, 1), date(2025, 12, 1))  # an old cycle must not shadow it
    async with client_for(db, 1) as c:
        implicit = await c.post(TABLIGH, params=q(org))
        explicit = await c.post(TABLIGH, params=q(org, cycle_id=world.cycle.id))
    assert implicit.status_code == explicit.status_code == 200
    assert implicit.json()["would_send"] == explicit.json()["would_send"] == 4


# ---------------------------------------------------------------------------------------------------------
# M3: manual reminders have their own key space and never spend the scheduled weekly slot
# ---------------------------------------------------------------------------------------------------------


@pytest.fixture
def real_mode(monkeypatch):
    monkeypatch.delenv("MKA_AUTOMATION_TEST_RECIPIENT")  # real mode: the weekly cap counts real rows
    monkeypatch.setenv("MKA_REMINDER_SCHEDULE", "11-16")  # today (MON) is a scheduled reminder day


async def test_scheduled_then_manual_on_the_same_day_is_one_email_per_person(db, org, world, transport, on, real_mode):  # noqa: F811
    report = await rem.run_all(db, dry_run=False, kind="reminder", now=MON)
    mine = next(o for o in report["orgs"] if o["org_id"] == org.id)["reminder"]
    assert mine["sent"] == 8
    async with client_for(db, 1) as c:
        preview = await c.post(TABLIGH, params=q(org))
        assert preview.json()["would_send"] == 0 and preview.json()["skipped_cooldown"] == 4
        assert preview.json()["cooldown_days"] == 3
        manual = await real(c, TABLIGH, org)
    assert manual.json()["sent"] == 0 and manual.json()["skipped_recent"] == 4
    assert len([t for t in transport.calls if "l2@example.invalid" in t["to"]]) == 1


async def test_manual_then_scheduled_the_same_day_skips_the_manual_recipients_but_not_the_rest(db, org, world, transport, on, real_mode):  # noqa: F811
    async with client_for(db, 1) as c:
        assert (await real(c, TABLIGH, org)).json()["sent"] == 4
    report = await rem.run_all(db, dry_run=False, kind="reminder", now=MON)
    mine = next(o for o in report["orgs"] if o["org_id"] == org.id)["reminder"]
    assert mine["sent"] == 4 and mine["skipped_cooldown"] == 4 and mine["candidates"] == 8


async def test_a_manual_recipient_is_not_mailed_again_by_the_scheduled_run_in_the_same_iso_week(db, org, world, transport, on, real_mode, monkeypatch):  # noqa: F811
    """Round 5 (spec 1.5 / 2C): the weekly cap counts manual sends too, so a manual remind at day 0 + 1 h means the
    cron never mails that person again this ISO week, not even on the last window day. Everybody else gets exactly one
    scheduled reminder."""
    monkeypatch.setenv("MKA_REMINDER_WINDOW_DAYS", "4")  # window 11-16 .. 11-19, all in ISO week 47
    monkeypatch.setattr(rem, "current_instant", lambda: MON + timedelta(hours=1))
    async with client_for(db, 1) as c:
        assert (await real(c, TABLIGH, org)).json()["sent"] == 4
    per_day = []
    for offset in (timedelta(hours=2), timedelta(days=1), timedelta(days=2), timedelta(days=3)):
        rep = await rem.run_all(db, dry_run=False, kind="reminder", now=MON + offset)
        per_day.append(next(o for o in rep["orgs"] if o["org_id"] == org.id)["reminder"]["sent"])
    assert per_day == [4, 0, 0, 0]
    rows = [r for r in (await db.execute(select(MkaAutomationSendLog))).scalars().all() if r.org_id == org.id]
    per_person = {}
    for r in rows:
        per_person[r.intended_email] = per_person.get(r.intended_email, 0) + 1
    assert sum(per_person.values()) == 8 and set(per_person.values()) == {1}  # one email per person for the week


async def test_a_manual_remind_on_the_last_day_itself_still_blocks_the_scheduled_run(db, org, world, transport, on, real_mode, monkeypatch):  # noqa: F811
    """Round 4 H1: only manual reminders sent BEFORE local midnight of the last day are lifted. A manual Remind on the
    last day (+1 h) followed by the cron (+2 h) must not mail the same people twice 1 h apart."""
    monkeypatch.setenv("MKA_REMINDER_WINDOW_DAYS", "4")
    last_day = MON + timedelta(days=3)
    monkeypatch.setattr(rem, "current_instant", lambda: last_day + timedelta(hours=1))
    async with client_for(db, 1) as c:
        assert (await real(c, TABLIGH, org)).json()["sent"] == 4
    manual = {r.intended_email for r in (await db.execute(select(MkaAutomationSendLog))).scalars().all()
              if r.org_id == org.id and r.dedupe_key.startswith("manual:")}
    rep = await rem.run_all(db, dry_run=False, kind="reminder", now=last_day + timedelta(hours=2))
    mine = next(o for o in rep["orgs"] if o["org_id"] == org.id)["reminder"]
    assert mine["sent"] == 4 and mine["skipped_cooldown"] == 4  # only the 4 who did not get the manual mail
    scheduled = {r.intended_email for r in (await db.execute(select(MkaAutomationSendLog))).scalars().all()
                 if r.org_id == org.id and r.dedupe_key.startswith("reminder:")}
    assert not (scheduled & manual)


async def test_the_last_day_rule_does_not_lift_the_scheduled_cooldown_or_the_weekly_cap(db, org, world, transport, on, real_mode, monkeypatch):  # noqa: F811
    monkeypatch.setenv("MKA_REMINDER_WINDOW_DAYS", "4")
    await rem.run_all(db, dry_run=False, kind="reminder", now=MON + timedelta(hours=2))  # everybody, scheduled
    last = await rem.run_all(db, dry_run=False, kind="reminder", now=MON + timedelta(days=3))  # last window day
    assert next(o for o in last["orgs"] if o["org_id"] == org.id)["reminder"]["sent"] == 0  # already reminded this window


async def test_the_last_day_rule_reaches_but_does_not_lift_the_weekly_cap(db, org, world, transport, on, real_mode, monkeypatch):  # noqa: F811
    """A manual remind on day 0 is old enough for the last-day lift, so selection DOES pick those people again on the
    last day. It is the weekly cap (one reminder per person per ISO week, manual included) that stops the second
    email: the send is refused as ``capped`` and nothing goes out."""
    monkeypatch.setenv("MKA_REMINDER_WINDOW_DAYS", "4")
    monkeypatch.setattr(rem, "current_instant", lambda: MON + timedelta(hours=1))
    async with client_for(db, 1) as c:
        assert (await real(c, TABLIGH, org)).json()["sent"] == 4
    manual = {r.intended_email for r in (await db.execute(select(MkaAutomationSendLog))).scalars().all()
              if r.org_id == org.id and r.dedupe_key.startswith("manual:") and r.status == "sent"}
    assert len(manual) == 4
    last_day = MON + timedelta(days=3)
    sel = await rem.select_pending(
        db, org_id=org.id, people={e: None for e in manual}, today=rem.cycle_today(last_day), now=last_day,
        window_start=date(2026, 11, 16),
    )
    assert set(sel.pending) == manual and sel.cooled == 0  # the cooldown lift let them through to the cap check
    before = len(transport.calls)
    rep = await rem.run_all(db, dry_run=False, kind="reminder", now=last_day)
    block = next(o for o in rep["orgs"] if o["org_id"] == org.id)["reminder"]
    assert block["sent"] == 4 and block["skipped_recent"] == 4  # the other 4 people are mailed; the manual ones are capped
    scheduled = {r.intended_email for r in (await db.execute(select(MkaAutomationSendLog))).scalars().all()
                 if r.org_id == org.id and r.dedupe_key.startswith("reminder:")}
    assert len(scheduled) == 4 and not (scheduled & manual)


async def test_a_manual_remind_late_on_the_day_before_still_blocks_the_next_days_cron(db, org, world, transport, on, real_mode, monkeypatch):  # noqa: F811
    """Round 5 blocking fix: manual at 04:30 UTC (23:30 EST) the evening before the last window day, then the
    last-day cron at 15:00 UTC. The old rule lifted it (sent before local midnight) and mailed the same people twice
    in hours; now the recent manual mail keeps blocking through the cooldown, not the weekly cap alone."""
    monkeypatch.setenv("MKA_REMINDER_WINDOW_DAYS", "4")
    manual_at = MON + timedelta(days=2, hours=13, minutes=30)  # Thu 04:30 UTC = Wed 23:30 EST
    monkeypatch.setattr(rem, "current_instant", lambda: manual_at)
    async with client_for(db, 1) as c:
        assert (await real(c, TABLIGH, org)).json()["sent"] == 4
    cron = MON + timedelta(days=3)  # Thu 15:00 UTC: the last window day
    rep = await rem.run_all(db, dry_run=False, kind="reminder", now=cron)
    block = next(o for o in rep["orgs"] if o["org_id"] == org.id)["reminder"]
    assert block["last_window_day"] is True
    assert block["skipped_cooldown"] == 4  # held by the cooldown itself, so the lift did not apply
    rows = [r for r in (await db.execute(select(MkaAutomationSendLog))).scalars().all() if r.org_id == org.id]
    per_person = {}
    for r in rows:
        per_person[r.intended_email] = per_person.get(r.intended_email, 0) + 1
    assert set(per_person.values()) == {1}


@pytest.mark.parametrize("manual_at, lifted", [
    (datetime(2026, 11, 19, 4, 59, tzinfo=timezone.utc), True),   # 23:59 EST the night before: before local midnight
    (datetime(2026, 11, 19, 5, 1, tzinfo=timezone.utc), False),   # 00:01 EST on the last day itself: still blocks
])
async def test_the_last_day_lift_boundary_is_local_midnight_in_utc(db, org, world, transport, on, real_mode, monkeypatch, manual_at, lifted):  # noqa: F811
    """With a 1-day cooldown the lift boundary is local midnight (05:00 UTC in November EST) of the last day."""
    monkeypatch.setenv("MKA_REMINDER_WINDOW_DAYS", "4")
    monkeypatch.setenv("MKA_REMINDER_COOLDOWN_DAYS", "1")
    monkeypatch.setattr(rem, "current_instant", lambda: manual_at)
    async with client_for(db, 1) as c:
        assert (await real(c, TABLIGH, org)).json()["sent"] == 4
    manual = {r.intended_email for r in (await db.execute(select(MkaAutomationSendLog))).scalars().all() if r.org_id == org.id}
    now = datetime(2026, 11, 19, 15, 0, tzinfo=timezone.utc)
    sel = await rem.select_pending(
        db, org_id=org.id, people={e: None for e in manual}, today=rem.cycle_today(now), now=now,
        window_start=date(2026, 11, 16),
    )
    assert (set(sel.pending) == manual) is lifted and (sel.cooled == 0) is lifted


async def test_the_cooldown_is_configurable(db, org, world, transport, on, real_mode, monkeypatch):  # noqa: F811
    monkeypatch.setenv("MKA_REMINDER_COOLDOWN_DAYS", "1")
    async with client_for(db, 1) as c:
        await real(c, TABLIGH, org)
    report = await rem.run_all(db, dry_run=False, kind="reminder", now=MON + timedelta(days=1))
    assert next(o for o in report["orgs"] if o["org_id"] == org.id)["reminder"]["skipped_cooldown"] == 0


async def test_manual_keys_are_per_course_and_per_week(db, org, world, transport, on, real_mode, monkeypatch):  # noqa: F811
    async with client_for(db, 1) as c:
        t1 = await real(c, TABLIGH, org)
        # same week, past the cooldown: the weekly cap (round 5) stops the 4 already mailed, the other 4 still go out
        monkeypatch.setattr(rem, "current_instant", lambda: MON + timedelta(days=4))
        g1 = await real(c, GENERAL, org)
        monkeypatch.setattr(rem, "current_instant", lambda: MON + timedelta(days=8))  # next ISO week: a fresh allowance
        g2 = await real(c, GENERAL, org)
    assert t1.json()["sent"] == 4 and g1.json()["sent"] == 4 and g2.json()["sent"] == 8
    keys = sorted(r.dedupe_key for r in (await db.execute(select(MkaAutomationSendLog))).scalars().all())
    assert all(k.startswith("manual:") for k in keys) and len(keys) == 16
    assert sum(":2026-W47:" in k for k in keys) == 8 and sum(":2026-W48:" in k for k in keys) == 8  # 4+4, then 8 afresh
    assert len({k.split(":")[1] for k in keys}) == 2  # both courses have their own key space


async def test_a_second_manual_remind_of_the_same_course_in_the_same_week_reaches_nobody_twice(
    db, org, world, transport, on, real_mode, monkeypatch  # noqa: F811
):
    async with client_for(db, 1) as c:
        assert (await real(c, TABLIGH, org)).json()["sent"] == 4
        monkeypatch.setattr(rem, "current_instant", lambda: MON + timedelta(hours=25))  # past the 24 h course limit
        later = await real(c, TABLIGH, org)
    assert later.status_code == 200 and later.json()["sent"] == 0 and later.json()["skipped_recent"] == 4
    assert len(transport.calls) == 4


async def test_manual_rows_count_against_the_weekly_cap(db, org, world, transport, on, real_mode):  # noqa: F811
    from src.services.mka import automation_send as send

    async with client_for(db, 1) as c:
        await real(c, GENERAL, org)
    week = send.current_iso_week(MON)
    assert await send.reminders_this_week(db, org.id, "l2@example.invalid", week) == 1
    assert await send.reminded_this_week(db, org.id, "l2@example.invalid", week)


# ---------------------------------------------------------------------------------------------------------
# H2 (e): the manual button has the same budget semantics and says what is left
# ---------------------------------------------------------------------------------------------------------


async def test_the_button_stops_at_the_budget_reports_what_is_left_and_can_be_run_again(
    db, org, world, transport, on, monkeypatch  # noqa: F811
):
    from src.services.mka import automation_send as send

    monkeypatch.setattr(rem, "SendBudget", lambda: send.SendBudget(max_sends=3, delay_seconds=0))
    async with client_for(db, 1) as c:
        first = await real(c, GENERAL, org)
        assert first.status_code == 200
        a = first.json()
        assert (a["sent"], a["remaining"], a["time_budget_hit"], a["stopped"]) == (3, 5, False, "send_cap_reached")
        # a partial run does not hold the 24 h slot: run it again for the rest, nobody is mailed twice
        second = await real(c, GENERAL, org)
        b = second.json()
        assert second.status_code == 200 and (b["sent"], b["remaining"], b["skipped_recent"]) == (3, 2, 3)
        third = await real(c, GENERAL, org)
        assert third.status_code == 200 and third.json()["sent"] == 2 and third.json()["remaining"] == 0
        done = await real(c, GENERAL, org)  # a COMPLETE run takes the 24 h slot
        assert done.status_code == 429
    to = [call["to"] for call in transport.calls]
    assert len(to) == 8 and set(to) == {TESTER}
    keys = [r.dedupe_key for r in (await db.execute(select(MkaAutomationSendLog))).scalars().all()]
    assert len(keys) == len(set(keys)) == 8


async def test_the_button_stops_at_the_time_budget(db, org, world, transport, on, monkeypatch):  # noqa: F811
    from src.services.mka import automation_send as send

    ticks = iter(range(0, 1000, 40))  # the clock jumps 40 s per look: the 90 s budget is gone after two sends
    monkeypatch.setattr(rem, "SendBudget", lambda: send.SendBudget(delay_seconds=0, clock=lambda: float(next(ticks))))
    async with client_for(db, 1) as c:
        r = await real(c, GENERAL, org)
    body = r.json()
    assert body["time_budget_hit"] is True and body["stopped"] == "time_budget_reached"
    assert 0 < body["sent"] < 8 and body["remaining"] == 8 - body["sent"]


# ---------------------------------------------------------------------------------------------------------
# M4: the real send is tied to the preview
# ---------------------------------------------------------------------------------------------------------


async def preview(c, org, path=TABLIGH):
    r = await c.post(path, params=q(org))
    assert r.status_code == 200
    return r.json()


async def test_the_preview_returns_a_stable_digest_and_a_real_send_with_it_goes_through(db, org, world, transport, on):  # noqa: F811
    async with client_for(db, 1) as c:
        p1, p2 = await preview(c, org), await preview(c, org)
        assert p1["preview_digest"] == p2["preview_digest"] and len(p1["preview_digest"]) >= 32
        assert "example.invalid" not in p1["preview_digest"]
        sent = await c.post(TABLIGH, params=q(org, dry_run="false", preview_digest=p1["preview_digest"]))
    assert sent.status_code == 200 and sent.json()["sent"] == p1["would_send"] == 4
    assert sent.json()["preview_digest"] is None


async def test_a_real_send_without_a_digest_is_refused_and_sends_nothing(db, org, world, transport, on):  # noqa: F811
    async with client_for(db, 1) as c:
        r = await c.post(TABLIGH, params=q(org, dry_run="false"))
    assert r.status_code == 422
    assert transport.calls == [] and await count(db, MkaAutomationSendLog) == 0 and await count(db, MkaAutomationEvent) == 0


async def test_a_person_becoming_eligible_between_preview_and_send_is_never_mailed(db, org, world, transport, on):  # noqa: F811
    async with client_for(db, 1) as c:
        shown = await preview(c, org)
        db.add(MkaComplianceExpected(org_id=org.id, cycle_id=world.cycle.id, email="late.joiner@example.invalid",
                                     department="tabligh", level="local", majlis="Albany", region="Northeast",
                                     role_title="Nazim Tabligh", person_name="Late Joiner"))
        await db.commit()
        refused = await c.post(TABLIGH, params=q(org, dry_run="false", preview_digest=shown["preview_digest"]))
        assert refused.status_code == 409 and "changed since the preview" in refused.json()["detail"]
        assert transport.calls == [] and await count(db, MkaAutomationSendLog) == 0
        assert await count(db, MkaAutomationEvent) == 0  # the refusal did not take the 24 h slot
        again = await preview(c, org)  # review the new list, confirm it
        assert again["would_send"] == shown["would_send"] + 1 and again["preview_digest"] != shown["preview_digest"]
        ok = await c.post(TABLIGH, params=q(org, dry_run="false", preview_digest=again["preview_digest"]))
    assert ok.status_code == 200 and ok.json()["sent"] == 5


async def test_a_swapped_person_with_the_same_head_count_is_refused_too(db, org, world, transport, on):  # noqa: F811
    async with client_for(db, 1) as c:
        shown = await preview(c, org)
        row = (await db.execute(select(MkaComplianceExpected).where(MkaComplianceExpected.email == "ghost1@example.invalid"))).scalars().first()
        row.email = "someone.else@example.invalid"  # same number of people, different person
        await db.commit()
        r = await c.post(TABLIGH, params=q(org, dry_run="false", preview_digest=shown["preview_digest"]))
    assert r.status_code == 409 and transport.calls == []


async def test_fewer_people_than_previewed_is_also_a_changed_list(db, org, world, transport, on):  # noqa: F811
    async with client_for(db, 1) as c:
        shown = await preview(c, org)
        row = (await db.execute(select(MkaComplianceExpected).where(MkaComplianceExpected.email == "ghost1@example.invalid"))).scalars().first()
        await db.delete(row)
        await db.commit()
        r = await c.post(TABLIGH, params=q(org, dry_run="false", preview_digest=shown["preview_digest"]))
    assert r.status_code == 409 and transport.calls == []


async def test_a_digest_is_bound_to_its_course_and_garbage_is_refused(db, org, world, transport, on):  # noqa: F811
    async with client_for(db, 1) as c:
        tabligh = await preview(c, org)
        general = await preview(c, org, GENERAL)
        assert tabligh["preview_digest"] != general["preview_digest"]
        wrong_course = await c.post(GENERAL, params=q(org, dry_run="false", preview_digest=tabligh["preview_digest"]))
        garbage = await c.post(GENERAL, params=q(org, dry_run="false", preview_digest="0" * 32))
        too_long = await c.post(GENERAL, params=q(org, dry_run="false", preview_digest="x" * 500))
    assert wrong_course.status_code == garbage.status_code == 409 and too_long.status_code == 422
    assert transport.calls == []


# ---------------------------------------------------------------------------------------------------------
# M1: a failed auto-enrolment is visible on /status
# ---------------------------------------------------------------------------------------------------------

STATUS = "/api/v1/mka/automation/status"


async def test_status_counts_recent_autoenrol_errors_for_this_org_only(db, org, other_org, world, transport):  # noqa: F811
    from datetime import datetime

    def err(org_id, when, note="enrol_failed:ProgrammingError", status="error", event="autoenroll", did=[0]):
        did[0] += 1
        return MkaAutomationEvent(org_id=org_id, delivery_id=f"autoenroll:{did[0]}", event=event, status=status,
                                  note=note, received_at=when)

    now = datetime.utcnow()
    db.add_all([
        err(org.id, now), err(org.id, now - timedelta(days=2)),
        err(org.id, now - timedelta(days=30)),  # too old to matter
        err(other_org.id, now),  # another org's problem
        err(org.id, now, status="processed", note="enrolled:2"),  # a success
        err(org.id, now, event="manual_remind"),  # not an auto-enrol event
    ])
    await db.commit()
    async with client_for(db, 1) as c:
        r = await c.get(STATUS, params=q(org))
    assert r.status_code == 200
    assert r.json()["autoenroll"] == {"errors_recent": 2, "window_days": 7}
    assert "ProgrammingError" not in r.text  # counts only


async def test_status_shows_zero_enrol_errors_when_nothing_failed(db, org, world, transport):  # noqa: F811
    async with client_for(db, 1) as c:
        r = await c.get(STATUS, params=q(org))
    assert r.json()["autoenroll"]["errors_recent"] == 0


# ---------------------------------------------------------------------------------------------------------
# M2: stale queued claims are visible on /status
# ---------------------------------------------------------------------------------------------------------


async def test_status_lists_claims_stuck_in_queued_past_the_lease(db, org, other_org, world, transport):  # noqa: F811
    from datetime import datetime

    def row(org_id, key, status, age_minutes):
        return MkaAutomationSendLog(
            org_id=org_id, kind="receipt", dedupe_key=key, to_email="a@example.invalid", intended_email="a@example.invalid",
            subject="s", status=status, created_at=datetime.utcnow() - timedelta(minutes=age_minutes),
        )

    db.add_all([
        row(org.id, "k1", "queued", 60), row(org.id, "k2", "queued", 20),  # past the 15 minute lease: stuck
        row(org.id, "k3", "queued", 2),  # in flight
        row(org.id, "k4", "sent", 600),  # finished
        row(other_org.id, "k5", "queued", 600),  # another org
    ])
    await db.commit()
    async with client_for(db, 1) as c:
        r = await c.get(STATUS, params=q(org))
    assert r.json()["send_log"]["stale_queued"] == 2


# ---------------------------------------------------------------------------------------------------------
# round 2 test gaps
# ---------------------------------------------------------------------------------------------------------


@pytest.fixture
def before_the_cycle(monkeypatch):
    """The likely state until Nov 1: the org's ONLY cycle (2026-11-01 ..) has not started yet."""
    from datetime import datetime, timezone

    from src.services.mka import compliance as svc

    before = datetime(2026, 10, 20, 15, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(svc, "today", lambda: "2026-10-20")
    monkeypatch.setattr(rem, "current_instant", lambda: before)
    monkeypatch.setenv("MKA_AUTOMATION_CRON_SECRET", "s3cret-for-tests-only")
    monkeypatch.setenv("MKA_REMINDER_SCHEDULE", "10-20")  # even a scheduled day must not send for a cycle not started
    return before


async def test_an_org_whose_only_cycle_has_not_started_behaves_sanely(db, org, world, transport, on, before_the_cycle):  # noqa: F811
    from src.tests.routers.test_mka_automation_reminders_router import RUN, anon

    async with client_for(db, 1) as c:
        scope = await c.get(f"{BASE}/scope", params=q(org))
        overview = await c.get(f"{BASE}/overview", params=q(org))
        dry = await c.post(TABLIGH, params=q(org))
        real_send = await c.post(TABLIGH, params=q(org, dry_run="false", preview_digest="0" * 40))
    assert scope.status_code == 200 and scope.json()["cycle"]["label"] == "2026-27"
    assert overview.status_code == 200
    for r in (dry, real_send):
        assert r.status_code == 409 and "not started" in r.json()["detail"] and "current cycle" in r.json()["detail"]
    async with anon(db) as c:
        run = await c.post(RUN, params={"dry_run": "false"}, headers={"X-MKA-Cron-Secret": "s3cret-for-tests-only"})
        sweep = await c.post("/api/v1/mka/automation/receipts/sweep", params={"dry_run": "false"},
                             headers={"X-MKA-Cron-Secret": "s3cret-for-tests-only"})
    assert run.status_code == 200 and sweep.status_code == 200
    mine = next(o for o in run.json()["orgs"] if o["org_id"] == org.id)
    assert mine["reminder"] == {"ran": False, "reason": "cycle_not_started"} and run.json()["sent"] == 0
    assert transport.calls == [] and await count(db, MkaAutomationSendLog) == 0 and await count(db, MkaAutomationEvent) == 0


async def test_a_preview_is_bound_to_the_day_a_real_change_of_day_refuses_the_send(db, org, world, transport, on, monkeypatch):  # noqa: F811
    from src.services.mka import compliance as svc

    async with client_for(db, 1) as c:
        shown = await preview(c, org)  # MON 2026-11-16
        tomorrow = MON + timedelta(days=1)
        monkeypatch.setattr(svc, "today", lambda: "2026-11-17")
        monkeypatch.setattr(rem, "current_instant", lambda: tomorrow)
        stale = await c.post(TABLIGH, params=q(org, dry_run="false", preview_digest=shown["preview_digest"]))
        fresh = await preview(c, org)  # the same list, but a new day: a new digest
        assert stale.status_code == 409 and "changed since the preview" in stale.json()["detail"]
        assert fresh["would_send"] == shown["would_send"] and fresh["preview_digest"] != shown["preview_digest"]
        ok = await c.post(TABLIGH, params=q(org, dry_run="false", preview_digest=fresh["preview_digest"]))
    assert ok.status_code == 200 and ok.json()["sent"] == 4 and len(transport.calls) == 4
