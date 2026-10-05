"""MKA fork: pure compliance scoring (no DB, no I/O). Spec 2026-10-04-mka-native-compliance-analytics §3.

Port of the reference implementation ``custom/compliance/packages/analytics`` (status.ts, aggregate.ts,
attention.ts, selfcheck.ts, csv.ts, trend.ts) with two spec additions: the ``not_signed_in`` stage (an
expected officeholder with no user row) and a configurable ``attested_requires`` (``both`` | ``any``).

Everything here is deterministic and unit-tested against the shared vectors in
``src/tests/services/mka/vectors/compliance_scoring.json`` (cases marked ``ref_parity: true`` were generated
from the TypeScript reference, the rest are hand-derived).

Record shape (all keys snake_case; mirrors the API JSON)::

    {
      "id", "email", "person_name", "department_slug" ('' = executive: general course only),
      "level", "region", "majlis", "role_title", "appointed_on",
      "signed_in": bool (default True),
      "general": course | None, "dept_course": course | None,
      "self_check": {"answered": bool, "mismatches": [str]} | None,
    }
    course = {"enrolled", "lessons_done", "lessons_total", "completed_at", "attested_at",
              "quiz_scores", "last_activity_at"}

Definitions (documented disagreements with upstream, see spec section 3 / integration-map risk 4):
* ``lessons_total`` counts PUBLISHED activities only (what ``is_course_fully_completed`` counts); the learner
  progress widget upstream counts unpublished activities too, so its totals can be larger.
* ``completed`` is derived from step counts, not from ``TrailRun.status`` (which can be stale); the raw run
  status is exposed separately by the learners endpoint for debugging.
"""

from __future__ import annotations

import copy
import math
import re
from datetime import date, timedelta
from typing import Any, Iterable, Optional

# --------------------------------------------------------------------------------------------------
# configuration (UNCONFIRMED values: tune with the owner before the first live cycle)
# --------------------------------------------------------------------------------------------------

DEFAULT_CONFIG: dict[str, Any] = {
    # Fraction of learners expected to be attested at the deadline.
    "target_at_deadline": 1.0,
    # Days allowed from appointment to completion for people appointed after the cycle started.
    "appointee_window_days": 30,
    # 'both': attested on the general AND the department course; 'any': either one.
    "attested_requires": "both",
    # score = 100 * (shortfall*w.shortfall + overdue_rate*w.overdue + min(1, 3*mismatch_rate)*w.mismatch
    #                + not_signed_in_rate*w.not_signed_in), clamped to 100.
    # The not_signed_in term is an ADDITION to the reference formula (weights above it are unchanged, so
    # cases without never-signed-in people score exactly as the reference does).
    "weights": {"shortfall": 0.6, "overdue": 0.25, "mismatch": 0.15, "not_signed_in": 0.2},
    "thresholds": {
        "amber": 10,
        "red": 25,
        "overdue_rate_red": 0.2,
        "mismatch_rate_amber": 0.1,
        "not_started_grace_days": 3,
        "not_signed_in_rate_amber": 0.25,
    },
    "noun_plural": "officeholders",
}

STAGES = ("not_signed_in", "not_started", "in_progress", "completed", "attested")
RAG_ORDER = {"red": 3, "amber": 2, "green": 1, "none": 0, "not_started": 0}


def with_config(partial: Optional[dict] = None) -> dict:
    """Deep-merge a partial override onto the defaults (never mutates the defaults)."""
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    for key, value in (partial or {}).items():
        if isinstance(value, dict) and isinstance(cfg.get(key), dict):
            cfg[key].update(value)
        else:
            cfg[key] = value
    return cfg


# --------------------------------------------------------------------------------------------------
# dates ('day' values are YYYY-MM-DD; timestamps may carry a time suffix, only the day is used)
# --------------------------------------------------------------------------------------------------

_DAY_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")


