"""MKA fork: identity parser, table-driven (spec A4 / B8)."""

import copy
import json
import random
import string

import pytest

from src.services.mka.identity_parser import (
    IdentityRules,
    MkaAttributes,
    load_rules,
    parse_identity,
)
from src.services.users.mka_profile import MAJLIS_TO_REGION

RULES = load_rules()

# Independent copy of the canonical lists so a bad rules edit cannot also fix its test.
LOCAL_DEPT_PREFIXES = {
    "tabligh": "tabligh", "tarbiyyat": "tarbiyyat", "maal": "maal",
    "sanat-o-tijarat": "sanat_o_tijarat", "sehat-e-jismani": "sehat_e_jismani",
    "ishaat": "ishaat", "khidmat-e-khalq": "khidmat_e_khalq",
    "tahrik-e-jadid": "tahrik_e_jadid", "tajneed": "tajneed", "taleem": "taleem",
    "nau-mubaeen": "nau_mubaeen", "amoomi": "amoomi",
    "amoor-e-tuluba": "amoor_e_tuluba", "waqar-e-amal": "waqar_e_amal",
    "mohasib": "mohasib", "rishtanata": "rishta_nata", "wasiyyat": "wasiyyat",
    "waqf-e-nau": "waqf_e_nau", "immigrants": "new_immigrants",
}
NATIONAL_DEPT_MAILBOXES = {**LOCAL_DEPT_PREFIXES, "atfal": "atfal"}
REGIONS = {
    "east": "East", "greatlakes": "Great Lakes", "gulf": "Gulf", "midwest": "Midwest",
    "newyorkmetro": "New York Metro", "northeast": "Northeast",
    "northwest": "Northwest", "southeast": "Southeast", "southwest": "Southwest",
    "virginia": "Virginia",
}


def _slug(name: str) -> str:
    return name.lower().replace(" ", "")


def _check(email, status, holder, level, dept, role, majlis, region, flags=(), rules=RULES):
    a = parse_identity(email, rules)
    assert (a.status, a.is_officeholder, a.level, a.department, a.role, a.majlis, a.region) == (
        status, holder, level, dept, role, majlis, region
    ), email
    for f in flags:
        assert f in a.flags, (email, f, a.flags)
    return a


