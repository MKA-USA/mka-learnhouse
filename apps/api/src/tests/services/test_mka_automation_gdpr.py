"""MKA fork: GDPR export / anonymise / retention for automation data + the expected-roster scrub gap.

Identity rule under test: only a PROVEN address (attributes.is_address_proven) is ever used as a key; role
mailboxes are offices (row kept, person fields nulled); send-log/event rows are scrubbed by user_id only."""

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

VICTIM = "victim.person@mkausa.org"          # personal address (parser: unrecognized)
OTHER = "other.person@mkausa.org"
ROLE = "tabligh.albany@mkausa.org"           # org role mailbox (parser: matched, role nazim_dept)


async def cycle(db, org, label="2026-27"):
    c = MkaComplianceCycle(org_id=org.id, label=label, starts_on=date(2026, 11, 1), deadline_on=date(2026, 12, 1))
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return c


def roster(org, c, email, **over):
    base = dict(org_id=org.id, cycle_id=c.id, email=email, department="tabligh", level="local", majlis="Albany",
                region="East", role_title="Nazim Tabligh", person_name="Some Person", appointed_on=date(2026, 11, 1))
    base.update(over)
    return MkaComplianceExpected(**base)


def log(org_id, key, intended, *, user_id=None, to=None, **over):
    base = dict(org_id=org_id, kind="reminder", dedupe_key=key, user_id=user_id, to_email=to or intended,
                intended_email=intended, subject="s", status="sent")
    base.update(over)
    return MkaAutomationSendLog(**base)


def proof(uid, email, **over):
    base = dict(user_id=uid, email_seen=email, verified_hd=email.split("@")[1], derived={}, rules_version=attr_svc.get_rules().version,
                stale=False, effective={}, eff_status="matched")
    base.update(over)
    return MkaUserAttributes(**base)


async def all_of(db, model):
    return (await db.execute(select(model).order_by(model.id))).scalars().all()


async def anonymise(db, org, user_id):
    with patch("src.services.admin.admin.dispatch_webhooks", new_callable=AsyncMock):
        await anonymize_user(_make_token_user(org.id), user_id, db)


@pytest.fixture
async def world(db, org, other_org, user_role):
    """victim (301): personal address, PROVEN. other (302): colleague."""
    victim = await _create_user(db, user_id=301, username="vic", email="Victim.Person@mkausa.org")
    other = await _create_user(db, user_id=302, username="oth", email=OTHER)
    await _add_user_to_org(db, victim, org, role_id=user_role.id)
    await _add_user_to_org(db, other, org, role_id=user_role.id)
    c, c2 = await cycle(db, org), await cycle(db, other_org)
    db.add_all([
        proof(301, VICTIM),
        roster(org, c, VICTIM, person_name="Victim Person"),
        roster(org, c, VICTIM, department="maal", role_title="Nazim Maal", person_name="Victim Person"),
        roster(org, c, OTHER, person_name="Other Person"),
        roster(other_org, c2, VICTIM, person_name="Victim Person"),                           # org the victim is NOT in
        MkaAutomationEvent(org_id=org.id, delivery_id="d1", event="assignment_submitted", user_id=301, user_uuid="user_vic", status="processed"),
        MkaAutomationEvent(org_id=org.id, delivery_id="d2", event="assignment_submitted", user_id=302, user_uuid="user_oth", status="processed"),
        MkaAutomationEvent(org_id=org.id, delivery_id="d3", event="course_completed", user_id=None, user_uuid="user_vic", status="ignored"),
        log(org.id, "a", VICTIM, user_id=301),
        log(org.id, "b", VICTIM, user_id=None),                                              # email-only: about the mailbox
        log(org.id, "c", OTHER, user_id=302),
        log(org.id, "d", "someone.else@mkausa.org", to=VICTIM, test_mode=True),
        log(other_org.id, "e", VICTIM, user_id=None),
    ])
    await db.commit()
    return victim, other


# --- anonymise: automation rows (by user_id only) ------------------------------------------------------------


@pytest.mark.asyncio
async def test_anonymise_scrubs_rows_by_user_id_and_leaves_email_only_rows(db, org, other_org, world):
    await anonymise(db, org, 301)
    assert {e.delivery_id for e in await all_of(db, MkaAutomationEvent)} == {"d2"}          # d1 by id, d3 by user_uuid
    keys = {(s.org_id, s.dedupe_key) for s in await all_of(db, MkaAutomationSendLog)}
    assert keys == {(org.id, "b"), (org.id, "c"), (org.id, "d"), (other_org.id, "e")}      # only 'a' (user_id) is gone


# --- anonymise: expected roster (proven personal address -> delete) --------------------------------------------


@pytest.mark.asyncio
async def test_anonymise_deletes_roster_rows_of_a_proven_personal_address_in_member_orgs_only(db, org, other_org, world):
    """The existing gap: MkaComplianceExpected (email + person_name) survived an anonymise."""
    await anonymise(db, org, 301)
    left = [(r.org_id, r.email, r.person_name) for r in await all_of(db, MkaComplianceExpected)]
    assert sorted(left) == sorted([(org.id, OTHER, "Other Person"), (other_org.id, VICTIM, "Victim Person")])


