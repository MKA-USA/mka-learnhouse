"""MKA fork: audience rule validation + evaluation (contract section 1). Runs the SHARED vectors (the web
evaluator runs the same file) plus Python-specific edge cases."""

import copy
import json
from pathlib import Path

import pytest

from src.services.mka.audience_eval import (
    NULL_VIEWER,
    effective_viewer,
    evaluate_rule,
    validate_rule,
)

VECTORS = json.loads((Path(__file__).parent / "vectors" / "audience_vectors.json").read_text(encoding="utf-8"))
VIEWERS = VECTORS["viewers"]


@pytest.mark.parametrize("case", VECTORS["evaluate"], ids=lambda c: c["name"])
def test_evaluate_vectors(case):
    assert evaluate_rule(case["rule"], VIEWERS[case["viewer"]]) is case["expect"]


@pytest.mark.parametrize("case", VECTORS["validate"], ids=lambda c: c["name"])
def test_validate_vectors(case):
    ok, result = validate_rule(case["rule"])
    assert ok is case["ok"], result
    if case["ok"]:
        if "normalized" in case:
            assert result == case["normalized"]
    else:
        assert isinstance(result, str) and result


def test_vector_file_is_well_formed():
    assert len(VECTORS["evaluate"]) >= 44 + 15
    assert len(VECTORS["validate"]) >= 26 + 15
    names = [c["name"] for c in VECTORS["evaluate"]]
    assert len(names) == len(set(names)), "duplicate evaluate vector names"
    for c in VECTORS["evaluate"]:
        assert c["viewer"] in VIEWERS


def test_validate_does_not_mutate_input():
    raw = {"v": 1, "mode": "show", "groups": [{"level": ["local", "local"], "majlis": []}], "extra": 1}
    snapshot = copy.deepcopy(raw)
    ok, rule = validate_rule(raw)
    assert ok
    assert raw == snapshot
    rule["groups"][0]["level"].append("x")  # the normalized rule is independent of the input
    assert raw == snapshot


def test_bool_is_not_an_integer_version():
    assert validate_rule({"v": True, "mode": "show", "groups": [{}]})[0] is False
    assert validate_rule({"v": False, "mode": "show", "groups": [{}]})[0] is False


def test_integral_float_version_matches_javascript_number_isinteger():
    ok, rule = validate_rule({"v": 1.0, "mode": "show", "groups": [{}]})
    assert ok and rule["v"] == 1 and isinstance(rule["v"], int)
    assert validate_rule({"v": float("nan"), "mode": "show", "groups": [{}]})[0] is False
    assert validate_rule({"v": float("inf"), "mode": "show", "groups": [{}]})[0] is False


def test_validate_never_raises_on_hostile_values():
    deep: list = []
    cur = deep
    for _ in range(5000):
        nxt: list = []
        cur.append(nxt)
        cur = nxt
    for raw in (deep, {"v": 1, "mode": "show", "groups": [{"gender": deep}]}, object(), b"x", {1: 2}, {"v": 1, "mode": ["show"], "groups": [{}]}):
        ok, result = validate_rule(raw)
        assert isinstance(ok, bool)
        if not ok:
            assert isinstance(result, str)


def test_unhashable_mode_does_not_raise():
    assert validate_rule({"v": 1, "mode": {"a": 1}, "groups": [{}]})[0] is False


def test_evaluate_never_raises_on_hostile_viewers():
    rule = {"v": 1, "mode": "show", "groups": [{"level": ["local"]}]}
    for viewer in ("matched", 5, [], {"status": ["matched"]}, {"status": "matched", "level": ["local"]}, {"status": "matched", "is_officeholder": "true", "level": {}}):
        assert evaluate_rule(rule, viewer) is False


def test_effective_viewer_shapes():
    assert effective_viewer(None) == NULL_VIEWER
    assert NULL_VIEWER["signed_in"] is False
    assert all(NULL_VIEWER[k] is None for k in ("is_officeholder", "level", "department", "role", "region", "majlis"))
    stale = effective_viewer(VIEWERS["unrecognized_stale"])
    assert stale["signed_in"] is True and stale["is_officeholder"] is False and stale["level"] is None
    missing = effective_viewer(VIEWERS["unrecognized_missing_row"])
    assert missing["signed_in"] is True and missing["is_officeholder"] is None
    leftover = effective_viewer(VIEWERS["unrecognized_with_leftover_attrs"])
    assert leftover["is_officeholder"] is None and leftover["department"] is None  # true is NOT kept for unrecognized
    matched = effective_viewer(VIEWERS["local_tabligh_albany"])
    assert matched["signed_in"] is True and matched["department"] == "tabligh" and matched["majlis"] == "Albany"
    not_off = effective_viewer(VIEWERS["not_officeholder"])
    assert not_off["is_officeholder"] is False