M = "matched"
# (email, status, is_officeholder, level, department, role, majlis, region)
HAND_ROWS = [
    # --- every local department mailbox x Albany --------------------------------
    *[
        (f"{p}.albany@mkausa.org", M, True, "local", d, "nazim_dept", "Albany", "Northeast")
        for p, d in LOCAL_DEPT_PREFIXES.items()
    ],
    # --- every national mailbox ---------------------------------------------------
    *[
        (f"{p}@mkausa.org", M, True, "national", d, "mohtamim", None, None)
        for p, d in NATIONAL_DEPT_MAILBOXES.items()
    ],
    # --- national exact, non-department -------------------------------------------
    ("sadr@mkausa.org", M, True, "national", None, "sadr", None, None),
    ("legal@mkausa.org", M, True, "national", None, "national_staff", None, None),
    ("events@mkausa.org", M, True, "national", None, "national_staff", None, None),
    ("it@mkausa.org", M, True, "national", None, "national_staff", None, None),
    ("media@mkausa.org", M, True, "national", None, "national_staff", None, None),
    ("expense@mkausa.org", M, True, "national", None, "national_staff", None, None),
    # --- Aitmad / Motamid ------------------------------------------------------------
    ("motamid@mkausa.org", M, True, "national", "aitmad", "motamid", None, None),
    ("motamid.albany@mkausa.org", M, True, "local", "aitmad", "motamid", "Albany", "Northeast"),
    ("motamid.houston@mkausa.org", M, True, "local", "aitmad", "motamid", "Houston", "Gulf"),
    # --- qaid / naib qaid ---------------------------------------------------------------
    ("qaid.albany@mkausa.org", M, True, "local", None, "qaid", "Albany", "Northeast"),
    ("naibqaid.houston@mkausa.org", M, True, "local", None, "naib_qaid", "Houston", "Gulf"),
    ("qaid.northeast@mkausa.org", M, True, "regional", None, "regional_qaid", None, "Northeast"),
    # slug collision risks resolved through the known lists
    ("qaid.virginia@mkausa.org", M, True, "regional", None, "regional_qaid", None, "Virginia"),
    ("qaid.newyorkmetro@mkausa.org", M, True, "regional", None, "regional_qaid", None, "New York Metro"),
    ("qaid.gulf@mkausa.org", M, True, "regional", None, "regional_qaid", None, "Gulf"),
    ("qaid.northvirginia@mkausa.org", M, True, "local", None, "qaid", "North Virginia", "Virginia"),
    ("qaid.southvirginia@mkausa.org", M, True, "local", None, "qaid", "South Virginia", "Virginia"),
    ("qaid.longisland@mkausa.org", M, True, "local", None, "qaid", "Long Island", "New York Metro"),
    # --- special slugs -------------------------------------------------------------------------
    ("tabligh.syracuse-binghamton@mkausa.org", M, True, "local", "tabligh", "nazim_dept", "Syracuse-Binghamton", "Northeast"),
    ("tabligh.kansascity@mkausa.org", M, True, "local", "tabligh", "nazim_dept", "Kansas City", "Midwest"),
    ("tabligh.saintlouis@mkausa.org", M, True, "local", "tabligh", "nazim_dept", "Saint Louis", "Midwest"),
    ("tabligh.siliconvalley@mkausa.org", M, True, "local", "tabligh", "nazim_dept", "Silicon Valley", "Northwest"),
    ("tabligh.losangeles@mkausa.org", M, True, "local", "tabligh", "nazim_dept", "Los Angeles", "Southwest"),
    ("tabligh.longisland@mkausa.org", M, True, "local", "tabligh", "nazim_dept", "Long Island", "New York Metro"),
    ("tabligh.northjersey@mkausa.org", M, True, "local", "tabligh", "nazim_dept", "North Jersey", "East"),
    ("tabligh.centraljersey@mkausa.org", M, True, "local", "tabligh", "nazim_dept", "Central Jersey", "East"),
    ("tabligh.northvirginia@mkausa.org", M, True, "local", "tabligh", "nazim_dept", "North Virginia", "Virginia"),
    ("tabligh.southvirginia@mkausa.org", M, True, "local", "tabligh", "nazim_dept", "South Virginia", "Virginia"),
    ("tabligh.fortworth@mkausa.org", M, True, "local", "tabligh", "nazim_dept", "Fort Worth", "Gulf"),
    ("tabligh.lasvegas@mkausa.org", M, True, "local", "tabligh", "nazim_dept", "Las Vegas", "Southwest"),
    ("tabligh.baypoint@mkausa.org", M, True, "local", "tabligh", "nazim_dept", "Bay Point", "Northwest"),
    ("tabligh.rtp@mkausa.org", M, True, "local", "tabligh", "nazim_dept", "RTP", "Virginia"),
    ("tabligh.muqami@mkausa.org", M, True, "local", "tabligh", "nazim_dept", "Muqami", "Muqami"),
    # --- Atfal on the other domain ---------------------------------------------------------------------
    ("nazim.albany@atfalusa.org", M, True, "local", "atfal", "nazim_atfal", "Albany", "Northeast"),
    ("murabbi.albany@atfalusa.org", M, True, "local", "atfal", "murabbi_atfal", "Albany", "Northeast"),
    ("nazim.syracuse@atfalusa.org", M, True, "local", "atfal", "nazim_atfal", "Syracuse-Binghamton", "Northeast"),
    ("murabbi.syracuse@atfalusa.org", M, True, "local", "atfal", "murabbi_atfal", "Syracuse-Binghamton", "Northeast"),
    ("nazim.syracuse-binghamton@atfalusa.org", M, True, "local", "atfal", "nazim_atfal", "Syracuse-Binghamton", "Northeast"),
    ("nazim.kansascity@atfalusa.org", M, True, "local", "atfal", "nazim_atfal", "Kansas City", "Midwest"),
    ("murabbi.siliconvalley@atfalusa.org", M, True, "local", "atfal", "murabbi_atfal", "Silicon Valley", "Northwest"),
    # --- naib sadr personal-name entries ------------------------------------------------------------------
    ("mahmood.kauser@mkausa.org", M, True, "national", None, "naib_sadr", None, None),
    ("ashfaq.khan@mkausa.org", M, True, "national", None, "naib_sadr", None, None),
    ("abdul.naseer@mkausa.org", M, True, "national", None, "naib_sadr", None, None),
    ("ibrahim.chaudhry@mkausa.org", M, True, "national", None, "naib_sadr", None, None),
    # --- case / whitespace / plus addressing ------------------------------------------------------------------
    ("Tabligh.Albany@MKAUSA.ORG", M, True, "local", "tabligh", "nazim_dept", "Albany", "Northeast"),
    ("  tabligh.albany@mkausa.org  ", M, True, "local", "tabligh", "nazim_dept", "Albany", "Northeast"),
    ("\ttabligh.albany@mkausa.org\n", M, True, "local", "tabligh", "nazim_dept", "Albany", "Northeast"),
    ("tabligh.albany+x@mkausa.org", M, True, "local", "tabligh", "nazim_dept", "Albany", "Northeast"),
    ("QAID.NORTHEAST+training@mkausa.org", M, True, "regional", None, "regional_qaid", None, "Northeast"),
    ("sadr+test@mkausa.org", M, True, "national", None, "sadr", None, None),
    ("NAZIM.Syracuse@AtfalUSA.org", M, True, "local", "atfal", "nazim_atfal", "Syracuse-Binghamton", "Northeast"),
    # --- rishtanata: parsed as Rishta Nata, flagged ---------------------------------------------------------------
    ("rishtanata.albany@mkausa.org", M, True, "local", "rishta_nata", "nazim_dept", "Albany", "Northeast"),
    # --- partial: role known, slug unknown / unconfirmed -------------------------------------------------------------
    ("tabligh.atlantis@mkausa.org", "partial", True, None, "tabligh", "nazim_dept", None, None),
    ("qaid.atlantis@mkausa.org", "partial", True, None, None, "qaid", None, None),
    ("tabligh.newyorkmetro-region@mkausa.org", "partial", True, None, "tabligh", "nazim_dept", None, None),
    ("qaid.newyorkmetro-region@mkausa.org", "partial", True, None, None, "qaid", None, None),
    ("naibqaid.northeast@mkausa.org", "partial", True, None, None, "naib_qaid", None, None),
    ("tabligh.northeast@mkausa.org", "partial", True, None, "tabligh", "nazim_dept", None, None),
    ("tabligh.syracuse@mkausa.org", "partial", True, None, "tabligh", "nazim_dept", None, None),
    ("nazim.atlantis@atfalusa.org", "partial", True, None, "atfal", "nazim_atfal", None, None),
    ("nazim.northeast@atfalusa.org", "partial", True, None, "atfal", "nazim_atfal", None, None),
    ("muqami@mkausa.org", "partial", True, None, None, None, None, None),
    # --- unrecognized: officeholder domain, no rule -------------------------------------------------------------------
    ("john.smith@mkausa.org", "unrecognized", None, None, None, None, None, None),
    ("jsmith@mkausa.org", "unrecognized", None, None, None, None, None, None),
    ("a.b.c@mkausa.org", "unrecognized", None, None, None, None, None, None),
    ("tabligh.albany.extra@mkausa.org", "unrecognized", None, None, None, None, None, None),
    ("bogus.albany@mkausa.org", "unrecognized", None, None, None, None, None, None),
    ("nazim.albany@mkausa.org", "unrecognized", None, None, None, None, None, None),   # nazim only on atfalusa.org
    ("tabligh.albany@atfalusa.org", "unrecognized", None, None, None, None, None, None),  # tabligh only on mkausa.org
    ("qaid.albany@atfalusa.org", "unrecognized", None, None, None, None, None, None),
    ("sadr@atfalusa.org", "unrecognized", None, None, None, None, None, None),
    ("atfal@atfalusa.org", "unrecognized", None, None, None, None, None, None),
    ("tabligh.@mkausa.org", "unrecognized", None, None, None, None, None, None),
    (".albany@mkausa.org", "unrecognized", None, None, None, None, None, None),
    ("tabligh..albany@mkausa.org", "unrecognized", None, None, None, None, None, None),
    ("tabligh.al bany@mkausa.org", "unrecognized", None, None, None, None, None, None),
    ("+x@mkausa.org", "unrecognized", None, None, None, None, None, None),
    ("tabligh.Albany-x@mkausa.org", "partial", True, None, "tabligh", "nazim_dept", None, None),
    # --- not applicable: other domains --------------------------------------------------------------------------------------
    ("someone@gmail.com", "not_applicable", False, None, None, None, None, None),
    ("tabligh.albany@gmail.com", "not_applicable", False, None, None, None, None, None),
    ("tabligh.albany@mkausa.com", "not_applicable", False, None, None, None, None, None),
    ("tabligh.albany@mail.mkausa.org", "not_applicable", False, None, None, None, None, None),   # subdomain
    ("tabligh.albany@mkausa.org.evil.com", "not_applicable", False, None, None, None, None, None),
    ("tabligh.albany@evilmkausa.org", "not_applicable", False, None, None, None, None, None),
    ("nazim.albany@atfalusa.com", "not_applicable", False, None, None, None, None, None),
    ("sadr@example.org", "not_applicable", False, None, None, None, None, None),
    # --- malformed ------------------------------------------------------------------------------------------------------------
    ("", "unrecognized", None, None, None, None, None, None),
    ("   ", "unrecognized", None, None, None, None, None, None),
    ("a@@b", "unrecognized", None, None, None, None, None, None),
    ("@mkausa.org", "unrecognized", None, None, None, None, None, None),
    ("tabligh.albany@", "unrecognized", None, None, None, None, None, None),
    ("tabligh.albany", "unrecognized", None, None, None, None, None, None),
    ("tabligh.albany@mkausa.org@mkausa.org", "unrecognized", None, None, None, None, None, None),
    ("not an email", "unrecognized", None, None, None, None, None, None),
]