@pytest.mark.asyncio
async def test_no_attributes_row_means_no_proof_and_nothing_email_keyed_is_touched(db, org, user_role):
    u = await _create_user(db, user_id=310, username="np", email=VICTIM)
    await _add_user_to_org(db, u, org, role_id=user_role.id)
    c = await cycle(db, org)
    db.add(roster(org, c, VICTIM, person_name="Real Holder"))
    await db.commit()
    assert await gdpr.known_emails(db, 310) == set()
    exp = await gdpr.export_user_records(db, 310)
    assert exp["compliance_roster"] == []
    await anonymise(db, org, 310)
    (row,) = await all_of(db, MkaComplianceExpected)
    assert row.person_name == "Real Holder"


@pytest.mark.asyncio
@pytest.mark.parametrize("over", [{"stale": True}, {"verified_hd": None}, {"verified_hd": "gmail.com"}])
async def test_a_stale_or_unverified_attributes_row_is_not_proof(db, org, user_role, over):
    u = await _create_user(db, user_id=311, username="st", email=VICTIM)
    await _add_user_to_org(db, u, org, role_id=user_role.id)
    c = await cycle(db, org)
    db.add_all([proof(311, VICTIM, **over), roster(org, c, VICTIM)])
    await db.commit()
    assert await gdpr.known_emails(db, 311) == set()
    await anonymise(db, org, 311)
    assert len(await all_of(db, MkaComplianceExpected)) == 1


@pytest.mark.asyncio
async def test_email_changed_after_proof_is_not_proof(db, org, user_role):
    """email_seen is the old proven address, the account now holds a different one: proof no longer holds."""
    u = await _create_user(db, user_id=312, username="ch", email="new.address@mkausa.org")
    await _add_user_to_org(db, u, org, role_id=user_role.id)
    c = await cycle(db, org)
    db.add_all([proof(312, "old.address@mkausa.org"), roster(org, c, "old.address@mkausa.org"), roster(org, c, "new.address@mkausa.org", department="maal")])
    await db.commit()
    assert await gdpr.known_emails(db, 312) == set()
    await anonymise(db, org, 312)
    assert len(await all_of(db, MkaComplianceExpected)) == 2


# --- the attack: change email to someone else's role mailbox --------------------------------------------------


@pytest.mark.asyncio
async def test_a_user_who_changed_their_email_to_an_unowned_role_mailbox_exports_and_erases_nothing_of_it(db, org, user_role):
    attacker = await _create_user(db, user_id=320, username="atk", email="attacker@example.invalid")
    holder = await _create_user(db, user_id=321, username="hold", email=ROLE)
    await _add_user_to_org(db, attacker, org, role_id=user_role.id)
    await _add_user_to_org(db, holder, org, role_id=user_role.id)
    c = await cycle(db, org)
    db.add_all([
        proof(320, "attacker@example.invalid", verified_hd=None),                       # never proven (non-Workspace)
        roster(org, c, ROLE, person_name="Real Nazim"),
        log(org.id, "r1", ROLE, user_id=None), log(org.id, "r2", ROLE, user_id=321),
        MkaAutomationEvent(org_id=org.id, delivery_id="h1", event="x", user_id=321, status="processed"),
    ])
    await db.commit()
    attacker.email = ROLE          # the email change (re-verification is all upstream asks for)
    db.add(attacker)
    await db.commit()
    exp = await gdpr.export_user_records(db, 320)
    assert exp == {"events": [], "send_log": [], "compliance_roster": []}
    assert "Real Nazim" not in repr(await mka_profile.profile_status(db, 320, include_attributes=True))
    await anonymise(db, org, 320)
    (row,) = await all_of(db, MkaComplianceExpected)
    assert (row.email, row.person_name, row.appointed_on) == (ROLE, "Real Nazim", date(2026, 11, 1))
    assert {s.dedupe_key for s in await all_of(db, MkaAutomationSendLog)} == {"r1", "r2"}
    assert {e.delivery_id for e in await all_of(db, MkaAutomationEvent)} == {"h1"}


# --- proven role mailbox: the office survives its holder -------------------------------------------------------


@pytest.mark.asyncio
async def test_proven_role_mailbox_account_keeps_the_office_row_and_nulls_the_person(db, org, other_org, user_role):
    holder = await _create_user(db, user_id=330, username="rm", email=ROLE)
    nxt = await _create_user(db, user_id=331, username="nx", email="next.holder@mkausa.org")
    await _add_user_to_org(db, holder, org, role_id=user_role.id)
    await _add_user_to_org(db, nxt, org, role_id=user_role.id)
    c, c2 = await cycle(db, org), await cycle(db, other_org)
    db.add_all([
        proof(330, ROLE),
        roster(org, c, ROLE, person_name="Outgoing Nazim"),
        roster(other_org, c2, ROLE, person_name="Other Org Nazim"),
        log(org.id, "mine", ROLE, user_id=330), log(org.id, "office", ROLE, user_id=None), log(org.id, "next", ROLE, user_id=331),
        MkaAutomationEvent(org_id=org.id, delivery_id="n1", event="x", user_id=331, status="processed"),
    ])
    await db.commit()
    await anonymise(db, org, 330)
    rows = {r.org_id: r for r in await all_of(db, MkaComplianceExpected)}
    assert (rows[org.id].email, rows[org.id].role_title, rows[org.id].person_name, rows[org.id].appointed_on) == (ROLE, "Nazim Tabligh", None, None)
    assert (rows[other_org.id].person_name, rows[other_org.id].appointed_on) == ("Other Org Nazim", date(2026, 11, 1))
    assert {s.dedupe_key for s in await all_of(db, MkaAutomationSendLog)} == {"office", "next"}   # next holder's history untouched
    assert {e.delivery_id for e in await all_of(db, MkaAutomationEvent)} == {"n1"}


