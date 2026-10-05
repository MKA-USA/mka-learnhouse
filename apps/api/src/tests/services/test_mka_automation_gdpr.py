"""MKA fork: GDPR export / anonymise / retention for automation data + the expected-roster scrub gap."""

from datetime import date, datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlmodel import select

from src.db.mka_automation import MkaAutomationEvent, MkaAutomationSendLog
from src.db.mka_compliance import MkaComplianceCycle, MkaComplianceExpected
from src.db.mka_user_attributes import MkaUserAttributes
from src.services.admin.admin import anonymize_user, export_user_data
from src.services.mka import attributes as attr_svc
from src.services.mka import automation_gdpr as gdpr
from src.services.users import mka_profile
from src.tests.services.test_admin_service_extra import _add_user_to_org, _create_user, _make_token_user

VICTIM_EMAIL = "Victim.Person@mkausa.org"


async def cycle(db, org, label="2026-27"):
    c = MkaComplianceCycle(org_id=org.id, label=label, starts_on=date(2026, 11, 1), deadline_on=date(2026, 12, 1))
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return c


def roster(org, c, email, **over):
    base = dict(org_id=org.id, cycle_id=c.id, email=email, department="tabligh", level="local", majlis="Albany",
                region="East", role_title="Nazim Tabligh", person_name="Victim Person")
    base.update(over)
    return MkaComplianceExpected(**base)


def log(org_id, key, intended, *, user_id=None, to=None, **over):
    base = dict(org_id=org_id, kind="reminder", dedupe_key=key, user_id=user_id, to_email=to or intended,
                intended_email=intended, subject="s", status="sent")
    base.update(over)
    return MkaAutomationSendLog(**base)


async def all_of(db, model):
    return (await db.execute(select(model).order_by(model.id))).scalars().all()


@pytest.fixture
async def world(db, org, other_org, user_role):
    victim = await _create_user(db, user_id=301, username="vic", email=VICTIM_EMAIL)
    other = await _create_user(db, user_id=302, username="oth", email="other.person@mkausa.org")
    await _add_user_to_org(db, victim, org, role_id=user_role.id)
    await _add_user_to_org(db, other, org, role_id=user_role.id)
    c = await cycle(db, org)
    c2 = await cycle(db, other_org)
    db.add_all([
        roster(org, c, VICTIM_EMAIL.lower()),
        roster(org, c, VICTIM_EMAIL.lower(), department="maal", role_title="Nazim Maal"),     # second role
        roster(org, c, "other.person@mkausa.org", person_name="Other Person"),
        roster(other_org, c2, VICTIM_EMAIL.lower()),                                          # org the victim is NOT in
        MkaAutomationEvent(org_id=org.id, delivery_id="d1", event="assignment_submitted", user_id=301, user_uuid="user_vic", status="processed"),
        MkaAutomationEvent(org_id=org.id, delivery_id="d2", event="assignment_submitted", user_id=302, user_uuid="user_oth", status="processed"),
        MkaAutomationEvent(org_id=org.id, delivery_id="d3", event="course_completed", user_id=None, user_uuid="user_vic", status="ignored"),
        log(org.id, "a", VICTIM_EMAIL.lower(), user_id=301),
        log(org.id, "b", VICTIM_EMAIL.lower(), user_id=None),                                 # email-keyed only
        log(org.id, "c", "other.person@mkausa.org", user_id=302),
        log(org.id, "d", "someone.else@mkausa.org", to="victim.person@mkausa.org", test_mode=True),  # test mail delivered TO the victim
        log(other_org.id, "e", VICTIM_EMAIL.lower(), user_id=None),                           # other org: not ours to delete
    ])
    await db.commit()
    return victim, other


async def anonymise(db, org, user_id):
    with patch("src.services.admin.admin.dispatch_webhooks", new_callable=AsyncMock):
        await anonymize_user(_make_token_user(org.id), user_id, db)


# --- anonymise -----------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_anonymise_scrubs_the_users_automation_rows_and_leaves_everyone_else(db, org, other_org, world):
    await anonymise(db, org, 301)
    events = {e.delivery_id for e in await all_of(db, MkaAutomationEvent)}
    assert events == {"d2"}                                                   # d1 by user_id, d3 by user_uuid
    keys = {(s.org_id, s.dedupe_key) for s in await all_of(db, MkaAutomationSendLog)}
    assert keys == {(org.id, "c"), (other_org.id, "e")}                       # a (user_id), b (email), d (to_email) gone