# Every Majlis as a local Qaid (expected computed independently from the map).
QAID_ROWS = [
    (f"qaid.{_slug(m)}@mkausa.org", M, True, "local", None, "qaid", m, r)
    for m, r in MAJLIS_TO_REGION.items()
]
# Every region as a Regional Qaid.
REGION_ROWS = [
    (f"qaid.{s}@mkausa.org", M, True, "regional", None, "regional_qaid", None, n)
    for s, n in REGIONS.items()
]
# Every Majlis as Atfal Nazim (alias for Syracuse covered above).
ATFAL_ROWS = [
    (f"nazim.{_slug(m)}@atfalusa.org", M, True, "local", "atfal", "nazim_atfal", m, r)
    for m, r in MAJLIS_TO_REGION.items()
]

ALL_ROWS = HAND_ROWS + QAID_ROWS + REGION_ROWS + ATFAL_ROWS


def test_matrix_size():
    assert len(ALL_ROWS) >= 150
    assert len(MAJLIS_TO_REGION) == 52


@pytest.mark.parametrize("row", ALL_ROWS, ids=[r[0] or "<empty>" for r in ALL_ROWS])
def test_parse_matrix(row):
    _check(*row)


# --- flags / titles / source -------------------------------------------------------------------------

def test_rishtanata_flagged_shared_mailbox():
    a = _check("rishtanata.albany@mkausa.org", M, True, "local", "rishta_nata", "nazim_dept", "Albany", "Northeast")
    assert "shared_mailbox_note" in a.flags
    b = parse_identity("tabligh.albany@mkausa.org", RULES)
    assert "shared_mailbox_note" not in b.flags


