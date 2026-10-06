#!/usr/bin/env python3
"""Validate the provisioner's payloads against the fork's REAL compliance API code (no mock).

Usage (from custom/compliance, after `bun run lh push-cycle` and `push-roster --all` dry runs wrote out/payload-*.json):
  FORK_API_DIR=/path/to/worktree/apps/api uv run --project "$FORK_API_DIR" python scripts/validate-against-api.py

Exit code 1 on any mismatch. Prints counts only (no PII).
"""
import json, os, sys, pathlib, inspect

api_dir = os.environ.get("FORK_API_DIR")
if not api_dir:
    sys.exit("set FORK_API_DIR to the fork worktree's apps/api")
sys.path.insert(0, api_dir)
os.chdir(api_dir)
import secrets
# Import-time config only (no DB/network is touched); throwaway values generated per run.
os.environ.setdefault("LEARNHOUSE_SQL_CONNECTION_STRING", "postgresql+asyncpg://x:x@localhost/x")
os.environ.setdefault("LEARNHOUSE_AUTH_JWT_SECRET_KEY", secrets.token_urlsafe(32))

root = pathlib.Path(__file__).resolve().parents[1]
out = root / "out"
problems: list[str] = []
def bad(m): problems.append(m)

cycle_payload = json.loads((out / "payload-cycle.json").read_text())
expected = json.loads((out / "payload-expected.json").read_text())

from pydantic import ValidationError
from src.routers import mka_compliance as router_mod
from src.services.mka import compliance_import as imp
from src.services.mka import compliance as comp
from src.services.mka import attributes as attrs
from src.services.mka.identity_parser import LEVELS

# ---- 1. POST /mka/compliance/cycles -------------------------------------------------------------------------
try:
    router_mod.CyclesIn(**cycle_payload)
except ValidationError as e:
    bad(f"CyclesIn rejects the cycle payload: {e.errors()[:3]}")
if len(cycle_payload["courses"]) > imp.MAX_COURSE_ROWS:
    bad("too many courses per request")
try:
    imp._text(cycle_payload.get("cycle"), "cycle", 100, required=True)
    d = imp._parse_date(cycle_payload.get("deadline") or cycle_payload.get("deadline_on"), "deadline")
    s = imp._parse_date(cycle_payload["starts_on"], "starts_on")
    if s > d: bad("starts_on after deadline")
except ValueError as e:
    bad(f"cycle dates: {e}")
rules_depts = set(attrs.get_rules().department_names)
seen_pairs = set()
for i, c in enumerate(cycle_payload["courses"]):
    try:
        kind = imp._text(c.get("kind"), "kind", 20, required=True)
        if kind not in imp.KINDS: bad(f"course {i}: kind {kind!r} not in {imp.KINDS}")
        dept = imp.normalize_department(c.get("department")) or None
        if kind == "department" and not dept: bad(f"course {i}: department required")
        if kind == "department" and dept not in rules_depts: bad(f"course {i}: department key {dept!r} is not a rules department key")
        imp._text(c.get("course_uuid"), "course_uuid", 200, required=True)
        for key in ("signoff", "contact_check"):
            if key in c and c[key] is not None:
                if not isinstance(c[key], dict): bad(f"course {i}: {key} must be object or null")
                else: imp._text(c[key].get("assignment_uuid"), f"{key}.assignment_uuid", 200, required=True)
        pair = (kind, dept if kind == "department" else None)
        if pair in seen_pairs: bad(f"course {i}: duplicate {pair} (API: 'already has a {kind} course')")
        seen_pairs.add(pair)
    except ValueError as e:
        bad(f"course {i}: {e}")

# ---- 2. POST /mka/compliance/expected/import ----------------------------------------------------------------
rows = expected["rows"]
batch = expected["batchSize"]
if batch > imp.MAX_EXPECTED_ROWS: bad(f"batch size {batch} > API limit {imp.MAX_EXPECTED_ROWS}")
try:
    router_mod.ExpectedImportIn(cycle=expected["cycle"], rows=rows[:batch], dry_run=True)  # extra="forbid": body keys we send
except ValidationError as e:
    bad(f"ExpectedImportIn rejects a batch: {e.errors()[:3]}")