def to_date(value: Any) -> Optional[date]:
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    m = _DAY_RE.match(value.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def day_str(value: Any) -> Optional[str]:
    d = to_date(value)
    return d.isoformat() if d else None


def add_days(day: str, n: int) -> str:
    d = to_date(day)
    if d is None:
        raise ValueError(f"bad day: {day}")
    return (d + timedelta(days=n)).isoformat()


def diff_days(a: Any, b: Any) -> int:
    x, y = to_date(a), to_date(b)
    if x is None or y is None:
        return 0
    return (x - y).days


def max_day(*values: Any) -> Optional[str]:
    best: Optional[date] = None
    for v in values:
        d = to_date(v)
        if d is not None and (best is None or d > best):
            best = d
    return best.isoformat() if best else None


def median(values: list[float]) -> Optional[float]:
    if not values:
        return None
    s = sorted(values)
    m = len(s) >> 1
    return s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2


def _round_half_up(x: float) -> int:
    """JavaScript ``Math.round`` semantics (Python's round() is banker's)."""
    return int(math.floor(x + 0.5))


def _round1(x: float) -> float:
    return _round_half_up(x * 10) / 10


def _pct0(x: float) -> str:
    return f"{_round_half_up(x * 100)}%"


# --------------------------------------------------------------------------------------------------
# due dates and the expected curve
# --------------------------------------------------------------------------------------------------

def _appointed_after_start(appointed_on: Any, cycle: dict) -> bool:
    return to_date(appointed_on) is not None and diff_days(appointed_on, cycle["starts_on"]) > 0


def due_date(appointed_on: Any, cycle: dict, cfg: Optional[dict] = None) -> str:
    """The cycle deadline, or appointed_on + window for people appointed after the cycle started."""
    cfg = cfg or DEFAULT_CONFIG
    if _appointed_after_start(appointed_on, cycle):
        return add_days(day_str(appointed_on), cfg["appointee_window_days"])  # type: ignore[arg-type]
    return cycle["deadline_on"]


def window_start(appointed_on: Any, cycle: dict) -> str:
    if _appointed_after_start(appointed_on, cycle):
        return day_str(appointed_on)  # type: ignore[return-value]
    return cycle["starts_on"]


def expected_attested(as_of: str, start: str, due: str, cfg: Optional[dict] = None) -> float:
    """Expected share attested on ``as_of`` (0..target), linear from window start to due date."""
    cfg = cfg or DEFAULT_CONFIG
    target = cfg["target_at_deadline"]
    span = diff_days(due, start)
    elapsed = diff_days(as_of, start)
    if span <= 0:
        return target if elapsed >= 0 else 0
    return min(1, max(0, elapsed / span)) * target


# --------------------------------------------------------------------------------------------------
# per-learner stage / status
# --------------------------------------------------------------------------------------------------

def _present(course: Optional[dict]) -> bool:
    return bool(course) and bool(course.get("enrolled"))


def _required_courses(record: dict) -> list[Optional[dict]]:
    """The courses this person must finish. Executives (no department) only have the general course;
    a department with no cycle course (``dept_required`` false) and a cycle with no general course
    (``general_required`` false) are not required."""
    req: list[Optional[dict]] = [record.get("general")] if record.get("general_required", True) else []
    if record.get("department_slug", "") != "" and record.get("dept_required", True):
        req.append(record.get("dept_course"))
    return req


def stage_of(record: dict, cfg: Optional[dict] = None) -> str:
    cfg = cfg or DEFAULT_CONFIG
    if record.get("signed_in", True) is False:
        return "not_signed_in"
    req = _required_courses(record)
    present = [c for c in req if _present(c)]
    any_mode = cfg["attested_requires"] == "any"
    all_present = len(req) > 0 and len(present) == len(req)
    if any_mode:
        if any(c.get("attested_at") for c in present):  # type: ignore[union-attr]
            return "attested"
        done_courses = [
            c for c in present
            if c["lessons_total"] > 0 and c["lessons_done"] >= c["lessons_total"]  # type: ignore[index]
        ]
        if done_courses:
            return "completed"
    else:
        if all_present and all(c.get("attested_at") for c in present):  # type: ignore[union-attr]
            return "attested"
        total = sum(c["lessons_total"] for c in present)  # type: ignore[index]
        done = sum(c["lessons_done"] for c in present)  # type: ignore[index]
        if all_present and total > 0 and done >= total:
            return "completed"
    any_activity = any(
        _present(c) and (c["lessons_done"] > 0 or bool(c.get("attested_at")))  # type: ignore[index]
        for c in (record.get("general"), record.get("dept_course"))
    )
    return "in_progress" if any_activity else "not_started"


def score_learner(record: dict, cycle: dict, as_of: str, cfg: Optional[dict] = None) -> dict:
    """Score one learner as of ``as_of`` (YYYY-MM-DD). Pure."""
    cfg = cfg or DEFAULT_CONFIG
    stage = stage_of(record, cfg)
    due = due_date(record.get("appointed_on"), cycle, cfg)
    start = window_start(record.get("appointed_on"), cycle)
    overdue = stage != "attested" and diff_days(as_of, due) > 0
    courses = [c for c in (record.get("general"), record.get("dept_course")) if _present(c)]
    scores = [s for c in courses for s in (c.get("quiz_scores") or [])]
    attested_courses = [c.get("attested_at") for c in courses]
    attested_at = max_day(*attested_courses) if stage == "attested" else None
    completed_at = max_day(*[c.get("completed_at") for c in courses]) if stage in ("attested", "completed") else None
    sc = record.get("self_check") or {}
    return {
        "roster_id": record.get("id"),
        "email": record.get("email"),
        "person_name": record.get("person_name"),
        "department_slug": record.get("department_slug", ""),
        "level": record.get("level"),
        "region": record.get("region", ""),
        "majlis": record.get("majlis", ""),
        "role_title": record.get("role_title", ""),
        "appointed_on": record.get("appointed_on"),
        "stage": stage,
        "status": "overdue" if overdue else stage,
        "overdue": overdue,
        "lessons_done": sum(c["lessons_done"] for c in courses),
        "lessons_total": sum(c["lessons_total"] for c in courses),
        "quiz_avg": _round_half_up(sum(scores) / len(scores)) if scores else None,
        "completed_at": completed_at,
        "attested_at": attested_at,
        "last_activity_at": max_day(*[c.get("last_activity_at") for c in courses]),
        "due_on": due,
        "days_overdue": diff_days(as_of, due) if overdue else 0,
        "expected_attested": expected_attested(as_of, start, due, cfg),
        "self_check_answered": bool(sc.get("answered")),
        "self_check_mismatches": len(sc.get("mismatches") or []),
    }


# --------------------------------------------------------------------------------------------------
# aggregates and attention
# --------------------------------------------------------------------------------------------------

def _pct(a: float, n: int) -> float:
    return 0 if n == 0 else a / n


def aggregate(key: str, rows: Iterable[dict], cycle: dict) -> dict:
    rows = list(rows)
    n = len(rows)
    c = {s: 0 for s in STAGES}
    overdue = mism = mism_people = lessons_done = lessons_total = 0
    exp_sum = 0.0
    days: list[float] = []
    last: Optional[str] = None
    for r in rows:
        c[r["stage"]] += 1
        if r["overdue"]:
            overdue += 1
        mism += r["self_check_mismatches"]
        if r["self_check_mismatches"] > 0:
            mism_people += 1
        exp_sum += r["expected_attested"]
        lessons_done += r["lessons_done"]
        lessons_total += r["lessons_total"]
        last = max_day(last, r["last_activity_at"])
        if r["completed_at"]:
            days.append(max(0, diff_days(r["completed_at"], window_start(r.get("appointed_on"), cycle))))
    return {
        "key": key,
        "expected": n,
        "not_signed_in": c["not_signed_in"],
        "not_started": c["not_started"],
        "in_progress": c["in_progress"],
        "completed": c["completed"],
        "attested": c["attested"],
        "signed_in": n - c["not_signed_in"],
        "started": n - c["not_signed_in"] - c["not_started"],
        "overdue": overdue,
        "started_pct": _pct(n - c["not_signed_in"] - c["not_started"], n),
        "completed_pct": _pct(c["completed"] + c["attested"], n),
        "attested_pct": _pct(c["attested"], n),
        "expected_attested_pct": _pct(exp_sum, n),
        "median_days_to_complete": median(days),
        "last_activity_at": last,
        "self_check_mismatches": mism,
        "self_check_mismatched_people": mism_people,
        "lessons_done": lessons_done,
        "lessons_total": lessons_total,
    }


def attention(agg: dict, cycle: dict, as_of: str, cfg: Optional[dict] = None) -> dict:
    """Attention for one group (department, region, department x region cell, ...). See DEFAULT_CONFIG."""
    cfg = cfg or DEFAULT_CONFIG
    n = agg["expected"]
    if n == 0:
        return {"score": 0, "rag": "none", "shortfall": 0, "reasons": [],
                "summary": f"No {cfg['noun_plural']} in scope"}
    if diff_days(as_of, cycle["starts_on"]) < 0:  # cycle hasn't opened yet: nothing to judge, stay neutral
        return {"score": 0, "rag": "not_started", "shortfall": 0, "reasons": [], "summary": "Cycle not started"}
    shortfall = max(0, agg["expected_attested_pct"] - agg["attested_pct"])
    overdue_rate = agg["overdue"] / n
    mismatch_rate = agg["self_check_mismatches"] / n
    nsi_rate = agg["not_signed_in"] / n
    w, t = cfg["weights"], cfg["thresholds"]
    score = _round1(min(100.0, 100 * (
        w["shortfall"] * shortfall + w["overdue"] * overdue_rate
        + w["mismatch"] * min(1, 3 * mismatch_rate) + w["not_signed_in"] * nsi_rate
    )))
    rag = "red" if score >= t["red"] else "amber" if score >= t["amber"] else "green"
    if agg["overdue"] > 0 and overdue_rate >= t["overdue_rate_red"]:
        rag = "red"
    elif rag == "green" and (mismatch_rate >= t["mismatch_rate_amber"] or nsi_rate >= t["not_signed_in_rate_amber"]):
        rag = "amber"

    reasons: list[str] = []
    if agg["overdue"] > 0:
        reasons.append(f"{agg['overdue']} of {n} overdue")
    if agg["not_signed_in"] > 0 and diff_days(as_of, cycle["starts_on"]) >= t["not_started_grace_days"]:
        reasons.append(f"{agg['not_signed_in']} of {n} never signed in")
    if agg["not_started"] > 0 and diff_days(as_of, cycle["starts_on"]) >= t["not_started_grace_days"]:
        reasons.append(f"{agg['not_started']} of {n} haven't started")
    if shortfall >= 0.05:
        reasons.append(f"attested {_pct0(agg['attested_pct'])} vs {_pct0(agg['expected_attested_pct'])} expected")
    if agg["self_check_mismatches"] > 0:
        k = agg["self_check_mismatches"]
        reasons.append(f"{k} contact self-check mismatch{'' if k == 1 else 'es'}")
    summary = "; ".join(reasons) if reasons else ("On track" if rag == "green" else "Needs a look")
    return {"score": score, "rag": rag, "shortfall": shortfall, "reasons": reasons, "summary": summary}


def rag_severity(rag: str) -> int:
    return RAG_ORDER.get(rag, 0)


def attention_sort_key(att: dict, agg: dict) -> tuple:
    """Worst first: RAG, then score, then size (use as ``sorted(..., key=...)``)."""
    return (-rag_severity(att["rag"]), -att["score"], -agg["expected"], str(agg.get("key", "")))


def group_by(rows: Iterable[dict], field: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(r.get(field) or "", []).append(r)
    return out


CELL_SEP = "␟"


def cell_key(a: str, b: str) -> str:
    return f"{a}{CELL_SEP}{b}"


def cross_tab(rows: Iterable[dict], row_field: str, col_field: str, cycle: dict) -> dict[str, dict]:
    cells: dict[str, list[dict]] = {}
    for r in rows:
        cells.setdefault(cell_key(r.get(row_field) or "", r.get(col_field) or ""), []).append(r)
    return {k: aggregate(k, v, cycle) for k, v in cells.items()}


# --------------------------------------------------------------------------------------------------
# contact self-check
# --------------------------------------------------------------------------------------------------

def _norm(s: str) -> str:
    return s.lower().strip()


def _alnum(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", _norm(s))


def loose_match(expected: str, got: str) -> bool:
    """Emails compare in full, names compare alphanumerics, a titled answer ("Qaid Jane Doe") still matches."""
    if "@" in expected or "@" in got:
        return _norm(expected) == _norm(got)
    e, g = _alnum(expected), _alnum(got)
    if not e or not g:
        return False
    if e == g:
        return True
    short, long_ = (e, g) if len(e) <= len(g) else (g, e)
    return len(short) >= 4 and short in long_


SELF_CHECK_FIELDS = ("majlis", "regional_qaid", "dept_head")


def evaluate_self_check(answers: Optional[dict], expected: dict) -> dict:
    """Compare a learner's contact self-check answers with what the roster says.

    ``expected[field]`` may be a string or a list of acceptable strings. Blank answers are not mismatches
    (the learner skipped); an unanswered form is ``answered: false``; a field with no expected value is
    never a mismatch (we cannot judge it).
    """
    if not answers:
        return {"answered": False, "mismatches": []}
    given = [f for f in SELF_CHECK_FIELDS if str(answers.get(f) or "").strip() != ""]
    if not given:
        return {"answered": False, "mismatches": []}
    mismatches: list[str] = []
    for f in given:
        exp = expected.get(f)
        options = [exp] if isinstance(exp, str) else [e for e in (exp or []) if isinstance(e, str)]
        options = [o for o in options if o]
        if options and not any(loose_match(o, str(answers[f])) for o in options):
            mismatches.append(f)
    return {"answered": True, "mismatches": mismatches}


# --------------------------------------------------------------------------------------------------
# CSV (formula-injection safe)
# --------------------------------------------------------------------------------------------------

_FORMULA_LEAD = re.compile(r"^\s*[=+\-@\t\r]")


def csv_cell(value: Any) -> str:
    """Neutralise spreadsheet formula injection (=, +, -, @, tab, CR; also after leading spaces) and quote
    per RFC 4180."""
    s = "" if value is None else str(value)
    if _FORMULA_LEAD.match(s):
        s = "'" + s
    if re.search(r'[",\n\r]', s):
        s = '"' + s.replace('"', '""') + '"'
    return s


# --------------------------------------------------------------------------------------------------
# trend (cumulative counts per day)
# --------------------------------------------------------------------------------------------------

MAX_TREND_DAYS = 400


def build_trend(
    completed_days: Iterable[Optional[str]],
    attested_days: Iterable[Optional[str]],
    expected: int,
    cycle: dict,
    as_of: str,
) -> list[dict]:
    """Cumulative completed/attested per day from the cycle start to ``as_of`` (inclusive; at least to the
    deadline is NOT forced: the series stops at ``as_of``). Days outside [start, as_of] are folded into the
    first day (earlier events) or ignored (future events)."""
    start = to_date(cycle["starts_on"])
    end = to_date(as_of)
    if start is None or end is None or end < start:
        return []
    if (end - start).days >= MAX_TREND_DAYS:
        start = end - timedelta(days=MAX_TREND_DAYS - 1)
    comp_by_day: dict[date, int] = {}
    att_by_day: dict[date, int] = {}
    for src, bucket in ((completed_days, comp_by_day), (attested_days, att_by_day)):
        for raw in src:
            d = to_date(raw)
            if d is None or d > end:
                continue
            d = max(d, start)
            bucket[d] = bucket.get(d, 0) + 1
    out: list[dict] = []
    comp = att = 0
    d = start
    while d <= end:
        comp += comp_by_day.get(d, 0)
        att += att_by_day.get(d, 0)
        out.append({
            "date": d.isoformat(),
            "completed": comp,
            "attested": att,
            "expected_attested": _round1(expected * expected_attested(d.isoformat(), cycle["starts_on"], cycle["deadline_on"])),
        })
        d += timedelta(days=1)
    return out
