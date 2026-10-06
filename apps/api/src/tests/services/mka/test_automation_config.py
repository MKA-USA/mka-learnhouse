"""MKA fork: automation config is read from the environment at CALL time and fails safe."""

import logging
from datetime import date

import pytest

from src.services.mka import automation_config as cfg

ENV = (
    "MKA_AUTOMATION_ENABLED", "MKA_AUTOENROLL_ENABLED", "MKA_RECEIPTS_ENABLED", "MKA_REMINDERS_ENABLED",
    "MKA_AUTOMATION_TEST_RECIPIENT", "MKA_AUTOMATION_WEBHOOK_SECRET", "MKA_AUTOMATION_CRON_SECRET",
    "MKA_AUTOMATION_CONTACT_EMAIL", "MKA_REMINDER_SCHEDULE", "MKA_AUTOMATION_RUN_SEND_CAP",
    "MKA_AUTOMATION_SEND_DELAY_SECONDS", "MKA_AUTOMATION_MAX_CONSECUTIVE_FAILURES",
    "MKA_AUTOMATION_WEEKLY_REMINDER_CAP", "MKA_COMPLIANCE_TZ",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ENV:
        monkeypatch.delenv(name, raising=False)


def test_everything_is_off_by_default():
    assert not cfg.automation_enabled()
    for feature in ("autoenroll", "receipts", "reminders"):
        assert not cfg.feature_enabled(feature)


def test_per_feature_flag_is_ignored_without_the_master_switch(monkeypatch):
    for name in ("MKA_AUTOENROLL_ENABLED", "MKA_RECEIPTS_ENABLED", "MKA_REMINDERS_ENABLED"):
        monkeypatch.setenv(name, "true")
    assert not cfg.automation_enabled()
    assert not any(cfg.feature_enabled(f) for f in ("autoenroll", "receipts", "reminders"))


def test_master_on_but_feature_off_stays_off(monkeypatch):
    monkeypatch.setenv("MKA_AUTOMATION_ENABLED", "true")
    assert cfg.automation_enabled()
    assert not cfg.feature_enabled("receipts")
    monkeypatch.setenv("MKA_RECEIPTS_ENABLED", "1")
    assert cfg.feature_enabled("receipts")
    assert not cfg.feature_enabled("reminders")


def test_flag_is_read_at_call_time(monkeypatch):
    monkeypatch.setenv("MKA_AUTOMATION_ENABLED", "true")
    assert cfg.automation_enabled()
    monkeypatch.setenv("MKA_AUTOMATION_ENABLED", "false")
    assert not cfg.automation_enabled()


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "maybe", "2", " "])
def test_non_truthy_values_are_off(monkeypatch, value):
    monkeypatch.setenv("MKA_AUTOMATION_ENABLED", value)
    assert not cfg.automation_enabled()


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "Yes", "on", " true "])
def test_truthy_values_are_on(monkeypatch, value):
    monkeypatch.setenv("MKA_AUTOMATION_ENABLED", value)
    assert cfg.automation_enabled()


def test_unknown_feature_is_off(monkeypatch):
    monkeypatch.setenv("MKA_AUTOMATION_ENABLED", "true")
    assert not cfg.feature_enabled("nonsense")


def test_kind_to_feature_mapping():
    assert cfg.feature_for_kind("receipt") == "receipts"
    assert cfg.feature_for_kind("allset") == "receipts"
    assert cfg.feature_for_kind("reminder") == "reminders"
    assert cfg.feature_for_kind("digest") == "reminders"
    assert cfg.feature_for_kind("bogus") is None


def test_test_recipient_unset_blank_and_set(monkeypatch):
    assert cfg.test_recipient() is None
    monkeypatch.setenv("MKA_AUTOMATION_TEST_RECIPIENT", "")
    assert cfg.test_recipient() is None
    monkeypatch.setenv("MKA_AUTOMATION_TEST_RECIPIENT", "  Owner@Example.invalid ")
    assert cfg.test_recipient() == "owner@example.invalid"


@pytest.mark.parametrize("bad", ["not-an-address", "a@b", "a@b.invalid,c@d.invalid", "a@b.invalid\r\nBcc: x@y.invalid",
                                 "a b@c.invalid", "<a@b.invalid>", "a@b.invalid;c@d.invalid", "   "[:0] + "@b.invalid"])
