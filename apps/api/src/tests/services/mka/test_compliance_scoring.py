"""MKA fork: pure compliance scoring, driven by the shared JSON vectors (also consumed by the web tests)."""

import copy
import json
from pathlib import Path

import pytest

from src.services.mka import compliance_scoring as cs

VECTORS = json.loads((Path(__file__).parent / "vectors" / "compliance_scoring.json").read_text())
CYCLE = VECTORS["cycle"]
PRESETS = VECTORS["presets"]["presets"]
BASE = VECTORS["presets"]["base"]


def build(preset: str, i: int, override: dict | None = None) -> dict:
    rec = copy.deepcopy(BASE)
    rec.update({"id": f"{preset}{i}", "email": f"{preset}{i}@example.invalid", "majlis": f"{preset}{i}"})
    rec.update(copy.deepcopy(PRESETS[preset]))
    rec.update(copy.deepcopy(override or {}))
    return rec


def records(groups: list[dict]) -> list[dict]:
    return [
        build(g["preset"], i + g.get("offset", 0), g.get("override"))
        for g in groups
        for i in range(g["count"])
    ]


def test_vectors_are_not_empty():
    for key in ("due_date", "stage", "score_learner", "attention", "self_check", "loose_match", "csv_cell"):
        assert VECTORS[key], key
    assert any(v.get("ref_parity") for v in VECTORS["attention"])


@pytest.mark.parametrize("case", VECTORS["due_date"], ids=lambda c: c["name"])
def test_due_date(case):
    assert cs.due_date(case["appointed_on"], CYCLE) == case["expect"]
    assert cs.window_start(case["appointed_on"], CYCLE) == case["window_start"]


@pytest.mark.parametrize("case", VECTORS["expected_attested"], ids=lambda c: c.get("name", c["as_of"]))
def test_expected_attested(case):
    cfg = cs.with_config(case.get("cfg"))
    assert cs.expected_attested(case["as_of"], case["start"], case["due"], cfg) == pytest.approx(case["expect"])


@pytest.mark.parametrize("case", VECTORS["stage"], ids=lambda c: c["name"])
def test_stage(case):
    assert cs.stage_of(case["record"], cs.with_config(case.get("cfg"))) == case["expect"]


@pytest.mark.parametrize("case", VECTORS["score_learner"], ids=lambda c: c["name"])
def test_score_learner(case):
    got = cs.score_learner(case["record"], CYCLE, case["as_of"])
    for key, value in case["expect"].items():
        if isinstance(value, float):
            assert got[key] == pytest.approx(value), key
        else:
            assert got[key] == value, key


@pytest.mark.parametrize("case", VECTORS["attention"], ids=lambda c: c["name"])
def test_attention(case):
    cfg = cs.with_config(case.get("cfg"))
    rows = [cs.score_learner(r, CYCLE, case["as_of"], cfg) for r in records(case["groups"])]
    att = cs.attention(cs.aggregate("x", rows, CYCLE), CYCLE, case["as_of"], cfg)
    assert att["rag"] == case["expect"]["rag"]
    assert att["score"] == pytest.approx(case["expect"]["score"])
    assert att["reasons"] == case["expect"]["reasons"]
    assert att["summary"] == case["expect"]["summary"]


@pytest.mark.parametrize("case", VECTORS["self_check"], ids=lambda c: c["name"])
def test_self_check(case):
    assert cs.evaluate_self_check(case["answers"], case["expected"]) == case["expect"]


@pytest.mark.parametrize("case", VECTORS["loose_match"], ids=lambda c: f"{c['expected']}|{c['got']}")
def test_loose_match(case):
    assert cs.loose_match(case["expected"], case["got"]) is case["expect"]


@pytest.mark.parametrize("case", VECTORS["csv_cell"], ids=lambda c: repr(c["value"]))
def test_csv_cell(case):
    assert cs.csv_cell(case["value"]) == case["expect"]


# ---- behaviour not expressed as vectors -------------------------------------------------------

def test_attention_ranking_puts_red_before_amber_then_score():
    red = ({"score": 40, "rag": "red"}, {"expected": 5, "key": "a"})
    amber = ({"score": 90, "rag": "amber"}, {"expected": 5, "key": "b"})
    ranked = sorted([amber, red], key=lambda x: cs.attention_sort_key(*x))
    assert ranked[0] is red


def test_aggregate_counts_partition_expected_and_overdue_is_an_overlay():
    rows = [cs.score_learner(r, CYCLE, "2026-12-05") for r in records([
        {"count": 2, "preset": "attested"}, {"count": 3, "preset": "not_started", "offset": 10},
        {"count": 4, "preset": "not_signed_in", "offset": 20}, {"count": 1, "preset": "in_progress", "offset": 30},
    ])]
    agg = cs.aggregate("x", rows, CYCLE)
    assert agg["expected"] == 10
    assert (agg["attested"], agg["not_started"], agg["not_signed_in"], agg["in_progress"]) == (2, 3, 4, 1)
    assert agg["attested"] + agg["completed"] + agg["in_progress"] + agg["not_started"] + agg["not_signed_in"] == 10
    assert agg["overdue"] == 8  # everyone not attested is past the 2026-12-01 deadline
    assert agg["signed_in"] == 6 and agg["started"] == 3