def test_role_mailbox_detection_uses_the_identity_parser():
    assert gdpr.is_role_mailbox(ROLE) and gdpr.is_role_mailbox("sadr@mkausa.org")
    assert not gdpr.is_role_mailbox(VICTIM) and not gdpr.is_role_mailbox("john.doe@gmail.com")


# --- ordering / commits / misc ---------------------------------------------------------------------------------


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
    assert len(await all_of(db, MkaComplianceExpected)) == 4


@pytest.mark.asyncio
async def test_anonymise_with_no_automation_data_still_works(db, org, user_role):
    u = await _create_user(db, user_id=340, username="none", email="none@mkausa.org")
    await _add_user_to_org(db, u, org, role_id=user_role.id)
    await anonymise(db, org, 340)


@pytest.mark.asyncio
async def test_placeholder_addresses_are_never_proof(db, org, user_role):
    u = await _create_user(db, user_id=341, username="ph", email="deleted-user-1@anonymized.example.com")
    await _add_user_to_org(db, u, org, role_id=user_role.id)
    c = await cycle(db, org)
    db.add_all([proof(341, "deleted-user-1@anonymized.example.com", verified_hd="anonymized.example.com"), roster(org, c, "deleted-user-1@anonymized.example.com")])
    await db.commit()
    assert await gdpr.known_emails(db, 341) == set()


# --- export ------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_contains_only_the_users_own_records(db, org, other_org, world):
    out = (await mka_profile.profile_status(db, 301, include_attributes=True))["mka_automation"]
    assert {e["delivery_id"] for e in out["events"]} == {"d1", "d3"}
    assert [(s["kind"], s["intended_email"]) for s in out["send_log"]] == [("reminder", VICTIM)]   # user_id rows only
    assert {r["role_title"] for r in out["compliance_roster"]} == {"Nazim Tabligh", "Nazim Maal"}
    assert all(r["org_id"] == org.id for r in out["compliance_roster"])
    text = repr(out)
    assert OTHER not in text and "someone.else@mkausa.org" not in text and "Other Person" not in text


@pytest.mark.asyncio
async def test_export_never_contains_the_reviewers_address_of_a_test_mode_row(db, org, world):
    """Review L6: in test mode ``to_email`` is the reviewer's own mailbox, which is not the data subject's data."""
    reviewer = "reviewer.private@example.invalid"
    db.add(log(org.id, "reminder:2026-W46:tm", VICTIM, user_id=301, to=reviewer, test_mode=True, kind="digest"))
    await db.commit()
    out = (await gdpr.export_user_records(db, 301))
    rows = [s for s in out["send_log"] if s["test_mode"]]
    assert len(rows) == 1 and rows[0]["to_email"] is None and rows[0]["intended_email"] == VICTIM
    assert reviewer not in repr(out)
    real_rows = [s for s in out["send_log"] if not s["test_mode"]]
    assert all(s["to_email"] == VICTIM for s in real_rows)  # real mail: the person's own address stays


@pytest.mark.asyncio
async def test_export_user_data_includes_the_automation_section(db, org, world):
    data = await export_user_data(_make_token_user(org.id), 301, db)
    assert set(data["mka_profile"]["mka_automation"]) == {"events", "send_log", "compliance_roster"}
    assert len(data["mka_profile"]["mka_automation"]["compliance_roster"]) == 2


@pytest.mark.asyncio
async def test_learner_facing_profile_status_never_includes_automation_data(db, org, world):
    assert "mka_automation" not in await mka_profile.profile_status(db, 301)


@pytest.mark.asyncio
async def test_export_omits_the_section_when_the_user_has_no_records(db, org, user_role):
    u = await _create_user(db, user_id=350, username="empty", email="empty@mkausa.org")
    await _add_user_to_org(db, u, org, role_id=user_role.id)
    assert await mka_profile.profile_status(db, 350, include_attributes=True) == {"complete": False}


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


@pytest.mark.asyncio
async def test_export_omits_the_section_when_the_user_has_no_automation_records(db, org, user_role):
    u = await _create_user(db, user_id=330, username="empty", email="empty@mkausa.org")
    await _add_user_to_org(db, u, org, role_id=user_role.id)
    assert await mka_profile.profile_status(db, 330, include_attributes=True) == {"complete": False}