@pytest.mark.asyncio
async def test_anonymise_scrubs_the_expected_roster_rows_for_the_users_email_every_role(db, org, other_org, world):
    """The existing gap: MkaComplianceExpected (email + person_name) survived an anonymise."""
    await anonymise(db, org, 301)
    left = [(r.org_id, r.email, r.person_name) for r in await all_of(db, MkaComplianceExpected)]
    assert (org.id, VICTIM_EMAIL.lower(), "Victim Person") not in left
    assert not any(r[0] == org.id and r[1] == VICTIM_EMAIL.lower() for r in left)
    assert (org.id, "other.person@mkausa.org", "Other Person") in left          # a colleague is untouched
    assert (other_org.id, VICTIM_EMAIL.lower(), "Victim Person") in left        # an org the user is not in is not ours to edit


@pytest.mark.asyncio
async def test_roster_scrub_also_uses_email_seen_when_the_account_email_changed(db, org, user_role):
    u = await _create_user(db, user_id=310, username="ch", email="new.address@mkausa.org")
    await _add_user_to_org(db, u, org, role_id=user_role.id)
    c = await cycle(db, org)
    db.add_all([roster(org, c, "old.address@mkausa.org", person_name="Old"), roster(org, c, "new.address@mkausa.org", department="maal", person_name="New")])
    db.add(MkaUserAttributes(user_id=310, email_seen="old.address@mkausa.org", derived={}, rules_version=attr_svc.get_rules().version,
                             stale=False, effective={}, eff_status="matched"))
    await db.commit()
    await anonymise(db, org, 310)
    assert await all_of(db, MkaComplianceExpected) == []


@pytest.mark.asyncio
async def test_roster_scrub_works_with_no_attributes_row_and_after_prior_commits(db, org, world):
    """Nothing but the pending User.email history can supply the address here (placeholder is set before the hook)."""
    assert await db.get(MkaUserAttributes, 301) is None
    await anonymise(db, org, 301)
    assert not [r for r in await all_of(db, MkaComplianceExpected) if r.org_id == org.id and r.email == VICTIM_EMAIL.lower()]


@pytest.mark.asyncio
async def test_scrub_runs_before_delete_attributes(db, org, world, monkeypatch):
    order = []
    real_scrub, real_delete = gdpr.scrub_user_records, attr_svc.delete_attributes

    async def spy_scrub(*a, **k):
        order.append("scrub")
        return await real_scrub(*a, **k)

    async def spy_delete(*a, **k):
        order.append("delete_attributes")
        return await real_delete(*a, **k)

    monkeypatch.setattr(gdpr, "scrub_user_records", spy_scrub)
    monkeypatch.setattr(attr_svc, "delete_attributes", spy_delete)
    await anonymise(db, org, 301)
    assert order == ["scrub", "delete_attributes"]


@pytest.mark.asyncio
async def test_the_scrub_itself_does_not_commit(db, org, world):
    await mka_profile.delete_profile(db, 301)
    await db.rollback()
    assert {e.delivery_id for e in await all_of(db, MkaAutomationEvent)} == {"d1", "d2", "d3"}


@pytest.mark.asyncio
async def test_anonymise_with_no_automation_data_still_works(db, org, user_role):
    u = await _create_user(db, user_id=320, username="none", email="none@mkausa.org")
    await _add_user_to_org(db, u, org, role_id=user_role.id)
    await anonymise(db, org, 320)


@pytest.mark.asyncio
async def test_placeholder_addresses_are_never_used_as_match_keys(db, org, user_role):
    u = await _create_user(db, user_id=321, username="ph", email="deleted-user-1@anonymized.example.com")
    await _add_user_to_org(db, u, org, role_id=user_role.id)
    c = await cycle(db, org)
    db.add_all([roster(org, c, "deleted-user-1@anonymized.example.com"), roster(org, c, "kept@mkausa.org", department="maal")])
    await db.commit()
    assert await gdpr.known_emails(db, 321) == set()
    await gdpr.scrub_user_records(db, 321)
    assert len(await all_of(db, MkaComplianceExpected)) == 2


# --- export ------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_contains_only_the_users_own_records(db, org, other_org, world):
    out = (await mka_profile.profile_status(db, 301, include_attributes=True))["mka_automation"]
    assert {e["delivery_id"] for e in out["events"]} == {"d1", "d3"}
    assert {(s["kind"], s["intended_email"]) for s in out["send_log"]} == {("reminder", VICTIM_EMAIL.lower())}
    assert len(out["send_log"]) == 2                                           # a (user_id) + b (email); e is another org, d is mail TO them about someone else
    assert {r["role_title"] for r in out["compliance_roster"]} == {"Nazim Tabligh", "Nazim Maal"}
    assert all(r["org_id"] == org.id for r in out["compliance_roster"])
    text = repr(out)
    assert "other.person@mkausa.org" not in text and "someone.else@mkausa.org" not in text and "Other Person" not in text