def test_atfal_amoor_e_tuluba_not_swapped():
    assert parse_identity("atfal@mkausa.org", RULES).department == "atfal"
    assert parse_identity("amoor-e-tuluba@mkausa.org", RULES).department == "amoor_e_tuluba"
    assert parse_identity("amoor-e-tuluba.albany@mkausa.org", RULES).department == "amoor_e_tuluba"
    # atfal has no local mkausa.org mailbox; its local roles are on atfalusa.org
    assert parse_identity("atfal.albany@mkausa.org", RULES).status == "unrecognized"


def test_muqami_needs_review():
    a = parse_identity("muqami@mkausa.org", RULES)
    assert a.status == "partial" and "needs_review" in a.flags


def test_unconfirmed_slug_needs_review():
    a = parse_identity("tabligh.newyorkmetro-region@mkausa.org", RULES)
    assert a.status == "partial" and "needs_review" in a.flags and a.majlis is None


def test_titles():
    assert parse_identity("tabligh.albany@mkausa.org", RULES).role_title == "Nazim Tabligh"
    assert parse_identity("tabligh@mkausa.org", RULES).role_title == "Mohtamim Tabligh"
    assert parse_identity("qaid.northeast@mkausa.org", RULES).role_title == "Regional Qaid"
    assert parse_identity("qaid.albany@mkausa.org", RULES).role_title == "Qaid"
    assert parse_identity("motamid@mkausa.org", RULES).role_title == "National Motamid"
    assert parse_identity("motamid.albany@mkausa.org", RULES).role_title == "Motamid"
    assert parse_identity("nazim.albany@atfalusa.org", RULES).role_title == "Nazim Atfal"
    assert parse_identity("someone@gmail.com", RULES).role_title is None


def test_source_is_parser():
    assert parse_identity("tabligh.albany@mkausa.org", RULES).source == "parser"


def test_to_dict_roundtrip_is_json_serialisable():
    d = parse_identity("tabligh.albany@mkausa.org", RULES).to_dict()
    assert json.loads(json.dumps(d)) == d
    assert set(d) == {
        "status", "is_officeholder", "level", "department", "role", "role_title",
        "majlis", "region", "source", "flags",
    }


# --- collisions ---------------------------------------------------------------------------------

