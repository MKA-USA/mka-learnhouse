"""MKA fork: audience block configuration (contract s2.1): presets, personas, copy, role plurals.

The data lives in ``audience_config.json`` (reviewed in PRs). It is validated when first loaded: a bad preset or a persona that
contradicts the identity rules raises ``ValueError`` at startup of the first request rather than serving a broken picker.
``build_options()`` assembles the ``GET /mka/attributes/options`` payload from the rules file + ``MAJLIS_TO_REGION`` + this file.
"""

from __future__ import annotations

import json
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.services.mka.attributes import PUBLIC_FIELDS
from src.services.mka.audience_eval import validate_rule
from src.services.mka.identity_parser import LEVELS, STATUSES, IdentityRules, load_rules

CONFIG_PATH = Path(__file__).resolve().parent / "audience_config.json"
COPY_KEYS = ("not_secret", "unrecognized_note", "empty_lesson", "count_tooltip")
LEVEL_LABELS = {"national": "National", "regional": "Regional", "local": "Local"}


def role_keys(rules: IdentityRules) -> list[str]:
    """Role keys in rules order. ``role:level`` entries are title-lookup keys only, never a ``role`` value."""
    return [k for k in rules.role_titles if ":" not in k]


def region_names(rules: IdentityRules) -> list[str]:
    """Every region value a viewer can carry: the rules file's regions plus the region of every Majlis (a pseudo-Majlis such as
    "Muqami" sits in a region of its own that has no ``{prefix}.{region}`` mailbox)."""
    return list(dict.fromkeys([*rules.regions.values(), *rules.majlis_to_region.values()]))


def role_display_title(rules: IdentityRules, key: str) -> str:
    """``Nazim {department}`` -> ``Nazim (department)``: the picker lists the generic role, not one department's."""
    return rules.role_titles[key].replace("{department}", "(department)").strip()


def validate_config(cfg: Any, rules: IdentityRules) -> None:
    """Raise ``ValueError`` describing the first problem found."""
    if not isinstance(cfg, dict):
        raise ValueError("audience config must be an object")

    copy_ = cfg.get("copy")
    if not isinstance(copy_, dict) or set(copy_) != set(COPY_KEYS) or not all(isinstance(copy_[k], str) and copy_[k] for k in COPY_KEYS):
        raise ValueError(f"copy must have exactly the non-empty string keys {COPY_KEYS}")

    plurals = cfg.get("role_plurals")
    keys = role_keys(rules)
    if not isinstance(plurals, dict) or set(plurals) != set(keys) or not all(isinstance(v, str) and v for v in plurals.values()):
        raise ValueError("role_plurals must have a non-empty plural for every role key in the rules file (and nothing else)")

    presets = cfg.get("presets")
    if not isinstance(presets, list) or not presets:
        raise ValueError("presets must be a non-empty list")
    seen: set[str] = set()
    for p in presets:
        if not isinstance(p, dict) or not isinstance(p.get("id"), str) or not isinstance(p.get("label"), str):
            raise ValueError("every preset needs a string id and label")
        if p["id"] in seen:
            raise ValueError(f"duplicate preset id {p['id']}")
        seen.add(p["id"])
        ok, result = validate_rule(p.get("rule"))
        if not ok:
            raise ValueError(f"preset {p['id']}: {result}")
        if result["v"] != 1:
            raise ValueError(f"preset {p['id']}: presets must use rule version 1")
        for g in result["groups"]:
            _check_group_values(f"preset {p['id']}", g, rules)

    personas = cfg.get("personas")
    if not isinstance(personas, list) or not personas:
        raise ValueError("personas must be a non-empty list")
    seen = set()
    for persona in personas:
        if not isinstance(persona, dict) or not isinstance(persona.get("id"), str) or not isinstance(persona.get("label"), str):
            raise ValueError("every persona needs a string id and label")
        if persona["id"] in seen:
            raise ValueError(f"duplicate persona id {persona['id']}")
        seen.add(persona["id"])
        _check_persona(persona["id"], persona.get("attributes"), rules)


def _check_group_values(where: str, group: dict, rules: IdentityRules) -> None:
    allowed = {
        "level": set(LEVELS),
        "department": set(rules.department_names),
        "role": set(role_keys(rules)),
        "region": set(region_names(rules)),
        "majlis": set(rules.majlis_to_region),
    }
    for key, values in group.items():
        if key == "officeholder":
            continue
        if key not in allowed:
            raise ValueError(f"{where}: unknown group key {key}")
        for value in values:
            if value not in allowed[key]:
                raise ValueError(f"{where}: {key}={value!r} is not a value in the rules file")


def _check_persona(pid: str, attrs: Any, rules: IdentityRules) -> None:
    where = f"persona {pid}"
    if not isinstance(attrs, dict) or set(attrs) != set(PUBLIC_FIELDS):
        raise ValueError(f"{where}: attributes must have exactly the keys {PUBLIC_FIELDS}")
    if attrs["status"] not in STATUSES:
        raise ValueError(f"{where}: unknown status {attrs['status']!r}")
    if attrs["is_officeholder"] not in (True, False, None):
        raise ValueError(f"{where}: is_officeholder must be true, false or null")
    if attrs["status"] not in ("matched", "partial"):
        if any(attrs[k] is not None for k in PUBLIC_FIELDS if k not in ("status", "is_officeholder")):
            raise ValueError(f"{where}: a {attrs['status']} persona carries no attributes")
        return
    if attrs["is_officeholder"] is not True:
        raise ValueError(f"{where}: a matched persona is an officeholder")
    group = {k: [attrs[k]] for k in ("level", "department", "role", "region", "majlis") if attrs[k] is not None}
    _check_group_values(where, group, rules)
    majlis = attrs["majlis"]
    if majlis is not None and attrs["region"] != rules.majlis_to_region[majlis]:
        raise ValueError(f"{where}: region {attrs['region']!r} contradicts the region of {majlis}")
    if attrs["role"] is not None:
        expected = rules.title(attrs["role"], attrs["level"], attrs["department"])
        if attrs["role_title"] != expected:
            raise ValueError(f"{where}: role_title {attrs['role_title']!r} should be {expected!r}")


@lru_cache(maxsize=1)
def _load_cached() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    validate_config(cfg, load_rules())
    return cfg


def load_config() -> dict:
    """The validated config. Callers get a deep copy: the cache is never mutated."""
    return deepcopy(_load_cached())


def build_options(rules: IdentityRules | None = None) -> dict:
    """The ``AudienceOptions`` payload (contract s2.1). Everything org-specific comes from data files."""
    rules = rules or load_rules()
    cfg = load_config()
    plurals = cfg["role_plurals"]
    return {
        "rules_version": rules.version,
        "levels": [{"key": k, "label": LEVEL_LABELS[k]} for k in LEVELS],
        "departments": [
            {"key": d["key"], "name": d["name"], "aka": list(d.get("aka", []))} for d in rules.raw.get("departments", [])
        ],
        "roles": [
            {"key": k, "title": role_display_title(rules, k), "plural": plurals[k]} for k in role_keys(rules)
        ],
        "regions": [{"name": n} for n in region_names(rules)],
        "majlis": [{"name": m, "region": r} for m, r in rules.majlis_to_region.items()],
        "presets": cfg["presets"],
        "personas": cfg["personas"],
        "copy": cfg["copy"],
    }