def test_cross_tab_only_has_non_empty_cells():
    rows = [cs.score_learner(r, CYCLE, "2026-11-16") for r in records([{"count": 3, "preset": "not_started"}])]
    for r, region in zip(rows, ("East", "East", "Gulf")):
        r["region"] = region
    cells = cs.cross_tab(rows, "department_slug", "region", CYCLE)
    assert len(cells) == 2
    assert cells[cs.cell_key("tabligh", "East")]["expected"] == 2


def test_with_config_does_not_mutate_defaults():
    cfg = cs.with_config({"thresholds": {"amber": 99}})
    assert cfg["thresholds"]["amber"] == 99
    assert cs.DEFAULT_CONFIG["thresholds"]["amber"] == 10


def test_build_trend_is_cumulative_and_stops_at_as_of():
    series = cs.build_trend(
        completed_days=["2026-11-02", "2026-11-02T10:00:00", "2026-10-15", None, "2026-12-30"],
        attested_days=["2026-11-03"], expected=4, cycle=CYCLE, as_of="2026-11-04",
    )
    assert [p["date"] for p in series] == ["2026-11-01", "2026-11-02", "2026-11-03", "2026-11-04"]
    # the pre-cycle event folds into day 1; the future event is ignored
    assert [p["completed"] for p in series] == [1, 3, 3, 3]
    assert [p["attested"] for p in series] == [0, 0, 1, 1]
    assert series[0]["expected_attested"] == 0 and series[-1]["expected_attested"] == pytest.approx(0.4)


def test_build_trend_edge_cases():
    assert cs.build_trend([], [], 3, CYCLE, "2026-10-01") == []
    long = cs.build_trend([], [], 3, {**CYCLE, "starts_on": "2020-01-01"}, "2026-11-01")
    assert len(long) == cs.MAX_TREND_DAYS


def test_attention_is_neutral_before_cycle_starts():
    groups = [{"count": 3, "preset": "not_started"}]
    before = (cs.to_date(CYCLE["starts_on"]).fromordinal(cs.to_date(CYCLE["starts_on"]).toordinal() - 5)).isoformat()
    rows = [cs.score_learner(r, CYCLE, before) for r in records(groups)]
    att = cs.attention(cs.aggregate("x", rows, CYCLE), CYCLE, before)
    assert att["rag"] == "not_started"
    assert att["score"] == 0 and att["reasons"] == []
    assert cs.rag_severity(att["rag"]) == 0
    # on the start day the normal scoring applies again
    rows = [cs.score_learner(r, CYCLE, CYCLE["starts_on"]) for r in records(groups)]
    assert cs.attention(cs.aggregate("x", rows, CYCLE), CYCLE, CYCLE["starts_on"])["rag"] != "not_started"


# ---- Majlis Plan (third course kind): Qaideen and Naib Qaideen need general + majlis-plan --------------------------

@pytest.mark.parametrize("title,dept,expected", [
    ("Qaid", "", True), ("Naib Qaid", "", True), ("Naib Qaid I", "", True), ("Naib Qaid II", "", True), ("Naib Qaid III", "", True),
    ("Naib Qaid 2", "", True), ("Regional Qaid", "", True), ("  regional   QAID ", "", True), ("Mohtamim Muqami", "", True),
    ("Mohtamim Muqami", "tabligh", False), ("Sadr", "", False), ("Naib Sadr", "", False), ("Nazim Tabligh", "tabligh", False),
    ("Mohtamim Tabligh", "tabligh", False), ("Qaid Tabligh", "tabligh", False), ("National staff (it)", "", False), ("", "", False), (None, "", False),
])
def test_requires_majlis_plan(title, dept, expected):
    assert cs.requires_majlis_plan(title, dept) is expected


def _course(attested):
    return {"enrolled": True, "lessons_done": 3, "lessons_total": 3, "completed_at": "2026-11-10",
            "attested_at": "2026-11-12" if attested else None, "quiz_scores": [], "last_activity_at": "2026-11-12"}


def _qaid(general, plan, required=True):
    return {"signed_in": True, "department_slug": "", "general": _course(general), "dept_course": None,
            "majlis_plan": _course(plan), "majlis_plan_required": required, "general_required": True, "dept_required": False}


def test_qaid_is_attested_only_when_both_general_and_majlis_plan_are_signed():
    cfg = cs.with_config({"attested_requires": "both"})
    assert cs.stage_of(_qaid(True, False), cfg) == "completed"
    assert cs.stage_of(_qaid(False, True), cfg) == "completed"
    assert cs.stage_of(_qaid(True, True), cfg) == "attested"
    # not required of this person (or no such course in the cycle): general alone is enough, exactly as before
    assert cs.stage_of(_qaid(True, False, required=False), cfg) == "attested"
    legacy = _qaid(True, False); del legacy["majlis_plan"], legacy["majlis_plan_required"]
    assert cs.stage_of(legacy, cfg) == "attested"


def test_majlis_plan_counts_in_lessons_and_last_activity():
    rec = {"id": "q", "email": "q@example.invalid", "role_title": "Qaid", "level": "local", "region": "", "majlis": "m", "appointed_on": None, **_qaid(True, False)}
    scored = cs.score_learner(rec, CYCLE, "2026-11-20")
    assert scored["lessons_total"] == 6 and scored["stage"] == "completed"
