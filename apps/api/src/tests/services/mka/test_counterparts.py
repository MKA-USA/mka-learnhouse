"""MKA fork: counterparts (contract s2.3). Viewers are built by the REAL parser from synthetic mailbox names, and every
emitted mailbox is parsed back to prove the provider is the inverse of the parser (both read the same rules file)."""

import copy

import pytest

from src.services.mka.attributes import effective_public
from src.services.mka.counterparts import MailboxProvider, counterparts_for
from src.services.mka.identity_parser import IdentityRules, load_rules, parse_identity
from src.services.users.mka_profile import MAJLIS_TO_REGION

RULES = load_rules()


def attrs_of(email):
    return effective_public(parse_identity(email, RULES).to_dict())


def result(email, own=None):
    return counterparts_for(attrs_of(email), RULES, own_email=own if own is not None else email)


def emails(res):
    return [r["email"] for r in res["counterparts"]]


def test_local_nazim_gets_national_and_regional_not_self():
    res = result("tabligh.albany@mkausa.org")
    assert res["reason"] is None
    assert [(r["level"], r["role_title"], r["email"], r["department"]) for r in res["counterparts"]] == [
        ("national", "Mohtamim Tabligh", "tabligh@mkausa.org", "tabligh"),
        ("regional", "Regional Qaid", "qaid.northeast@mkausa.org", None),
    ]
    assert all(r["name"] is None for r in res["counterparts"])


def test_local_row_appears_for_a_different_role_in_the_department():
    res = result("murabbi.syracuse@atfalusa.org")
    assert [(r["level"], r["role_title"], r["email"]) for r in res["counterparts"]] == [
        ("national", "Mohtamim Atfal", "atfal@mkausa.org"),
        ("regional", "Regional Qaid", "qaid.northeast@mkausa.org"),
        ("local", "Nazim Atfal", "nazim.syracuse@atfalusa.org"),
    ]


def test_atfal_nazim_on_atfalusa_org_omits_own_local_row():
    res = result("nazim.syracuse@atfalusa.org")
    assert emails(res) == ["atfal@mkausa.org", "qaid.northeast@mkausa.org"]
    assert res["counterparts"][0]["department"] == "atfal"


def test_local_executives_get_only_their_regional_qaid():
    for email, region_mailbox in (
        ("qaid.houston@mkausa.org", "qaid.gulf@mkausa.org"),
        ("naibqaid.houston@mkausa.org", "qaid.gulf@mkausa.org"),
        ("motamid.albany@mkausa.org", "qaid.northeast@mkausa.org"),
    ):
        res = result(email)
        assert res["reason"] is None
        assert emails(res) == [region_mailbox], email
        assert res["counterparts"][0]["level"] == "regional"


def test_regional_qaid_has_no_department():
    res = result("qaid.northeast@mkausa.org")
    assert res == {"counterparts": [], "reason": "no_department"}


def test_sadr_and_national_staff_have_no_department():
    for email in ("sadr@mkausa.org", "legal@mkausa.org"):
        assert result(email) == {"counterparts": [], "reason": "no_department"}


def test_national_head_sees_nothing_when_all_rows_are_themselves():
    res = result("tabligh@mkausa.org")
    assert res == {"counterparts": [], "reason": None}


def test_national_head_viewing_with_a_different_address_still_gets_the_mailbox():
    res = counterparts_for(attrs_of("tabligh@mkausa.org"), RULES, own_email="someone.else@example.invalid")
    assert emails(res) == ["tabligh@mkausa.org"]


def test_regional_department_nazim_gets_national_and_regional_qaid_only():
    res = result("tabligh.northeast@mkausa.org")
    assert [r["level"] for r in res["counterparts"]] == ["national", "regional"]
    assert emails(res) == ["tabligh@mkausa.org", "qaid.northeast@mkausa.org"]


def test_partial_viewer_with_department_only_gets_national_row():
    attrs = attrs_of("tabligh.brandnewmajlis@mkausa.org")
    assert attrs["status"] == "partial"
    assert emails(counterparts_for(attrs, RULES, own_email="x@example.invalid")) == ["tabligh@mkausa.org"]


def test_unrecognized_statuses_get_reason_unrecognized():
    for email in ("john.smith@mkausa.org", "someone@gmail.com", "", "qaid.newyorkmetro@mkausa.org"):
        attrs = attrs_of(email)
        assert attrs["status"] != "matched" or email == "qaid.newyorkmetro@mkausa.org"
    for status in ("unrecognized", "ambiguous", "not_applicable", "something_new"):
        res = counterparts_for({"status": status, "department": "tabligh", "role": "qaid", "level": "local", "region": "Gulf"}, RULES)
        assert res == {"counterparts": [], "reason": "unrecognized"}
    assert counterparts_for(attrs_of("someone@gmail.com"), RULES) == {"counterparts": [], "reason": "unrecognized"}