def test_malformed_test_recipient_raises_instead_of_falling_back_to_real_sends(monkeypatch, bad):
    monkeypatch.setenv("MKA_AUTOMATION_TEST_RECIPIENT", bad)
    with pytest.raises(cfg.InvalidTestRecipient):
        cfg.test_recipient()


def test_secrets_and_contact_default_empty(monkeypatch):
    assert cfg.webhook_secret() == "" and cfg.cron_secret() == "" and cfg.contact_email() == ""
    monkeypatch.setenv("MKA_AUTOMATION_WEBHOOK_SECRET", "w")
    monkeypatch.setenv("MKA_AUTOMATION_CRON_SECRET", "c")
    monkeypatch.setenv("MKA_AUTOMATION_CONTACT_EMAIL", " help@example.invalid ")
    assert (cfg.webhook_secret(), cfg.cron_secret(), cfg.contact_email()) == ("w", "c", "help@example.invalid")


def test_malformed_contact_email_is_ignored_with_warning(monkeypatch, caplog):
    monkeypatch.setenv("MKA_AUTOMATION_CONTACT_EMAIL", "x@y.invalid\r\nBcc: z@y.invalid")
    with caplog.at_level(logging.WARNING):
        assert cfg.contact_email() == ""
    assert "MKA_AUTOMATION_CONTACT_EMAIL" in caplog.text


def test_default_schedule():
    sched = cfg.reminder_schedule()
    assert sched.days == ((11, 8), (11, 15), (11, 22), (11, 28))
    assert sched.weekly_after_deadline is True


def test_custom_schedule_parses_mmdd_iso_and_weekly(monkeypatch):
    monkeypatch.setenv("MKA_REMINDER_SCHEDULE", "12-01, 2026-11-05 ,11-09")
    sched = cfg.reminder_schedule()
    assert sched.days == ((11, 9), (12, 1))
    assert sched.dates == (date(2026, 11, 5),)
    assert sched.weekly_after_deadline is False  # not requested


@pytest.mark.parametrize("bad", ["13-01", "02-30", "11-8x", "garbage", "11-08,,", "2026-02-30", "11-08;11-15", "weekly,weekly,x"])
def test_invalid_schedule_falls_back_to_default_with_warning(monkeypatch, caplog, bad):
    monkeypatch.setenv("MKA_REMINDER_SCHEDULE", bad)
    with caplog.at_level(logging.WARNING):
        sched = cfg.reminder_schedule()
    assert sched == cfg.DEFAULT_SCHEDULE
    assert "MKA_REMINDER_SCHEDULE" in caplog.text


def test_is_reminder_day_default():
    s = cfg.reminder_schedule()
    deadline = date(2026, 12, 1)
    for d in (date(2026, 11, 8), date(2026, 11, 15), date(2026, 11, 22), date(2026, 11, 28)):
        assert cfg.is_reminder_day(d, deadline, s)
    assert not cfg.is_reminder_day(date(2026, 11, 9), deadline, s)
    assert not cfg.is_reminder_day(date(2026, 12, 1), deadline, s)  # the deadline day itself is not "after"
    assert cfg.is_reminder_day(date(2026, 12, 8), deadline, s)       # weekly after the deadline
    assert cfg.is_reminder_day(date(2026, 12, 15), deadline, s)
    assert not cfg.is_reminder_day(date(2026, 12, 9), deadline, s)


def test_is_reminder_day_without_deadline_or_weekly(monkeypatch):
    s = cfg.reminder_schedule()
    assert not cfg.is_reminder_day(date(2026, 12, 8), None, s)
    monkeypatch.setenv("MKA_REMINDER_SCHEDULE", "11-08")
    s2 = cfg.reminder_schedule()
    assert not cfg.is_reminder_day(date(2026, 12, 8), date(2026, 12, 1), s2)


def test_full_iso_date_token_matches_only_that_year(monkeypatch):
    monkeypatch.setenv("MKA_REMINDER_SCHEDULE", "2026-11-05")
    s = cfg.reminder_schedule()
    assert cfg.is_reminder_day(date(2026, 11, 5), None, s)
    assert not cfg.is_reminder_day(date(2027, 11, 5), None, s)


