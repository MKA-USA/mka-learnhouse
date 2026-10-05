"""MKA fork: audience config data file + options builder (contract s2.1)."""

import copy
import json

import pytest

from src.services.mka import audience_config as cfg_mod
from src.services.mka.attributes import PUBLIC_FIELDS
from src.services.mka.audience_eval import evaluate_rule, validate_rule
from src.services.mka.identity_parser import load_rules
from src.services.users.mka_profile import MAJLIS_TO_REGION

RULES = load_rules()
EXACT_COPY = {
    "not_secret": "Visibility is for convenience, not secrecy. Anyone enrolled can technically access this section, so don't put confidential information in it.",
    "unrecognized_note": "Parts of this lesson are tailored by role. We couldn't recognise your role from your sign-in, so you may not see everything meant for you. Contact your administrator.",
    "empty_lesson": "Nothing in this lesson applies to your role. You can mark it complete and continue.",
    "count_tooltip": "Counts members of this organization who have signed in at least once (or were added to the roster), using their current role.",
}


def raw_config():
    return json.loads(cfg_mod.CONFIG_PATH.read_text(encoding="utf-8"))


def test_shipped_config_loads_and_validates():
    cfg_mod.validate_config(raw_config(), RULES)
    assert cfg_mod.load_config()["copy"] == EXACT_COPY


def test_every_preset_passes_validate_rule_and_uses_known_values():
    for p in cfg_mod.load_config()["presets"]:
        ok, result = validate_rule(p["rule"])
        assert ok, (p["id"], result)


def test_preset_ids_and_shapes_follow_the_contract():
    presets = {p["id"]: p for p in cfg_mod.load_config()["presets"]}
    assert [p["label"] for p in presets.values()] == [
        "Local officeholders", "Regional Qaids", "National team", "Qaids & Naib Qaids", "Motamids", "My department",
    ]
    assert presets["local"]["rule"]["groups"] == [{"level": ["local"]}]
    assert presets["regional-qaids"]["rule"]["groups"] == [{"level": ["regional"], "role": ["regional_qaid"]}]
    assert presets["qaids-naib-qaids"]["rule"]["groups"] == [{"role": ["qaid", "naib_qaid"]}]
    assert presets["motamids"]["rule"]["groups"] == [{"role": ["motamid", "regional_motamid"]}]
    assert presets["my-department"]["needs_author_department"] is True
    assert all("needs_author_department" not in p for pid, p in presets.items() if pid != "my-department")


def test_every_persona_attributes_validate_against_rules():
    personas = cfg_mod.load_config()["personas"]
    assert len(personas) == 7
    for p in personas:
        assert set(p["attributes"]) == set(PUBLIC_FIELDS)
        if p["attributes"]["majlis"]:
            assert p["attributes"]["majlis"] in MAJLIS_TO_REGION
            assert MAJLIS_TO_REGION[p["attributes"]["majlis"]] == p["attributes"]["region"]
    labels = [p["label"] for p in personas]
    assert "Local Nazim Tabligh · Albany" in labels and "Regional Nazim Tabligh · Northeast" in labels and not any("Atfal" in lab for lab in labels)
    unrec = next(p for p in personas if p["attributes"]["status"] == "unrecognized")
    assert unrec["attributes"]["is_officeholder"] is None
    notoff = next(p for p in personas if p["attributes"]["status"] == "not_applicable")
    assert notoff["attributes"]["is_officeholder"] is False