def _rules_with_extra_majlis(extra: dict) -> IdentityRules:
    return IdentityRules.from_dict(
        copy.deepcopy(RULES.raw), {**MAJLIS_TO_REGION, **extra}
    )


def test_synthetic_collision_is_ambiguous_never_guessed():
    # A Majlis literally named "Gulf" collides with the Gulf region slug.
    rules = _rules_with_extra_majlis({"Gulf": "Gulf"})
    a = parse_identity("qaid.gulf@mkausa.org", rules)
    assert a.status == "ambiguous"
    assert a.level is None and a.majlis is None and a.region is None and a.role is None
    assert a.is_officeholder is True
    assert "ambiguous_slug" in a.flags
    # a non-regional prefix is unambiguous: the Majlis wins
    b = parse_identity("tabligh.gulf@mkausa.org", rules)
    assert (b.status, b.level, b.majlis) == (M, "local", "Gulf")


def test_default_rules_have_no_collisions():
    assert RULES.collisions() == []


def test_collisions_reports_overlap():
    rules = _rules_with_extra_majlis({"Virginia": "Virginia"})
    assert rules.collisions() == ["virginia"]


# --- robustness ----------------------------------------------------------------------------------

@pytest.mark.parametrize("junk", [None, 0, 1.5, [], {}, b"tabligh.albany@mkausa.org", object()])
def test_non_string_input_never_raises(junk):
    a = parse_identity(junk, RULES)
    assert isinstance(a, MkaAttributes) and a.status == "unrecognized"


def test_parser_never_raises_on_fuzz_and_is_deterministic():
    rng = random.Random(1234)
    alphabet = string.printable + "éم‮\x00"
    for _ in range(3000):
        s = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 40)))
        a = parse_identity(s, RULES)
        assert a.status in {"matched", "partial", "ambiguous", "unrecognized", "not_applicable"}
        assert parse_identity(s, RULES).to_dict() == a.to_dict()
    for _ in range(1000):
        s = rng.choice(["tabligh", "qaid", "nazim", "x", ""]) + rng.choice([".", "..", "+", ""]) + \
            rng.choice(["albany", "northeast", "", "x y"]) + rng.choice(["@mkausa.org", "@atfalusa.org", "@", ""])
        parse_identity(s, RULES)


def test_parser_swallows_internal_errors():
    broken = IdentityRules.from_dict(copy.deepcopy(RULES.raw), MAJLIS_TO_REGION)
    broken.domains = None  # type: ignore[assignment]
    assert parse_identity("tabligh.albany@mkausa.org", broken).status == "unrecognized"


def test_unicode_digits_and_lookalikes_do_not_match():
    # Cyrillic 'а' in "albany" and fullwidth '@' must not resolve.
    assert parse_identity("tabligh.аlbany@mkausa.org", RULES).status == "partial"
    assert parse_identity("tabligh.albany＠mkausa.org", RULES).status == "unrecognized"
    assert parse_identity("tаbligh.albany@mkausa.org", RULES).status == "unrecognized"


# --- rules file integrity -------------------------------------------------------------------------

def test_rules_version_and_domains():
    assert RULES.version == "2026.1"
    assert set(RULES.domains) == {"mkausa.org", "atfalusa.org"}


def test_every_rule_department_is_canonical():
    keys = {d["key"] for d in RULES.raw["departments"]}
    assert len(keys) == 21
    for dom in RULES.raw["domains"].values():
        for table in ("local_prefixes", "national_exact", "personal_mailboxes"):
            for e in dom[table].values():
                assert e.get("department") is None or e["department"] in keys


def test_every_rule_role_has_a_title():
    titles = RULES.raw["role_titles"]
    for dom in RULES.raw["domains"].values():
        for table in ("local_prefixes", "national_exact", "personal_mailboxes"):
            for e in dom[table].values():
                for r in (e.get("role"), e.get("regional")):
                    if r:
                        assert r in titles, r


def test_region_names_exist_in_majlis_map():
    assert set(RULES.raw["regions"].values()) <= set(MAJLIS_TO_REGION.values())


def test_slug_aliases_point_to_real_majlis():
    for dom in RULES.raw["domains"].values():
        for target in dom["slug_aliases"].values():
            assert target in MAJLIS_TO_REGION
    for target in RULES.raw["slug_aliases"].values():
        assert target in MAJLIS_TO_REGION


def test_amoor_e_tuluba_and_atfal_national_mailboxes_in_rules():
    nat = RULES.raw["domains"]["mkausa.org"]["national_exact"]
    assert nat["atfal"]["department"] == "atfal"
    assert nat["amoor-e-tuluba"]["department"] == "amoor_e_tuluba"