def test_numeric_defaults():
    assert cfg.run_send_cap() == 400
    assert cfg.send_delay_seconds() == pytest.approx(0.25)
    assert cfg.max_consecutive_failures() == 5
    assert cfg.weekly_reminder_cap() == 1


def test_numeric_overrides(monkeypatch):
    monkeypatch.setenv("MKA_AUTOMATION_RUN_SEND_CAP", "10")
    monkeypatch.setenv("MKA_AUTOMATION_SEND_DELAY_SECONDS", "0")
    monkeypatch.setenv("MKA_AUTOMATION_MAX_CONSECUTIVE_FAILURES", "2")
    monkeypatch.setenv("MKA_AUTOMATION_WEEKLY_REMINDER_CAP", "3")
    assert (cfg.run_send_cap(), cfg.send_delay_seconds(), cfg.max_consecutive_failures(), cfg.weekly_reminder_cap()) == (10, 0.0, 2, 3)


def test_zero_send_cap_is_allowed_as_a_hard_stop(monkeypatch):
    monkeypatch.setenv("MKA_AUTOMATION_RUN_SEND_CAP", "0")
    assert cfg.run_send_cap() == 0


@pytest.mark.parametrize("name,fn,default", [
    ("MKA_AUTOMATION_RUN_SEND_CAP", cfg.run_send_cap, 400),
    ("MKA_AUTOMATION_SEND_DELAY_SECONDS", cfg.send_delay_seconds, 0.25),
    ("MKA_AUTOMATION_MAX_CONSECUTIVE_FAILURES", cfg.max_consecutive_failures, 5),
    ("MKA_AUTOMATION_WEEKLY_REMINDER_CAP", cfg.weekly_reminder_cap, 1),
])
@pytest.mark.parametrize("bad", ["abc", "-1", "nan", "inf", "1e999", ""])
def test_bad_numbers_fall_back_to_default(monkeypatch, name, fn, default, bad):
    monkeypatch.setenv(name, bad)
    assert fn() == pytest.approx(default)


def test_failure_stop_and_weekly_cap_must_be_at_least_one(monkeypatch):
    monkeypatch.setenv("MKA_AUTOMATION_MAX_CONSECUTIVE_FAILURES", "0")
    monkeypatch.setenv("MKA_AUTOMATION_WEEKLY_REMINDER_CAP", "0")
    assert cfg.max_consecutive_failures() == 5 and cfg.weekly_reminder_cap() == 1


def test_timezone_follows_mka_compliance_tz_at_call_time(monkeypatch):
    assert str(cfg.cycle_tz()) == "America/New_York"
    monkeypatch.setenv("MKA_COMPLIANCE_TZ", "America/Los_Angeles")
    assert str(cfg.cycle_tz()) == "America/Los_Angeles"
    monkeypatch.setenv("MKA_COMPLIANCE_TZ", "Not/AZone")
    assert str(cfg.cycle_tz()) == "UTC"


def test_status_snapshot_exposes_no_secret_values(monkeypatch):
    monkeypatch.setenv("MKA_AUTOMATION_WEBHOOK_SECRET", "super-secret-w")
    monkeypatch.setenv("MKA_AUTOMATION_CRON_SECRET", "super-secret-c")
    monkeypatch.setenv("MKA_AUTOMATION_TEST_RECIPIENT", "owner.person@example.invalid")
    snap = cfg.status_snapshot()
    text = repr(snap)
    assert "super-secret" not in text and "owner.person" not in text
    assert snap["test_mode"] is True
    assert snap["test_recipient_masked"].endswith("@example.invalid") and "owner.person" not in snap["test_recipient_masked"]
    assert snap["webhook_secret_configured"] is True and snap["cron_secret_configured"] is True
    assert snap["enabled"] is False


def test_status_snapshot_with_invalid_recipient_reports_misconfiguration(monkeypatch):
    monkeypatch.setenv("MKA_AUTOMATION_TEST_RECIPIENT", "garbage")
    snap = cfg.status_snapshot()
    assert snap["test_mode"] is True and snap["test_recipient_invalid"] is True
    assert "garbage" not in repr(snap)