def test_missing_attribute_keys_do_not_raise():
    assert counterparts_for({}, RULES) == {"counterparts": [], "reason": "unrecognized"}
    assert counterparts_for({"status": "matched"}, RULES) == {"counterparts": [], "reason": "no_department"}


def test_own_address_omission_ignores_case_and_plus_tag():
    res = counterparts_for(attrs_of("murabbi.syracuse@atfalusa.org"), RULES, own_email="  Atfal+Test@MKAUSA.org ")
    assert "atfal@mkausa.org" not in emails(res)
    assert len(res["counterparts"]) == 2


def test_region_without_a_mailbox_slug_gets_no_regional_row():
    attrs = {"status": "matched", "department": "tabligh", "role": "nazim_dept", "level": "local", "majlis": "Muqami", "region": "Muqami"}
    assert MAJLIS_TO_REGION["Muqami"] == "Muqami"
    res = counterparts_for(attrs, RULES, own_email="x@example.invalid")
    assert emails(res) == ["tabligh@mkausa.org"]


def test_every_emitted_mailbox_parses_back_to_the_row_it_describes():
    """Provider/parser symmetry for EVERY Majlis and department that has a national and local mailbox."""
    provider = MailboxProvider()
    checked = 0
    for majlis, region in MAJLIS_TO_REGION.items():
        for dept in RULES.department_names:
            attrs = {"status": "matched", "department": dept, "role": "murabbi_atfal" if dept == "atfal" else "regional_nazim_dept",
                     "level": "local", "majlis": majlis, "region": region}
            for row in provider.for_viewer(attrs, RULES):
                parsed = parse_identity(row["email"], RULES)
                assert parsed.status == "matched", row
                assert parsed.level == row["level"], row
                if row["level"] == "national":
                    assert parsed.department == dept
                elif row["level"] == "regional":
                    assert parsed.role == "regional_qaid" and parsed.region == region
                else:
                    assert parsed.department == dept and parsed.majlis == majlis
                assert row["role_title"] == parsed.role_title, row
                checked += 1
    assert checked > 100


def test_mailboxes_follow_the_rules_data_not_code():
    raw = copy.deepcopy(RULES.raw)
    nat = raw["domains"]["mkausa.org"]["national_exact"]
    nat["tabligh-head"] = nat.pop("tabligh")
    raw["domains"]["mkausa.org"]["local_prefixes"]["regionalqaid"] = raw["domains"]["mkausa.org"]["local_prefixes"].pop("qaid")
    custom = IdentityRules.from_dict(raw, MAJLIS_TO_REGION)
    attrs = {"status": "matched", "department": "tabligh", "role": "nazim_dept", "level": "regional", "region": "Northeast"}
    assert emails(counterparts_for(attrs, custom, own_email="x@example.invalid")) == [
        "tabligh-head@mkausa.org", "regionalqaid.northeast@mkausa.org",
    ]
    del raw["domains"]["mkausa.org"]["local_prefixes"]["regionalqaid"]["regional"]  # no regional-qaid mailbox convention left
    custom = IdentityRules.from_dict(raw, MAJLIS_TO_REGION)
    assert emails(counterparts_for(attrs, custom, own_email="x@example.invalid")) == ["tabligh-head@mkausa.org"]


def test_domain_slug_alias_is_used_for_the_mailbox():
    # atfalusa.org addresses Syracuse-Binghamton as "syracuse" (domain slug alias); mkausa.org would use the generated slug.
    attrs = {"status": "matched", "department": "atfal", "role": "murabbi_atfal", "level": "local", "majlis": "Syracuse-Binghamton", "region": "Northeast"}
    assert "nazim.syracuse@atfalusa.org" in emails(counterparts_for(attrs, RULES, own_email="x@example.invalid"))


def test_custom_provider_can_supply_names():
    class Named:
        def for_viewer(self, attrs, rules):
            return [{"level": "national", "role_title": "Mohtamim Tabligh", "email": "t@example.invalid", "name": "Synthetic Person", "department": "tabligh"}]

    res = counterparts_for(attrs_of("tabligh.albany@mkausa.org"), RULES, own_email="a@example.invalid", provider=Named())
    assert res["counterparts"][0]["name"] == "Synthetic Person"


@pytest.mark.parametrize("own", [None, ""])
def test_no_own_email_keeps_every_row(own):
    res = counterparts_for(attrs_of("murabbi.syracuse@atfalusa.org"), RULES, own_email=own)
    assert len(res["counterparts"]) == 3