def test_personas_behave_as_the_matching_presets_expect():
    cfg = cfg_mod.load_config()
    presets = {p["id"]: p["rule"] for p in cfg["presets"]}
    attrs = {p["id"]: p["attributes"] for p in cfg["personas"]}
    assert evaluate_rule(presets["local"], attrs["local-nazim-tabligh-albany"]) is True
    assert evaluate_rule(presets["local"], attrs["regional-qaid-northeast"]) is False
    assert evaluate_rule(presets["regional-qaids"], attrs["regional-qaid-northeast"]) is True
    assert evaluate_rule(presets["qaids-naib-qaids"], attrs["local-qaid-houston"]) is True
    assert evaluate_rule(presets["national-team"], attrs["mohtamim-tabligh-national"]) is True
    for rule in presets.values():  # nobody unrecognised ever matches a positive preset
        assert evaluate_rule(rule, attrs["unrecognized"]) is False
        assert evaluate_rule(rule, attrs["not-an-officeholder"]) is False


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda c: c["presets"][0]["rule"].update(mode="maybe"), "preset local"),
        (lambda c: c["presets"][0]["rule"]["groups"][0].update(level=["galactic"]), "level='galactic'"),
        (lambda c: c["presets"][0]["rule"]["groups"][0].update(department=["no_such_dept"]), "department="),
        (lambda c: c["presets"][0]["rule"]["groups"][0].update(gender=["x"]), "unknown group key"),
        (lambda c: c["presets"][0]["rule"].update(v=2), "version 1"),
        (lambda c: c["presets"].append(copy.deepcopy(c["presets"][0])), "duplicate preset"),
        (lambda c: c["personas"][0]["attributes"].update(department="no_such_dept"), "persona"),
        (lambda c: c["personas"][0]["attributes"].update(region="Gulf"), "contradicts"),
        (lambda c: c["personas"][0]["attributes"].update(role_title="Wazir"), "role_title"),
        (lambda c: c["personas"][0]["attributes"].update(majlis="Atlantis"), "persona"),
        (lambda c: c["personas"][0]["attributes"].pop("region"), "exactly the keys"),
        (lambda c: c["personas"][5]["attributes"].update(level="local"), "carries no attributes"),
        (lambda c: c["personas"][0]["attributes"].update(status="bogus"), "unknown status"),
        (lambda c: c["role_plurals"].pop("qaid"), "role_plurals"),
        (lambda c: c["role_plurals"].update(extra="Extras"), "role_plurals"),
        (lambda c: c["copy"].pop("not_secret"), "copy"),
        (lambda c: c["copy"].update(not_secret=""), "copy"),
    ],
)
def test_validate_config_rejects_bad_data(mutate, message):
    cfg = raw_config()
    mutate(cfg)
    with pytest.raises(ValueError) as exc:
        cfg_mod.validate_config(cfg, RULES)
    assert message in str(exc.value)


def test_load_config_returns_independent_copies():
    a = cfg_mod.load_config()
    a["presets"].clear()
    assert cfg_mod.load_config()["presets"]


def test_build_options_shape_and_sources():
    o = cfg_mod.build_options()
    assert set(o) == {"rules_version", "levels", "departments", "roles", "regions", "majlis", "presets", "personas", "copy"}
    assert o["rules_version"] == RULES.version
    assert o["levels"] == [{"key": "national", "label": "National"}, {"key": "regional", "label": "Regional"}, {"key": "local", "label": "Local"}]
    assert [d["key"] for d in o["departments"]] == [d["key"] for d in RULES.raw["departments"]]  # rules order
    assert len(o["departments"]) == len(RULES.raw["departments"]) == 22 and o["departments"][0] == {"key": "aitmad", "name": "Aitmad", "aka": ["General Secretary"]}
    assert next(d for d in o["departments"] if d["key"] == "tabligh")["aka"] == []
    role_keys = [r["key"] for r in o["roles"]]
    assert role_keys == [k for k in RULES.role_titles if ":" not in k]
    assert "motamid:national" not in role_keys
    by_key = {r["key"]: r for r in o["roles"]}
    assert by_key["qaid"] == {"key": "qaid", "title": "Qaid", "plural": "Qaids"}
    assert by_key["nazim_dept"]["title"] == "Nazim (department)"
    assert by_key["mohtamim"]["title"] == "Mohtamim (department)"
    assert by_key["regional_nazim_dept"]["title"] == "Regional Nazim (department)"
    assert all(r["plural"] for r in o["roles"])
    assert {r["name"] for r in o["regions"]} == set(MAJLIS_TO_REGION.values())
    assert len(o["regions"]) == len(set(MAJLIS_TO_REGION.values()))
    assert {"name": "Albany", "region": "Northeast"} in o["majlis"]
    assert len(o["majlis"]) == len(MAJLIS_TO_REGION)
    assert o["copy"] == EXACT_COPY
    json.dumps(o)  # serialisable


def test_every_rules_region_is_a_majlis_region():
    # guards the "regions: canonical names" claim the options builder relies on
    assert set(RULES.regions.values()) <= set(MAJLIS_TO_REGION.values())