@pytest.mark.asyncio
async def test_export_user_data_includes_the_automation_section(db, org, world):
    data = await export_user_data(_make_token_user(org.id), 301, db)
    assert set(data["mka_profile"]["mka_automation"]) == {"events", "send_log", "compliance_roster"}
    assert len(data["mka_profile"]["mka_automation"]["compliance_roster"]) == 2


@pytest.mark.asyncio
async def test_learner_facing_profile_status_never_includes_automation_data(db, org, world):
    assert "mka_automation" not in await mka_profile.profile_status(db, 301)


# --- retention ---------------------------------------------------------------------------------------------

NOW = datetime(2026, 10, 5, 12, 0)


@pytest.mark.asyncio
async def test_purge_older_than_deletes_only_rows_past_the_cutoff(db, org):
    old, edge_old, edge_new, fresh = datetime(2025, 3, 1), datetime(2025, 4, 4, 11, 59), datetime(2025, 4, 5, 12, 0), datetime(2026, 9, 1)
    db.add_all([
        log(org.id, "old", "a@example.invalid", created_at=old),
        log(org.id, "edge-old", "a@example.invalid", created_at=edge_old),
        log(org.id, "edge-new", "a@example.invalid", created_at=edge_new),
        log(org.id, "fresh", "a@example.invalid", created_at=fresh),
        MkaAutomationEvent(org_id=org.id, delivery_id="o", event="x", status="processed", received_at=old),
        MkaAutomationEvent(org_id=org.id, delivery_id="n", event="x", status="processed", received_at=fresh),
    ])
    await db.commit()
    result = await gdpr.purge_older_than(db, now=NOW)  # default 18 months -> cutoff 2025-04-05 12:00
    assert result["send_log"] == 2 and result["events"] == 1 and result["cutoff"] == datetime(2025, 4, 5, 12, 0)
    assert {s.dedupe_key for s in await all_of(db, MkaAutomationSendLog)} == {"edge-new", "fresh"}
    assert {e.delivery_id for e in await all_of(db, MkaAutomationEvent)} == {"n"}


@pytest.mark.asyncio
async def test_purge_covers_email_keyed_rows_in_every_org_and_is_committed(db, org, other_org):
    db.add_all([log(org.id, "k1", "a@example.invalid", created_at=datetime(2020, 1, 1)),
                log(other_org.id, "k2", "b@example.invalid", created_at=datetime(2020, 1, 1))])
    await db.commit()
    await gdpr.purge_older_than(db, 12, now=NOW)
    await db.rollback()  # proves it committed
    assert await all_of(db, MkaAutomationSendLog) == []


@pytest.mark.parametrize("bad", [0, -1, 1.5, "18", None, True])
@pytest.mark.asyncio
async def test_purge_refuses_a_value_that_could_wipe_everything(db, org, bad):
    db.add(log(org.id, "k", "a@example.invalid"))
    await db.commit()
    with pytest.raises(ValueError):
        await gdpr.purge_older_than(db, bad, now=NOW)
    assert len(await all_of(db, MkaAutomationSendLog)) == 1


def test_month_arithmetic_clamps_to_the_end_of_short_months():
    assert gdpr._months_ago(datetime(2026, 3, 31), 1) == datetime(2026, 2, 28)
    assert gdpr._months_ago(datetime(2026, 1, 15), 2) == datetime(2025, 11, 15)
    assert gdpr._months_ago(datetime(2024, 3, 31), 1) == datetime(2024, 2, 29)
    assert gdpr._months_ago(datetime(2026, 10, 5), 18) == datetime(2025, 4, 5)
    assert gdpr._months_ago(datetime(2026, 10, 5), 12) == datetime(2025, 10, 5)


@pytest.mark.asyncio
async def test_purge_test_rows_only_removes_that_orgs_test_rows(db, org, other_org):
    db.add_all([log(org.id, "t", "a@example.invalid", test_mode=True), log(org.id, "r", "a@example.invalid"),
                log(other_org.id, "t", "a@example.invalid", test_mode=True)])
    await db.commit()
    assert await gdpr.purge_test_rows(db, org.id) == 1
    assert {(s.org_id, s.dedupe_key) for s in await all_of(db, MkaAutomationSendLog)} == {(org.id, "r"), (other_org.id, "t")}