def test_effective_viewer_does_not_alias_input():
    v = copy.deepcopy(VIEWERS["local_tabligh_albany"])
    out = effective_viewer(v)
    out["level"] = "national"
    assert v["level"] == "local"


def test_evaluate_is_pure_and_repeatable():
    rule = {"v": 1, "mode": "hide", "groups": [{"level": ["national"]}]}
    snap = copy.deepcopy(rule)
    for _ in range(3):
        assert evaluate_rule(rule, VIEWERS["local_tabligh_albany"]) is True
    assert rule == snap


# ---- performance: compiled rules scale with members, not with list length -----------------------------------------------------

def _max_rule(entries=500):
    """The biggest structurally valid rule: 20 groups x 5 list keys x 500 distinct 200-char entries (~ 20 MB: far beyond the route's cap).
    Every list ends with the value the benchmark viewers carry (except majlis, which never matches), so a naive list scan has to walk
    every list of every group for every viewer."""
    pad = "x" * 190
    tail = {"level": "local", "department": "tabligh", "role": "nazim_dept", "region": "Northeast", "majlis": "never-matches"}
    return {"v": 1, "mode": "show", "groups": [
        {k: [f"{pad}{g:02d}{k[:2]}{i:04d}"[-200:] for i in range(entries - 1)] + [tail[k]] for k in ("level", "department", "role", "region", "majlis")}
        for g in range(20)
    ]}


def test_compiled_rule_evaluates_max_size_rule_over_5000_viewers_quickly():
    import time

    from src.services.mka.audience_eval import compile_rule, evaluate_compiled

    ok, rule = validate_rule(_max_rule())
    assert ok, rule
    viewers = [{"status": "matched", "is_officeholder": True, "level": "local", "department": "tabligh", "role": "nazim_dept",
                "role_title": "x", "majlis": f"Majlis {i}", "region": "Northeast"} for i in range(5000)]
    start = time.perf_counter()
    compiled = compile_rule(rule)
    hits = sum(evaluate_compiled(compiled, v) for v in viewers)
    elapsed = time.perf_counter() - start
    assert hits == 0
    assert elapsed < 1.0, f"{elapsed:.2f}s"


def test_compiled_and_plain_evaluation_agree_on_every_vector():
    from src.services.mka.audience_eval import compile_rule, evaluate_compiled

    for case in VECTORS["evaluate"]:
        ok, rule = validate_rule(case["rule"])
        expected = case["expect"]
        got = evaluate_compiled(compile_rule(rule), VIEWERS[case["viewer"]]) if ok else False
        assert got is expected, case["name"]


# ---- prototype-ish keys are ordinary unknown keys in Python ------------------------------------------------------------------

@pytest.mark.parametrize("key", ["__proto__", "constructor", "prototype", "toString", "hasOwnProperty"])
def test_prototype_keys_are_plain_unknown_group_keys(key):
    local = VIEWERS["local_tabligh_albany"]
    rule = {"v": 1, "mode": "show", "groups": [{"level": ["local"], key: ["x"]}]}
    ok, norm = validate_rule(rule)
    assert ok and key in norm["groups"][0]
    assert evaluate_rule(rule, local) is False                                    # unknown key: group never matches
    assert evaluate_rule({**rule, "mode": "hide"}, local) is True
    assert evaluate_rule({"v": 1, "mode": "show", "groups": [{key: ["x"]}, {"level": ["local"]}]}, local) is True
    assert evaluate_rule({"v": 1, "mode": "show", "groups": [{"level": ["local"]}], key: {"level": ["national"]}}, local) is True  # top level: ignored


def test_safe_integer_version_bounds():
    for v, expected in ((2**53 - 1, True), (2**53, False), (2**53 + 1, False), (float(2**53), False), (1, True)):
        assert validate_rule({"v": v, "mode": "show", "groups": [{}]})[0] is expected, v
