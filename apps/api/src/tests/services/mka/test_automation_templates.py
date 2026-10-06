"""MKA fork: automation email wording (golden snapshots + escaping + wording rules).

Regenerate the goldens deliberately with ``UPDATE_GOLDEN=1`` and REVIEW the diff: a missing golden fails."""

import os
import re
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from src.services.mka import automation_templates as t

GOLDEN = Path(__file__).parent / "golden"
CONTACT = "help@example.invalid"
URL = "https://ilm.example.invalid/courses/general"
SIGNED = datetime(2026, 11, 12, 20, 5, tzinfo=timezone.utc)  # 3:05 PM EST in New York


@pytest.fixture(autouse=True)
def tz(monkeypatch):
    monkeypatch.setenv("MKA_COMPLIANCE_TZ", "America/New_York")


def check_golden(name: str, out: t.Rendered):
    payload = f"SUBJECT: {out.subject}\n\n--- TEXT ---\n{out.text}\n--- HTML ---\n{out.html}\n"
    path = GOLDEN / f"automation_{name}.golden.txt"
    if os.environ.get("UPDATE_GOLDEN") == "1":
        path.write_text(payload, encoding="utf-8")
    assert path.exists(), f"missing golden {path.name}; run with UPDATE_GOLDEN=1 and review it"
    assert payload == path.read_text(encoding="utf-8")


def receipt(**over):
    base = dict(addressee="Nazim Tabligh, Albany", course_title="Tabligh Department", signed_at=SIGNED,
                cycle_label="2026-27", remaining=["General course"], course_url=URL, contact_email=CONTACT)
    base.update(over)
    return t.render_receipt(**base)


def allset(**over):
    base = dict(addressee="Nazim Tabligh, Albany", cycle_label="2026-27", url=URL, contact_email=CONTACT)
    base.update(over)
    return t.render_allset(**base)


def reminder(**over):
    base = dict(addressee="Nazim Tabligh, Albany", cycle_label="2026-27", deadline=date(2026, 12, 1), today=date(2026, 11, 22),
                outstanding=[("General course", "not_started"), ("Tabligh Department", "in_progress")], url=URL, contact_email=CONTACT)
    base.update(over)
    return t.render_reminder(**base)


def digest(**over):
    base = dict(addressee="Regional Qaid, Northeast", cycle_label="2026-27", scope_label="Northeast region",
                counts={"attested": 30, "in_progress": 6, "not_started": 4, "not_signed_in": 8, "overdue": 0},
                needs_nudge=["Nazim Tabligh, Albany", "Nazim Maal, Boston"], url=URL, contact_email=CONTACT)
    base.update(over)
    return t.render_digest(**base)


# --- golden snapshots -------------------------------------------------------------------------------------


def test_golden_receipt_with_work_remaining():
    check_golden("receipt_remaining", receipt())


def test_golden_receipt_everything_done():
    check_golden("receipt_done", receipt(remaining=[]))


def test_golden_receipt_two_remaining_personal_greeting_no_contact():
    check_golden("receipt_two_remaining", receipt(addressee="Ahmad", remaining=["General course", "Maal Department"], contact_email=None))


def test_golden_allset():
    check_golden("allset", allset())


def test_golden_reminder_before_deadline():
    check_golden("reminder", reminder())


def test_golden_reminder_overdue():
    check_golden("reminder_overdue", reminder(today=date(2026, 12, 8), outstanding=[("General course", "overdue")]))


def test_golden_digest():
    check_golden("digest", digest())


def test_golden_digest_empty_nudge_list_and_no_contact():
    check_golden("digest_empty", digest(needs_nudge=[], contact_email="", counts={"attested": 12}))


# --- wording rules ------------------------------------------------------------------------------------------

ALL = [
    ("receipt", receipt), ("receipt_done", lambda: receipt(remaining=[])), ("allset", allset),
    ("reminder", reminder), ("reminder_overdue", lambda: reminder(today=date(2026, 12, 8))), ("digest", digest),
]


@pytest.mark.parametrize("name,fn", ALL)
def test_exactly_one_content_link_and_one_mailto(name, fn):
    out = fn()
    hrefs = re.findall(r'href="([^"]+)"', out.html)
    assert hrefs == [URL, f"mailto:{CONTACT}"]
    assert out.text.count("http") == 1


@pytest.mark.parametrize("name,fn", ALL)
def test_no_emoji_no_marketing_no_unsubscribe(name, fn):
    out = fn()
    blob = out.subject + out.text + out.html
    assert not re.search("[\U0001f300-\U0001faff☀-➿]", blob)
    assert "unsubscribe" not in blob.lower() and "!" not in blob
    assert "\r" not in out.subject and "\n" not in out.subject


@pytest.mark.parametrize("name,fn", ALL)
def test_text_and_html_agree_on_the_key_facts(name, fn):
    out = fn()
    for needle in ("Nazim Tabligh, Albany", "Regional Qaid, Northeast"):
        if needle in out.text:
            assert needle in out.html


@pytest.mark.parametrize("name,fn", ALL)
def test_contact_line_comes_from_config_and_is_optional(name, fn):
    assert CONTACT in fn().text
    out = (fn.__wrapped__ if hasattr(fn, "__wrapped__") else fn)()
    assert "Questions?" in out.text


def test_no_contact_email_means_no_contact_line_and_a_malformed_one_is_dropped():
    assert "Questions?" not in receipt(contact_email=None).text
    bad = receipt(contact_email="a@example.invalid\r\nBcc: b@example.invalid")
    assert "Questions?" not in bad.text and "Bcc" not in bad.html and "Bcc" not in bad.text