nerr = 0; keys = set(); dup = 0; titles = {}
for i, r in enumerate(rows):
    try:
        clean = imp.validate_expected_row(r)
    except ValueError as e:
        nerr += 1
        if nerr <= 5: bad(f"row {i}: {e}")
        continue
    k = (clean["email"], clean["department"], clean["level"], clean["role_title"])
    if k in keys: dup += 1
    keys.add(k)
    if clean["level"] not in LEVELS: bad(f"row {i}: level {clean['level']!r}")
    if clean["department"] and clean["department"] not in rules_depts:
        bad(f"row {i}: department key {clean['department']!r} not in the rules")
    titles.setdefault((clean["level"], clean["department"]), []).append(clean["role_title"].lower())
if nerr > 5: bad(f"... {nerr} rows rejected in total")
if dup: bad(f"{dup} duplicate (email, department, level, role_title) keys")

# ---- 3. contact-check rules: do our role_title values let the self-check comparison work? ---------------------
rule_cov = {}
for field, rule in comp.CONTACT_CHECK_RULES.items():
    hits = {d for (lvl, d), ts in titles.items() if lvl == rule["level"] and any(any(kw in t for kw in rule["role_keywords"]) for t in ts)}
    rule_cov[field] = hits
    if field == "regional_qaid":
        if not hits: bad("CONTACT_CHECK_RULES regional_qaid matches no roster row")
    else:
        missing = sorted(rules_depts - hits - {""})
        if missing: bad(f"CONTACT_CHECK_RULES dept_head ('mohtamim' title at national level) has no row for departments: {', '.join(missing)} (self-check cannot flag mismatches for them)")
# the question wording the provisioner emits must contain the API's keywords
attest = (root / "packages/core/src/templates/attestation.ts").read_text()
for field, kws in comp.CONTACT_QUESTION_KEYWORDS.items():
    if not any(kw in attest.lower() for kw in kws): bad(f"attestation.ts wording lacks any keyword of {field}: {kws}")

# ---- 4. contributor endpoints we call (upstream routes in this checkout) --------------------------------------
from src.routers.courses import courses as courses_router
from src.db.resource_authors import ResourceAuthorshipEnum, ResourceAuthorshipStatusEnum
routes = {(m, r.path): r for r in courses_router.router.routes for m in getattr(r, "methods", [])}
want = [("POST", "/{course_uuid}/bulk-add-contributors"), ("PUT", "/{course_uuid}/contributors/{contributor_user_id}"), ("GET", "/{course_uuid}/contributors")]
for key in want:
    if key not in routes: bad(f"contributor route missing: {key}")
put = routes.get(("PUT", "/{course_uuid}/contributors/{contributor_user_id}"))
if put:
    q = {p.name for p in put.dependant.query_params}
    if not {"authorship", "authorship_status"} <= q: bad(f"PUT contributors query params are {q}")
post = routes.get(("POST", "/{course_uuid}/bulk-add-contributors"))
if post and [b.name for b in post.dependant.body_params] != ["usernames"]: bad("bulk-add body is not the bare `usernames` list")
for v in ("CONTRIBUTOR",):
    if v not in ResourceAuthorshipEnum.__members__: bad("CONTRIBUTOR enum missing")
if "ACTIVE" not in ResourceAuthorshipStatusEnum.__members__: bad("ACTIVE enum missing")

# ---- 5. routes + auth query -----------------------------------------------------------------------------------
rr = {(m, r.path): r for r in router_mod.router.routes for m in getattr(r, "methods", [])}
for key in (("POST", "/cycles"), ("POST", "/expected/import")):
    r = rr.get(key)
    if not r: bad(f"route missing {key}"); continue
    if "org_slug" not in {p.name for p in r.dependant.query_params}: bad(f"{key}: no org_slug query param")

print(f"cycle courses: {len(cycle_payload['courses'])}; expected rows: {len(rows)} (batch {batch}); rules departments: {len(rules_depts)}")
print("contact-check coverage:", {k: len(v) for k, v in rule_cov.items()})
if problems:
    print(f"\n{len(problems)} MISMATCH(ES):"); [print(" -", p) for p in problems]; sys.exit(1)
print("OK: payloads match the fork API")
