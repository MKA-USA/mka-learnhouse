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
        ("regional", "Regional Nazim Tabligh", "tabligh.northeast@mkausa.org", "tabligh"),
        ("regional", "Regional Qaid", "qaid.northeast@mkausa.org", None),
    ]
    assert all(r["name"] is None for r in res["counterparts"])


def test_local_row_appears_for_a_different_role_in_the_department():
    res = result("murabbi.syracuse@atfalusa.org")
    assert [(r["level"], r["role_title"], r["email"]) for r in res["counterparts"]] == [
        ("national", "Mohtamim Atfal", "atfal@mkausa.org"),
        ("regional", "Regional Qaid", "qaid.northeast@mkausa.org"),  # atfalusa.org has no regional pattern: no regional Atfal row
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


def test_regional_qaid_has_no_department_contacts_and_is_not_applicable():
    res = result("qaid.northeast@mkausa.org")
    assert res == {"counterparts": [], "reason": "not_applicable"}


def test_sadr_and_national_staff_are_not_applicable():
    for email in ("sadr@mkausa.org", "legal@mkausa.org"):
        assert result(email) == {"counterparts": [], "reason": "not_applicable"}


def test_no_department_reason_is_only_for_partial_viewers():
    partial = {"status": "partial", "role": "nazim_dept", "department": None, "level": None}
    assert counterparts_for(partial, RULES) == {"counterparts": [], "reason": "no_department"}
    assert counterparts_for({**partial, "status": "matched", "level": "regional", "role": "regional_qaid"}, RULES)["reason"] == "not_applicable"


def test_viewer_never_gets_a_row_for_their_own_office_even_with_a_different_account_address():
    # e2e finding: a Mohtamim Tabligh whose ACCOUNT address is not tabligh@ was told to contact tabligh@
    holder = {"status": "matched", "department": "tabligh", "role": "mohtamim", "level": "national", "majlis": None, "region": None}
    res = counterparts_for(holder, RULES, own_email="some.person@example.invalid")
    assert res == {"counterparts": [], "reason": None}
    # a different office in the same department still gets the department head
    nazim = {**holder, "role": "nazim_dept", "level": "regional", "region": "Northeast"}
    assert "tabligh@mkausa.org" in emails(counterparts_for(nazim, RULES, own_email="some.person@example.invalid"))
    # another department's head is a legitimate contact
    other = {**holder, "department": "maal"}
    assert emails(counterparts_for(other, RULES, own_email="x@example.invalid")) == []  # their own office
    local_maal = {"status": "matched", "department": "maal", "role": "nazim_dept", "level": "local", "majlis": "Albany", "region": "Northeast"}
    assert "maal@mkausa.org" in emails(counterparts_for(local_maal, RULES, own_email="x@example.invalid"))
    # the Muqami office holder: neither the national nor the chapter-Qaid row is their own counterpart
    muqami = {"status": "matched", "department": "muqami", "role": "mohtamim", "level": "national", "majlis": "Muqami", "region": "Muqami"}
    assert counterparts_for(muqami, RULES, own_email="some.person@example.invalid") == {"counterparts": [], "reason": None}


def test_national_head_sees_nothing_when_all_rows_are_themselves():
    res = result("tabligh@mkausa.org")
    assert res == {"counterparts": [], "reason": None}


def test_national_head_with_a_different_account_address_still_gets_no_row_for_their_own_office():
    res = counterparts_for(attrs_of("tabligh@mkausa.org"), RULES, own_email="someone.else@example.invalid")
    assert res == {"counterparts": [], "reason": None}


def test_regional_department_nazim_gets_national_and_regional_qaid_not_themselves():
    res = result("tabligh.northeast@mkausa.org")
    assert [r["level"] for r in res["counterparts"]] == ["national", "regional"]
    assert emails(res) == ["tabligh@mkausa.org", "qaid.northeast@mkausa.org"]


def test_regional_nazim_row_for_a_viewer_without_a_matching_own_role():
    # a national head in a region: both regional rows, department one first
    attrs = {"status": "matched", "department": "maal", "role": "national_staff", "level": "national", "region": "Gulf"}
    res = counterparts_for(attrs, RULES, own_email="x@example.invalid")
    assert [(r["role_title"], r["email"]) for r in res["counterparts"]] == [
        ("Mohtamim Maal", "maal@mkausa.org"), ("Regional Nazim Maal", "maal.gulf@mkausa.org"), ("Regional Qaid", "qaid.gulf@mkausa.org"),
    ]


def test_regional_nazim_row_omits_own_address():
    attrs = attrs_of("maal.gulf@mkausa.org")
    assert attrs["role"] == "regional_nazim_dept"
    res = counterparts_for(attrs, RULES, own_email="maal.gulf@mkausa.org")
    assert emails(res) == ["maal@mkausa.org", "qaid.gulf@mkausa.org"]
    # a local nazim of the same department in that region is not the regional nazim: they get the row
    local = counterparts_for({"status": "matched", "department": "maal", "role": "nazim_dept", "level": "local", "majlis": "Houston", "region": "Gulf"}, RULES, own_email="x@example.invalid")
    assert "maal.gulf@mkausa.org" in emails(local)


def test_muqami_chapter_qaid_is_the_national_muqami_mailbox_from_the_rules():
    # Muqami is its own region and chapter; its Qaid mailbox is muqami@ (no qaid.muqami@): the rules' national_exact region key says so
    attrs = {"status": "matched", "department": "tabligh", "role": "nazim_dept", "level": "local", "majlis": "Muqami", "region": "Muqami"}
    res = counterparts_for(attrs, RULES, own_email="x@example.invalid")
    assert [(r["level"], r["email"]) for r in res["counterparts"]] == [("national", "tabligh@mkausa.org"), ("regional", "muqami@mkausa.org")]
    parsed = parse_identity("muqami@mkausa.org", RULES)
    assert (parsed.status, parsed.level, parsed.region, parsed.majlis, parsed.department) == ("matched", "national", "Muqami", "Muqami", "muqami")
    # a local Qaid in Muqami: regional-Qaid row only
    qaid = counterparts_for({"status": "matched", "role": "qaid", "level": "local", "majlis": "Muqami", "region": "Muqami"}, RULES, own_email="x@example.invalid")
    assert emails(qaid) == ["muqami@mkausa.org"] and qaid["counterparts"][0]["role_title"] == "Regional Qaid"


def test_muqami_department_viewers_get_national_mohtamim_muqami_once():
    attrs = {"status": "matched", "department": "muqami", "role": "national_staff", "level": "national", "majlis": "Muqami", "region": "Muqami"}
    assert counterparts_for(attrs, RULES, own_email="x@example.invalid")["counterparts"] == [
        {"level": "national", "role_title": "Mohtamim Muqami", "email": "muqami@mkausa.org", "name": None, "department": "muqami"}]  # not twice
    assert counterparts_for(attrs, RULES, own_email="muqami@mkausa.org") == {"counterparts": [], "reason": None}  # the office holder: nobody else to contact
    assert emails(result("muqami@mkausa.org")) == []


def test_new_york_metro_regional_qaid_mailbox_is_qaid_newyorkmetro():
    attrs = {"status": "matched", "department": "maal", "role": "national_staff", "level": "local", "majlis": "Brooklyn", "region": "New York Metro"}
    assert MAJLIS_TO_REGION["Brooklyn"] == "New York Metro"
    got = counterparts_for(attrs, RULES, own_email="x@example.invalid")["counterparts"]
    assert [(r["level"], r["email"]) for r in got] == [
        ("national", "maal@mkausa.org"), ("regional", "maal.newyorkmetro@mkausa.org"), ("regional", "qaid.newyorkmetro@mkausa.org"), ("local", "maal.brooklyn@mkausa.org")]
    for r in got:
        assert parse_identity(r["email"], RULES).status == "matched", r  # all parse; newyorkmetro.region@ is an extra alias, never emitted
    assert parse_identity("newyorkmetro.region@mkausa.org", RULES).role == "regional_qaid"
    assert all("newyorkmetro.region" not in r["email"] for r in got)


def test_atfal_never_gets_a_regional_department_row():
    attrs = {"status": "matched", "department": "atfal", "role": "murabbi_atfal", "level": "local", "majlis": "Houston", "region": "Gulf"}
    rows = counterparts_for(attrs, RULES, own_email="x@example.invalid")["counterparts"]
    assert [r["role_title"] for r in rows] == ["Mohtamim Atfal", "Regional Qaid", "Nazim Atfal"]


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
    assert counterparts_for({"status": "matched"}, RULES) == {"counterparts": [], "reason": "not_applicable"}


def test_own_address_omission_ignores_case_and_plus_tag():
    res = counterparts_for(attrs_of("murabbi.syracuse@atfalusa.org"), RULES, own_email="  Atfal+Test@MKAUSA.org ")
    assert "atfal@mkausa.org" not in emails(res)
    assert len(res["counterparts"]) == 2


def test_region_without_a_mailbox_slug_or_office_gets_no_regional_row():
    attrs = {"status": "matched", "department": "tabligh", "role": "nazim_dept", "level": "local", "majlis": "Nowhere", "region": "Unmapped Region"}
    res = counterparts_for(attrs, RULES, own_email="x@example.invalid")
    assert emails(res) == ["tabligh@mkausa.org"]


def test_every_emitted_mailbox_parses_back_to_the_row_it_describes():
    """Provider/parser symmetry for EVERY Majlis and department that has a national and local mailbox."""
    provider = MailboxProvider()
    checked = 0
    emitted_regional_dept: set[str] = set()
    emitted_office: set[str] = set()
    for majlis, region in MAJLIS_TO_REGION.items():
        for dept in RULES.department_names:
            attrs = {"status": "matched", "department": dept, "role": "murabbi_atfal" if dept == "atfal" else "regional_nazim_dept",
                     "level": "local", "majlis": majlis, "region": region}
            for row in provider.for_viewer(attrs, RULES):
                parsed = parse_identity(row["email"], RULES)
                assert parsed.status == "matched", row
                office = row["level"] == "regional" and row["email"].split("@")[0] in RULES.domains["mkausa.org"]["national_exact"]
                assert parsed.level == ("national" if office else row["level"]), row  # muqami@: national Mohtamim AND the Muqami chapter Qaid
                if row["level"] == "national":
                    assert parsed.department == dept
                elif row["level"] == "regional" and row["department"]:
                    assert parsed.role in ("regional_nazim_dept", "regional_motamid") and parsed.department == dept and parsed.region == region
                    emitted_regional_dept.add(dept)
                elif office:
                    assert parsed.region == region == "Muqami" and parsed.majlis == "Muqami"
                    emitted_office.add(row["email"])
                elif row["level"] == "regional":
                    assert parsed.role == "regional_qaid" and parsed.region == region
                else:
                    assert parsed.department == dept and parsed.majlis == majlis
                assert office or row["role_title"] == parsed.role_title, row
                checked += 1
    assert checked > 100
    assert emitted_office == {"muqami@mkausa.org"}
    assert "atfal" not in emitted_regional_dept and "tabligh" in emitted_regional_dept and len(emitted_regional_dept) == 20


def test_mailboxes_follow_the_rules_data_not_code():
    raw = copy.deepcopy(RULES.raw)
    nat = raw["domains"]["mkausa.org"]["national_exact"]
    nat["tabligh-head"] = nat.pop("tabligh")
    raw["domains"]["mkausa.org"]["local_prefixes"]["regionalqaid"] = raw["domains"]["mkausa.org"]["local_prefixes"].pop("qaid")
    custom = IdentityRules.from_dict(raw, MAJLIS_TO_REGION)
    attrs = {"status": "matched", "department": "tabligh", "role": "nazim_dept", "level": "regional", "region": "Northeast"}
    assert emails(counterparts_for(attrs, custom, own_email="x@example.invalid")) == [
        "tabligh-head@mkausa.org", "tabligh.northeast@mkausa.org", "regionalqaid.northeast@mkausa.org",
    ]
    del raw["domains"]["mkausa.org"]["local_prefixes"]["regionalqaid"]["regional"]  # no regional-qaid mailbox convention left
    custom = IdentityRules.from_dict(raw, MAJLIS_TO_REGION)
    assert emails(counterparts_for(attrs, custom, own_email="x@example.invalid")) == ["tabligh-head@mkausa.org", "tabligh.northeast@mkausa.org"]


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