def test_receipt_states_course_and_time_in_the_cycle_timezone():
    out = receipt()
    assert "“Tabligh Department”" in out.text
    assert "November 12, 2026 at 3:05 PM EST" in out.text
    assert out.subject == "We have recorded your sign-off: Tabligh Department"


def test_receipt_timezone_follows_the_environment(monkeypatch):
    monkeypatch.setenv("MKA_COMPLIANCE_TZ", "America/Los_Angeles")
    assert "12:05 PM PST" in receipt().text


def test_receipt_lists_what_is_left_or_says_it_is_complete():
    assert "You still need to complete: General course." in receipt().text
    assert "General course and Maal Department" in receipt(remaining=["General course", "Maal Department"]).text
    done = receipt(remaining=[]).text
    assert "everything required of you for 2026-27" in done and "still need" not in done


def test_reminder_countdown_and_overdue_wording():
    assert "(9 days left)" in reminder().text and reminder().subject == "Reminder: 2026-27 compliance training"
    assert "(1 day left)" in reminder(today=date(2026, 11, 30)).text
    assert "The deadline is today" in reminder(today=date(2026, 12, 1)).text
    late = reminder(today=date(2026, 12, 8))
    assert "now overdue" in late.text and late.subject == "Overdue: 2026-27 compliance training"


def test_reminder_status_phrases_and_unknown_status():
    out = reminder(outstanding=[("A", "not_signed_in"), ("B", "overdue"), ("C", "weird")])
    assert "- A: not signed in yet" in out.text and "- B: overdue" in out.text and "- C: not finished" in out.text


def test_reminder_needs_something_outstanding():
    with pytest.raises(ValueError):
        reminder(outstanding=[])


def test_digest_lists_role_titles_only_and_counts():
    out = digest()
    assert "Signed off: 30 of 48" in out.text and "Not signed in yet: 8" in out.text
    assert "- Nazim Tabligh, Albany" in out.text and "- Nazim Maal, Boston" in out.text


def test_digest_is_capped_and_survives_bad_counts():
    out = digest(needs_nudge=[f"Role {i}" for i in range(60)], counts={"attested": "x", "overdue": -3, "in_progress": "4"})
    assert out.text.count("\n- ") == 51 and "- and 10 more" in out.text
    assert "Signed off: 0 of 4" in out.text and "Overdue: 0" in out.text


def test_digest_never_contains_a_name_that_was_not_passed_in():
    out = digest(needs_nudge=["Nazim Tabligh, Albany"])
    assert "Maal" not in out.text and "Boston" not in out.html


# --- addressee ---------------------------------------------------------------------------------------------


def test_addressee_rules():
    assert t.addressee(first_name="Ahmad", role_title="Nazim Tabligh", majlis="Albany") == "Ahmad"
    assert t.addressee(role_title="Nazim Tabligh", majlis="Albany") == "Nazim Tabligh, Albany"
    assert t.addressee(role_title="Nazim Tabligh Albany", majlis="Albany") == "Nazim Tabligh Albany"  # already there
    assert t.addressee(role_title="Qaid Majlis") == "Qaid Majlis"
    assert t.addressee() == ""
    assert t.addressee(first_name="  \n ", role_title="Sadr", majlis=None) == "Sadr"


def test_empty_addressee_gives_a_plain_greeting():
    out = receipt(addressee="")
    assert out.text.startswith("Hello,\n") and "<p" in out.html and "Hello,</p>" in out.html


# --- escaping / injection ---------------------------------------------------------------------------------


EVIL = '<script>alert(1)</script> & "q" \'s\' <img src=x onerror=y>'


@pytest.mark.parametrize("name,fn", [
    ("receipt-who", lambda: receipt(addressee=EVIL)),
    ("receipt-course", lambda: receipt(course_title=EVIL, remaining=[EVIL])),
    ("receipt-cycle", lambda: receipt(cycle_label=EVIL, remaining=[])),
    ("allset", lambda: allset(addressee=EVIL, cycle_label=EVIL)),
    ("reminder", lambda: reminder(addressee=EVIL, cycle_label=EVIL, outstanding=[(EVIL, "overdue")])),
    ("digest", lambda: digest(addressee=EVIL, cycle_label=EVIL, scope_label=EVIL, needs_nudge=[EVIL])),
])
def test_every_interpolated_value_is_html_escaped(name, fn):
    out = fn()
    assert "<script" not in out.html and "<img" not in out.html
    assert "&lt;script&gt;" in out.html and "&amp;" in out.html and "&quot;q&quot;" in out.html
    assert 'onerror=y>' not in out.html.replace("&gt;", "")  # the tag cannot survive


def test_url_is_attribute_escaped_and_must_be_http():
    out = receipt(course_url='https://x.example.invalid/a?b=1&c="2"')
    assert 'href="https://x.example.invalid/a?b=1&amp;c=&quot;2&quot;"' in out.html
    for bad in ("javascript:alert(1)", "data:text/html,x", "//example.invalid/x", "/relative", "", "ftp://x.invalid/a"):
        with pytest.raises(ValueError):
            receipt(course_url=bad)


def test_newlines_in_data_cannot_reach_the_subject_or_split_lines():
    out = receipt(course_title="Line1\r\nBcc: evil@example.invalid")
    assert "\n" not in out.subject and "\r" not in out.subject
    assert "Bcc: evil@example.invalid" in out.subject  # kept as inert text on ONE line
    assert "\r" not in out.text


def test_rendering_is_deterministic():
    assert receipt() == receipt() and digest() == digest()
