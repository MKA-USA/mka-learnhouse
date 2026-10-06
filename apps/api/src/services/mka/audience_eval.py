"""MKA fork: audience rule validation + evaluation (contract: docs/superpowers/specs/2026-10-05-mka-audience-contracts.md s1).

Pure functions, no I/O, never raise on hostile input. The TypeScript twin (``apps/web/components/mka/audience/evaluate.ts``)
must behave identically; both run ``tests/services/mka/vectors/audience_vectors.json``.

* ``validate_rule(raw)``       -> ``(True, normalized_rule)`` | ``(False, error_message)``
* ``effective_viewer(viewer)`` -> the viewer as the evaluator sees it (unknown / unrecognized => all null)
* ``evaluate_rule(raw, viewer)`` -> bool. Invalid or newer-version rules evaluate to ``False`` (fail-safe hide).

String length limits count UTF-16 code units (what JavaScript's ``String.length`` reports) so both sides agree on astral
characters. ``bool`` is an ``int`` in Python, so it is excluded explicitly wherever an integer is required.
"""

from __future__ import annotations

from typing import Any

SUPPORTED_VERSION = 1
MAX_SAFE_INTEGER = 2**53 - 1  # JS Number.isSafeInteger bound: the TS twin cannot represent more
MAX_GROUPS = 20
MAX_LIST = 500
MAX_STRING = 200
MAX_LABEL = 500
MODES = ("show", "hide")
LIST_KEYS = ("level", "department", "role", "region", "majlis")
KNOWN_GROUP_KEYS = frozenset(("officeholder",) + LIST_KEYS)
RECOGNIZED_STATUSES = ("matched", "partial")
VIEWER_ATTRS = ("is_officeholder", "level", "department", "role", "region", "majlis")

NULL_VIEWER: dict = {"signed_in": False, **{k: None for k in VIEWER_ATTRS}}


def _utf16_len(s: str) -> int:
    return len(s.encode("utf-16-le", "surrogatepass")) // 2


def _is_int(v: Any) -> bool:
    """JSON integer: ``int`` (not ``bool``) or an integral finite float (JS cannot tell ``1.0`` from ``1``)."""
    if isinstance(v, bool):
        return False
    if isinstance(v, int):
        return True
    return isinstance(v, float) and v.is_integer()


def validate_rule(raw: Any) -> tuple[bool, Any]:
    """Structural validation + normalisation (contract s1.1). Returns ``(ok, rule | error)``; never mutates ``raw``."""
    if not isinstance(raw, dict):
        return False, "rule must be an object"
    v = raw.get("v")
    if not _is_int(v) or v < 1 or v > MAX_SAFE_INTEGER:
        return False, f"v must be an integer between 1 and {MAX_SAFE_INTEGER}"
    mode = raw.get("mode")
    if not isinstance(mode, str) or mode not in MODES:
        return False, "mode must be 'show' or 'hide'"
    groups = raw.get("groups")
    if not isinstance(groups, list) or not groups or len(groups) > MAX_GROUPS:
        return False, f"groups must be a non-empty array of at most {MAX_GROUPS}"

    out_groups: list[dict] = []
    for gi, g in enumerate(groups):
        if not isinstance(g, dict):
            return False, f"groups[{gi}] must be an object"
        og: dict = {}
        for key, val in g.items():
            if key == "officeholder":
                if not isinstance(val, bool):
                    return False, f"groups[{gi}].officeholder must be a boolean"
                og[key] = val
            elif key in LIST_KEYS:
                if not isinstance(val, list):
                    return False, f"groups[{gi}].{key} must be an array of strings"
                if len(val) > MAX_LIST:
                    return False, f"groups[{gi}].{key} has more than {MAX_LIST} entries"
                seen: set[str] = set()
                items: list[str] = []
                for item in val:
                    if not isinstance(item, str) or not item:
                        return False, f"groups[{gi}].{key} entries must be non-empty strings"
                    if _utf16_len(item) > MAX_STRING:
                        return False, f"groups[{gi}].{key} entries must be at most {MAX_STRING} characters"
                    if item not in seen:
                        seen.add(item)
                        items.append(item)
                if items:  # an empty list means "any": the key is dropped
                    og[key] = items
            else:
                og[key] = val  # unknown keys are kept: they make the group non-matching (s1.2)
        out_groups.append(og)

    rule: dict = {"v": int(v), "mode": mode, "groups": out_groups}
    if "label" in raw:
        label = raw["label"]
        if not isinstance(label, str) or _utf16_len(label) > MAX_LABEL:
            return False, f"label must be a string of at most {MAX_LABEL} characters"
        rule["label"] = label
    return True, rule


def effective_viewer(viewer: Any) -> dict:
    """The viewer as the evaluator sees it (contract s1.2.2). Always returns a fresh dict."""
    if not isinstance(viewer, dict):
        return dict(NULL_VIEWER)
    if viewer.get("status") not in RECOGNIZED_STATUSES:
        out = dict(NULL_VIEWER)
        out["signed_in"] = True
        if viewer.get("is_officeholder") is False:  # stale / not_applicable: keep the one safe fact
            out["is_officeholder"] = False
        return out
    out = {k: viewer.get(k) for k in VIEWER_ATTRS}
    out["signed_in"] = True
    return out


def compile_rule(rule: dict) -> tuple:
    """Pre-process an ALREADY validated rule for repeated evaluation: lists become frozensets (O(1) membership).

    Semantics are identical to evaluating the plain rule: a group with an unknown key is compiled to ``None`` (never matches).
    """
    groups: list = []
    for g in rule["groups"]:
        if any(key not in KNOWN_GROUP_KEYS for key in g):
            groups.append(None)
            continue
        groups.append((bool(g.get("officeholder", True)), tuple((k, frozenset(g[k])) for k in LIST_KEYS if k in g)))
    return rule["v"], rule["mode"], tuple(groups)


def _compiled_group_matches(group: tuple, v: dict) -> bool:
    holder_required, lists = group
    if holder_required:
        if v["is_officeholder"] is not True:
            return False
    elif not v["signed_in"]:
        return False
    for key, allowed in lists:
        val = v[key]
        if not isinstance(val, str) or val not in allowed:  # list entries are strings: anything else can never match
            return False
    return True


def evaluate_compiled(compiled: tuple, viewer: Any) -> bool:
    version, mode, groups = compiled
    if version > SUPPORTED_VERSION:
        return False
    v = effective_viewer(viewer)
    any_match = any(g is not None and _compiled_group_matches(g, v) for g in groups)
    return any_match if mode == "show" else not any_match


def evaluate_validated(rule: dict, viewer: Any) -> bool:
    """Evaluate an ALREADY validated + normalised rule. For many viewers, ``compile_rule`` once and use ``evaluate_compiled``."""
    return evaluate_compiled(compile_rule(rule), viewer)


def evaluate_rule(raw: Any, viewer: Any) -> bool:
    """Contract s1.2. Invalid rule => False for everyone (fail-safe hide)."""
    ok, rule = validate_rule(raw)
    if not ok:
        return False
    return evaluate_validated(rule, viewer)
