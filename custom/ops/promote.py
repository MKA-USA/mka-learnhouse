#!/usr/bin/env python3
"""Promote dev -> prod: code, env, compose, org settings, backfill.

Usage:
    python3 custom/ops/promote.py [--apply] [--skip-code] [--only env,compose,org,code,backfill]

Default is a DRY RUN that prints the plan. Nothing is written without --apply.
Every step is idempotent. Secret values are never printed (key names only).
Execution order (env and compose must land before the deploy picks them up):
    env -> compose -> code(+deploy) -> org -> backfill
Python 3 stdlib only. See custom/ops/README.md.
"""
import argparse
import base64
import copy
import datetime
import json
import os
import re
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid as uuidlib

REPO = "MKA-USA/mka-learnhouse"
COOLIFY = os.environ.get("MKA_COOLIFY_URL", "http://82.29.153.52:8000/api/v1").rstrip("/")
DEV_SERVICE = "wu1nbkd5gklumfdukk2xwykl"
PROD_SERVICE = "7plsfizuqdvykh5oathbuefi"
DEV_HOST = "ilm-dev.mkausa.org"
PROD_HOST = "ilm.mkausa.org"
DEV_URL = f"https://{DEV_HOST}"
PROD_URL = f"https://{PROD_HOST}"
ORG_SLUG = "default"
DEPLOY_WORKFLOW = "mka-prod-deploy.yaml"
PROD_TOKEN_KEYCHAIN = "MKA_LH_PROD_API_TOKEN"
BACKUP_DIR = os.path.expanduser("~/.mka-promote/backups")
ALL_STEPS = ["env", "compose", "code", "org", "backfill"]

# ---------------------------------------------------------------------------
# Per-environment env keys. These are NEVER copied dev -> prod.
#
# Add a key here when prod must keep its own value (a different account, key,
# recipient...). Keys in PER_ENV_SECRET_KEYS are additionally generated on prod
# when missing (secrets.token_hex(32)) and stored in the macOS keychain as
# "<KEY>_PROD". PER_ENV_KEYS is for keys prod owns and the script must leave
# alone. Values containing the dev host are rewritten separately (rewrite_host)
# and do not need to be listed.
# ---------------------------------------------------------------------------
PER_ENV_SECRET_KEYS = ("MKA_AUTOMATION_CRON_SECRET", "MKA_AUTOMATION_WEBHOOK_SECRET")
PER_ENV_KEYS = (  # never copied; reported as MANUAL when missing on prod
    "NEXTAUTH_SECRET", "LEARNHOUSE_AUTH_JWT_SECRET_KEY", "COLLAB_INTERNAL_KEY",
    "POSTGRES_PASSWORD", "POSTGRES_USER", "POSTGRES_DB", "LEARNHOUSE_INITIAL_ADMIN_PASSWORD",
    "LEARNHOUSE_SQL_CONNECTION_STRING", "LEARNHOUSE_REDIS_CONNECTION_STRING", "LEARNHOUSE_REDIS_URL",
)  # e.g. add "MKA_AUTOMATION_TEST_RECIPIENT" if prod needs its own value
# Any key matching this is treated as a secret and NOT copied unless allowlisted below.
SECRET_RE = re.compile(r"(SECRET|PASSWORD|PRIVATE|_KEY$|TOKEN|DSN)", re.I)
# Credentials embedded in a URL/DSN value (scheme://user:pass@host) also count as secret.
CRED_URL_RE = re.compile(r"://[^/\s:@]+:[^@\s]+@")
# Third-party keys shared dev<->prod by design. Add a key here only after deciding that.
SHARED_SECRET_KEYS = (
    "LEARNHOUSE_GOOGLE_CLIENT_SECRET", "LEARNHOUSE_SMTP_PASSWORD", "LEARNHOUSE_AI_API_KEY",
    "TYPESAFE_API_KEY", "TURNSTILE_SECRET_KEY", "NEXT_PUBLIC_TURNSTILE_SITE_KEY",
)
# Coolify generates these per service (SERVICE_PASSWORD_*, SERVICE_FQDN_*...).
PER_ENV_PREFIXES = ("SERVICE_",)

# Org paths never copied: ids, uuids, dates, derived data, prod-owned plan.
ORG_IGNORE_KEYS = {
    "id", "org_id", "org_uuid", "uuid", "slug", "creation_date", "update_date",
    "resolved_features", "plan", "active", "config_version", "is_demo",
}
ORG_IGNORE_SUFFIXES = ("_at", "_uuid", "_id", "_date")
TOP_FIELDS = ("name", "description", "about", "label", "email", "links")
GENERAL_QUERY = {  # general/<key> -> (endpoint, query param)
    "color": ("color", "color"),
    "font": ("font", "font"),
    "footer_text": ("footer_text", "footer_text"),
    "email_sender_name": ("email_sender_name", "email_sender_name"),
    "default_language": ("default_language", "default_language"),
    "watermark": ("watermark", "watermark_enabled"),
}
FEATURE_TOGGLES = ("communities", "payments", "courses", "folders", "podcasts", "boards", "playgrounds")
# image path -> (upload endpoint, multipart field, media dir)
IMAGE_FIELDS = {
    ("logo_image",): ("logo", "logo_file", "logos"),
    ("thumbnail_image",): ("thumbnail", "thumbnail_file", "thumbnails"),
    ("config", "config", "customization", "general", "favicon_image"): ("favicon", "favicon_file", "favicons"),
    ("config", "config", "customization", "general", "square_logo_image"): ("square_logo", "square_logo_file", "square_logos"),
    ("config", "config", "customization", "seo", "default_og_image"): ("og_image", "og_image_file", "og_images"),
    ("config", "config", "customization", "auth_branding", "background_image"): ("auth_background", "background_file", "auth_backgrounds"),
}


# ---------------------------------------------------------------------------
# Pure functions (unit tested)
# ---------------------------------------------------------------------------
def rewrite_host(value, dev=DEV_HOST, prod=PROD_HOST):
    """Replace the dev host with the prod host in a string value."""
    if isinstance(value, str):
        return value.replace(dev, prod)
    return value


def is_secret(key, value, shared=SHARED_SECRET_KEYS):
    """True if this env var must not be copied dev -> prod."""
    if key in shared:
        return False
    return bool(SECRET_RE.search(key) or CRED_URL_RE.search(value or ""))


def plan_env(dev_envs, prod_envs, secret_keys=PER_ENV_SECRET_KEYS, per_env_keys=PER_ENV_KEYS,
             prefixes=PER_ENV_PREFIXES, shared=SHARED_SECRET_KEYS):
    """Plan env changes. dev_envs/prod_envs: lists of {"key","value"}.

    Returns dict(actions=[{key, op: create|update, value, reason}], gen=[keys to generate],
    prod_only=[keys], skipped=[keys], unchanged=int).
    """
    prod = {e["key"]: (e.get("value") or "") for e in prod_envs}
    actions, gen, skipped, unchanged, manual = [], [], [], 0, []
    for e in dev_envs:
        key, dv = e["key"], e.get("value") or ""
        if key in secret_keys:
            if key not in prod:
                gen.append(key)
            continue
        if any(key.startswith(p) for p in prefixes):
            skipped.append(key)
            continue
        if key in per_env_keys or is_secret(key, dv, shared):
            skipped.append(key)
            if key not in prod:
                manual.append(key)  # secret missing on prod: operator must set it
            continue
        want, reason = dv, "copy"
        if DEV_HOST in dv:
            want, reason = rewrite_host(dv), "copy+host"
        if key not in prod:
            actions.append({"key": key, "op": "create", "value": want, "reason": reason})
        elif prod[key] != want:
            actions.append({"key": key, "op": "update", "value": want, "reason": reason})
        else:
            unchanged += 1
    dev_keys = {e["key"] for e in dev_envs}
    prod_only = sorted(k for k in prod if k not in dev_keys)
    return {"actions": actions, "gen": gen, "prod_only": prod_only, "skipped": skipped, "unchanged": unchanged,
            "manual": manual}


_SVC_RE = re.compile(r"^  ([A-Za-z0-9_.-]+):\s*$")
_ENVHDR_RE = re.compile(r"^    environment:\s*$")
_ITEM_RE = re.compile(r"""^(\s{6}-\s+)['"]?([A-Za-z_][A-Za-z0-9_]*)=""")


def parse_env_lines(raw):
    """Return {service: [(var, line), ...]} for `- VAR=...` items under `environment:`."""
    out, svc, in_env = {}, None, False
    for line in raw.splitlines():
        m = _SVC_RE.match(line)
        if m:
            svc, in_env = m.group(1), False
            continue
        if _ENVHDR_RE.match(line):
            in_env = True
            out.setdefault(svc, [])
            continue
        if in_env:
            im = _ITEM_RE.match(line)
            if im:
                out[svc].append((im.group(2), line))
            elif line.strip() and not line.startswith("      "):
                in_env = False
    return out


def redact_compose(raw):
    """Redact literal values of secret-looking env lines (those not a ${VAR} ref).

    Returns (text, [var names redacted]).
    """
    out, names = [], []
    for line in raw.split("\n"):
        m = _ITEM_RE.match(line)
        if m and SECRET_RE.search(m.group(2)):
            val = line[m.end():].rstrip("'\" ")
            if val and not val.startswith("${"):
                names.append(m.group(2))
                line = line[:m.end()] + "<redacted>'"
        out.append(line)
    return "\n".join(out), names


def compose_insert(dev_raw, prod_raw):
    """Insert env pass-through lines present in dev but missing in prod.

    Position: right after the nearest preceding dev neighbour that exists in prod,
    else right before the nearest following one, else at the end of the block.
    Returns (new_prod_raw, [(service, var)]). Never touches anything else.
    """
    dev, prod = parse_env_lines(dev_raw), parse_env_lines(prod_raw)
    lines = prod_raw.split("\n")
    added = []
    for svc, items in dev.items():
        if svc not in prod:
            continue
        have = {v for v, _ in prod[svc]}
        for idx, (var, line) in enumerate(items):
            if var in have:
                continue
            pos = _find_insert_pos(lines, svc, items, idx, have)
            if pos is None:
                continue
            lines.insert(pos, line)
            have.add(var)
            added.append((svc, var))
    return "\n".join(lines), added


def _find_insert_pos(lines, svc, items, idx, have):
    def locate(var):
        cur, in_env = None, False
        for i, l in enumerate(lines):
            m = _SVC_RE.match(l)
            if m:
                cur, in_env = m.group(1), False
            elif _ENVHDR_RE.match(l):
                in_env = True
            elif in_env and cur == svc:
                im = _ITEM_RE.match(l)
                if im and im.group(2) == var:
                    return i
        return None
    for j in range(idx - 1, -1, -1):
        if items[j][0] in have:
            p = locate(items[j][0])
            if p is not None:
                return p + 1
    for j in range(idx + 1, len(items)):
        if items[j][0] in have:
            p = locate(items[j][0])
            if p is not None:
                return p
    # end of the service's environment block
    cur, in_env, last = None, False, None
    for i, l in enumerate(lines):
        m = _SVC_RE.match(l)
        if m:
            cur, in_env = m.group(1), False
        elif _ENVHDR_RE.match(l):
            in_env = True
            if cur == svc:
                last = i
        elif in_env and cur == svc:
            if _ITEM_RE.match(l):
                last = i
            elif l.strip() and not l.startswith("      "):
                in_env = False
    return None if last is None else last + 1


def _ignored(key):
    return key in ORG_IGNORE_KEYS or key.endswith(ORG_IGNORE_SUFFIXES)


def clean_org(org):
    """Drop ignored keys recursively and rewrite dev host in strings."""
    if isinstance(org, dict):
        return {k: clean_org(v) for k, v in org.items() if not _ignored(k)}
    if isinstance(org, list):
        return [clean_org(v) for v in org]
    return rewrite_host(org)


def org_diff(dev, prod):
    """Path-level diff dev -> prod. Returns [(path_tuple, dev_value, prod_value)].

    Dicts are walked; lists and scalars are compared whole. Ignored keys skipped.
    Only paths where dev differs from prod (or is absent on prod) are returned.
    """
    out = []

    def walk(d, p, path):
        if isinstance(d, dict):
            pd = p if isinstance(p, dict) else {}
            for k, v in d.items():
                if _ignored(k):
                    continue
                walk(v, pd.get(k, MISSING), path + (k,))
        else:
            if d != p:
                out.append((path, d, None if p is MISSING else p))

    walk(dev, prod, ())
    return out


MISSING = object()


def get_path(obj, path, default=None):
    for k in path:
        if not isinstance(obj, dict) or k not in obj:
            return default
        obj = obj[k]
    return obj


def plan_org_ops(diff, dev_org, prod_org):
    """Map diff paths to API operations. Images are handled separately.

    Returns (ops, manual, image_paths). op = dict(label, method, endpoint, query, json, paths).
    """
    paths = {p for p, _, _ in diff}
    ops, manual, images = [], [], []
    cust = ("config", "config", "customization")
    adm = ("config", "config", "admin_toggles")

    def has(prefix):
        return [p for p in paths if p[:len(prefix)] == prefix]

    def devv(p):
        return get_path(clean_org(dev_org), p)

    top = [f for f in TOP_FIELDS if (f,) in paths or has((f,))]
    if top:
        ops.append({"label": "org core fields: " + ",".join(top), "method": "PUT", "endpoint": "",
                    "json": {f: devv((f,)) for f in top}, "paths": [(f,) for f in top]})
    for k, (ep, param) in GENERAL_QUERY.items():
        pth = cust + ("general", k)
        if pth in paths:
            val = devv(pth)
            if isinstance(val, bool):
                val = str(val).lower()
            ops.append({"label": f"general.{k}", "method": "PUT", "endpoint": f"/config/{ep}",
                        "query": {param: val}, "paths": [pth]})
    for sect, ep in (("auth_branding", "auth_branding"), ("seo", "seo"), ("menu", "menu"),
                     ("signup_fields", "signup-fields"), ("course_end", "course-end")):
        sub = [p for p in has(cust + (sect,)) if p not in IMAGE_FIELDS]
        if sub:
            body = copy.deepcopy(devv(cust + (sect,)))
            # image filenames are set by the upload step, keep prod's current value here
            for ip in IMAGE_FIELDS:
                if ip[:4] == cust + (sect,) and isinstance(body, dict):
                    body[ip[-1]] = get_path(prod_org, ip, "")
            ops.append({"label": f"customization.{sect}", "method": "PUT", "endpoint": f"/config/{ep}",
                        "json": body, "paths": sub})
    # admin toggles
    ai = has(adm + ("ai",))
    if ai:
        q = {}
        d = devv(adm + ("ai",)) or {}
        if "disabled" in d:
            q["ai_enabled"] = str(not d["disabled"]).lower()
        if "copilot_enabled" in d:
            q["copilot_enabled"] = str(d["copilot_enabled"]).lower()
        ops.append({"label": "admin_toggles.ai", "method": "PUT", "endpoint": "/config/ai", "query": q, "paths": ai})
    sm = adm + ("members", "signup_mode")
    if sm in paths:
        ops.append({"label": "members.signup_mode", "method": "PUT", "endpoint": "/signup_mechanism",
                    "query": {"signup_mechanism": devv(sm)}, "paths": [sm]})
    for f in FEATURE_TOGGLES:
        pth = adm + (f, "disabled")
        if pth in paths:
            ops.append({"label": f"admin_toggles.{f}", "method": "PUT", "endpoint": f"/config/{f}",
                        "query": {f"{f}_enabled": str(not devv(pth)).lower()}, "paths": [pth]})
    covered = {p for o in ops for p in o["paths"]}
    for p in sorted(paths):
        if p in IMAGE_FIELDS:
            images.append(p)
        elif p not in covered and not any(p[:len(c)] == c for c in covered if len(c) < len(p)):
            manual.append(p)
    return ops, manual, images


def media_url(media_base, org_uuid, media_dir, filename):
    base = media_base if media_base.endswith("/") else media_base + "/"
    return f"{base}content/orgs/{org_uuid}/{media_dir}/{filename}"


def multipart(field, filename, data, ctype="application/octet-stream"):
    boundary = "----promote" + uuidlib.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; filename=\"{filename}\"\r\n"
            f"Content-Type: {ctype}\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


def fmt_val(v, limit=60):
    s = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else repr(v)
    return s if len(s) <= limit else s[:limit] + "..."


# ---------------------------------------------------------------------------
# IO helpers
# ---------------------------------------------------------------------------
def run(cmd, check=True, input_=None):
    r = subprocess.run(cmd, capture_output=True, text=True, input=input_)
    if check and r.returncode != 0:
        raise RuntimeError(f"{cmd[0]} {cmd[1] if len(cmd) > 1 else ''} failed: {r.stderr.strip()[:300]}")
    return r


def keychain_get(service):
    r = run(["security", "find-generic-password", "-s", service, "-w"], check=False)
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None


def keychain_set(service, value):
    # value goes via stdin (security -i), never argv, so it is not visible in `ps`
    run(["security", "-i"], input_=f"add-generic-password -U -s {service} -a mka -w {value}\n")


def http(method, url, headers=None, body=None, timeout=60, raw=False):
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
            return r.status, (data if raw else _maybe_json(data))
    except urllib.error.HTTPError as e:
        data = e.read()
        return e.code, (data if raw else _maybe_json(data))
    except Exception as e:  # network error
        return 0, str(e)


def _maybe_json(data):
    try:
        return json.loads(data)
    except Exception:
        return data.decode("utf-8", "replace")[:300]


class Coolify:
    def __init__(self):
        if COOLIFY.startswith("http://") and not re.match(r"http://(localhost|127\.0\.0\.1)[:/]", COOLIFY):
            say("WARNING: Coolify URL is cleartext http; the API token is sent unencrypted. Use an SSH tunnel (see README).")
        tok = keychain_get("MKA_Coolify_API_Key")
        if not tok:
            raise RuntimeError("keychain item MKA_Coolify_API_Key not found")
        self.h = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json", "Accept": "application/json"}

    def call(self, method, path, payload=None):
        st, data = http(method, COOLIFY + path, self.h, json.dumps(payload).encode() if payload is not None else None)
        if st == 0 or st >= 400:
            raise RuntimeError(f"coolify {method} {path} -> {st}")
        return data

    def envs(self, svc):
        return self.call("GET", f"/services/{svc}/envs")

    def service(self, svc):
        return self.call("GET", f"/services/{svc}")


def gh(args, check=True):
    return run(["gh"] + args + ["--repo", REPO], check=check)


def say(msg=""):
    print(msg, flush=True)


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------
class Ctx:
    def __init__(self, apply, urgent):
        self.apply = apply
        self.urgent = urgent
        self.coolify = None
        self.infra_changed = False
        self.dev_envs = None
        self.prod_token = None

    def cf(self):
        if not self.coolify:
            self.coolify = Coolify()
        return self.coolify


def step_env(ctx):
    say("== env ==")
    cf = ctx.cf()
    dev, prod = cf.envs(DEV_SERVICE), cf.envs(PROD_SERVICE)
    ctx.dev_envs = dev
    plan = plan_env(dev, prod)
    say(f"unchanged: {plan['unchanged']}   skipped per-env: {len(plan['skipped'])}")
    for a in plan["actions"]:
        say(f"  {a['op'].upper():6} {a['key']}  ({a['reason']}; value {'set' if a['op']=='create' else 'changed'})")
    for k in plan["gen"]:
        have = keychain_get(k + "_PROD")
        say(f"  CREATE {k}  (per-env secret; {'reuse keychain ' + k + '_PROD' if have else 'generate + store in keychain ' + k + '_PROD'}; value set)")
    for k in plan["manual"]:
        say(f"  MANUAL {k}: secret missing on prod, not copied; set it in Coolify yourself")
    for k in plan["prod_only"]:
        say(f"  prod-only key (not deleted): {k}")
    if not plan["actions"] and not plan["gen"]:
        say("  nothing to do")
    if not ctx.apply:
        return
    for a in plan["actions"]:
        if a["op"] == "create":
            cf.call("POST", f"/services/{PROD_SERVICE}/envs", {"key": a["key"], "value": a["value"]})
        else:
            cf.call("PATCH", f"/services/{PROD_SERVICE}/envs", {"key": a["key"], "value": a["value"]})
        ctx.infra_changed = True
    for k in plan["gen"]:
        val = keychain_get(k + "_PROD")
        if not val:
            val = secrets.token_hex(32)
            keychain_set(k + "_PROD", val)
        cf.call("POST", f"/services/{PROD_SERVICE}/envs", {"key": k, "value": val})
        ctx.infra_changed = True
    say("  applied")


def step_compose(ctx):
    say("== compose ==")
    cf = ctx.cf()
    dev_raw = cf.service(DEV_SERVICE)["docker_compose_raw"]
    prod_raw = cf.service(PROD_SERVICE)["docker_compose_raw"]
    new_raw, added = compose_insert(dev_raw, prod_raw)
    if not added:
        say("  nothing to do (prod has every dev env pass-through line)")
        return
    for svc, var in added:
        say(f"  ADD {svc}: {var}")
    if not ctx.apply:
        return
    os.makedirs(BACKUP_DIR, mode=0o700, exist_ok=True)
    os.chmod(BACKUP_DIR, 0o700)
    prod_backup, leaked = redact_compose(prod_raw)
    if leaked:
        say(f"  WARNING: prod compose has literal secret value(s) for {leaked}; redacted in the backup (original stays in Coolify)")
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    bpath = os.path.join(BACKUP_DIR, f"prod-compose-{ts}.yml")
    fd = os.open(bpath, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(prod_backup)
    say(f"  backup: {bpath}")
    cf.call("PATCH", f"/services/{PROD_SERVICE}", {"docker_compose_raw": base64.b64encode(new_raw.encode()).decode()})
    after = cf.service(PROD_SERVICE)["docker_compose_raw"]
    old, new = set(prod_raw.splitlines()), set(after.splitlines())
    expected = {l for l in new_raw.splitlines()} - old
    removed, gained = old - new, new - old
    if removed or gained != expected:
        raise RuntimeError(f"compose verify failed: removed={len(removed)} unexpected-added={len(gained - expected)}")
    ctx.infra_changed = True
    say("  applied + verified (only the intended lines changed)")


def http_ok(url, tries=1, delay=10):
    st = 0
    for _ in range(tries):
        st, _d = http("GET", url, timeout=20, raw=True)
        if 200 <= st < 300:
            return True, st
        time.sleep(delay) if tries > 1 else None
    return False, st


def wait_healthy(minutes=10):
    deadline = time.time() + minutes * 60
    while time.time() < deadline:
        ok, st = http_ok(PROD_URL)
        if ok:
            return True
        time.sleep(15)
    return False


def health_report():
    ok, st = http_ok(PROD_URL + "/", tries=6, delay=15)
    say(f"  health {PROD_URL}/ -> {st} {'OK' if ok else 'FAIL'}")
    st2, _ = http("GET", PROD_URL + "/api/v1/health", timeout=20, raw=True)
    say(f"  health {PROD_URL}/api/v1/health -> {st2}" + ("" if st2 else " (unreachable)") + (" (no health endpoint)" if st2 == 404 else ""))
    return ok


def step_code(ctx, skip_code):
    say("== code ==")
    if skip_code:
        say("  skipped (--skip-code)")
        return restart_if_needed(ctx)
    prs = json.loads(gh(["pr", "list", "--base", "prod", "--head", "dev", "--state", "open",
                         "--json", "number,url,title"]).stdout or "[]")
    cmp_ = json.loads(run(["gh", "api", f"repos/{REPO}/compare/prod...dev"]).stdout)
    ahead = cmp_.get("ahead_by", 0)
    say(f"  dev is {ahead} commit(s) ahead of prod; open dev->prod PRs: {[p['number'] for p in prs] or 'none'}")
    if ahead == 0:
        say("  no code to promote")
        return restart_if_needed(ctx)
    if not ctx.apply:
        say(f"  WOULD {'use PR #' + str(prs[0]['number']) if prs else 'create PR dev->prod'}, merge with a MERGE commit, "
            f"run {DEPLOY_WORKFLOW} --ref dev, wait (<=25 min), health check")
        return
    if prs:
        num = str(prs[0]["number"])
    else:
        out = gh(["pr", "create", "--base", "prod", "--head", "dev", "--title", "Promote dev to prod",
                  "--body", f"Automated promote of {ahead} commit(s).\n\n🤖 Generated with [Claude Code](https://claude.com/claude-code)"]).stdout
        num = out.strip().rstrip("/").split("/")[-1]
        say(f"  created PR #{num}")
    gh(["pr", "merge", num, "--merge"])  # merge commit, never squash
    say(f"  merged PR #{num} (merge commit)")
    started = datetime.datetime.now(datetime.timezone.utc)
    args = ["workflow", "run", DEPLOY_WORKFLOW, "--ref", "dev"]
    if ctx.urgent:
        args += ["-f", "urgent=true"]
    gh(args)
    time.sleep(8)
    run_id = None
    for _ in range(12):
        runs = json.loads(gh(["run", "list", "--workflow", DEPLOY_WORKFLOW, "--event", "workflow_dispatch",
                              "--limit", "5", "--json", "databaseId,createdAt"]).stdout or "[]")
        for r in runs:
            created = datetime.datetime.fromisoformat(r["createdAt"].replace("Z", "+00:00"))
            if created >= started - datetime.timedelta(seconds=30):
                run_id = r["databaseId"]
                break
        if run_id:
            break
        time.sleep(5)
    if not run_id:
        raise RuntimeError("could not find the dispatched deploy run")
    say(f"  deploy run {run_id}: waiting (poll 30s, cap 25 min)")
    deadline = time.time() + 25 * 60
    while time.time() < deadline:
        v = json.loads(gh(["run", "view", str(run_id), "--json", "status,conclusion"]).stdout)
        if v["status"] == "completed":
            say(f"  deploy conclusion: {v['conclusion']}")
            if v["conclusion"] != "success":
                raise RuntimeError("deploy did not succeed")
            break
        time.sleep(30)
    else:
        raise RuntimeError("deploy timed out after 25 min")
    if not health_report():
        raise RuntimeError("prod health check failed")


def restart_if_needed(ctx):
    if not ctx.infra_changed:
        return
    if not ctx.apply:
        return
    say("  env/compose changed and no deploy: restarting prod service")
    ctx.cf().call("POST", f"/services/{PROD_SERVICE}/restart")
    time.sleep(20)
    if not wait_healthy():
        raise RuntimeError("prod did not become healthy after restart")
    health_report()


# --- org -------------------------------------------------------------------
def fetch_org(base):
    st, d = http("GET", f"{base}/api/v1/orgs/slug/{ORG_SLUG}")
    if st != 200 or not isinstance(d, dict):
        raise RuntimeError(f"cannot read org from {base}: {st}")
    return d


def media_base(ctx, which):
    base = None
    if which == "dev":
        for e in ctx.dev_envs or ctx.cf().envs(DEV_SERVICE):
            if e["key"] == "LEARNHOUSE_MEDIA_URL":
                base = e.get("value")
    if not base:
        base = (DEV_URL if which == "dev" else PROD_URL)
    return rewrite_host(base) if which == "prod" else base


def step_org(ctx):
    say("== org ==")
    dev, prod = fetch_org(DEV_URL), fetch_org(PROD_URL)
    prod_org_id, dev_org_uuid, prod_org_uuid = prod["id"], dev["org_uuid"], prod["org_uuid"]
    diff = org_diff(clean_org(dev), clean_org(prod))
    ops, manual, images = plan_org_ops(diff, dev, prod)
    token = keychain_get(PROD_TOKEN_KEYCHAIN)
    ctx.prod_token = token
    for o in ops:
        for p in o["paths"]:
            say(f"  DIFF /{'/'.join(p)}: prod={fmt_val(get_path(prod, p))} -> dev={fmt_val(get_path(clean_org(dev), p))}")
        say(f"    -> {o['method']} /orgs/{{id}}{o['endpoint']}  [{o['label']}]")
    img_ops = []
    for p in images:
        ep, field, mdir = IMAGE_FIELDS[p]
        dname, pname = get_path(dev, p), get_path(prod, p)
        if not dname:
            continue
        db = http("GET", media_url(media_base(ctx, "dev"), dev_org_uuid, mdir, dname), raw=True)
        if db[0] != 200:
            say(f"  image /{'/'.join(p)}: cannot download dev file ({db[0]}); skipped")
            continue
        same = False
        if pname:
            pb = http("GET", media_url(media_base(ctx, "prod"), prod_org_uuid, mdir, pname), raw=True)
            same = pb[0] == 200 and pb[1] == db[1]
        say(f"  image /{'/'.join(p)}: {'identical bytes, skip' if same else 'differs -> PUT /orgs/{id}/' + ep}")
        if not same:
            img_ops.append((ep, field, dname, db[1]))
    for p in manual:
        say(f"  MANUAL (no org API endpoint wired): /{'/'.join(p)}")
    if not ops and not img_ops:
        say("  nothing to do")
    if not token:
        say("  prod admin API token missing; org writes skipped. Create one:")
        say("    Prod org settings -> API tokens -> Create token, access Full Access, then")
        say(f"    security add-generic-password -U -s {PROD_TOKEN_KEYCHAIN} -a mka -w '<lh_token>'")
        return
    if not ctx.apply:
        return
    auth = {"Authorization": f"Bearer {token}"}
    base = f"{PROD_URL}/api/v1/orgs/{prod_org_id}"
    failures = 0
    for o in ops:
        url = base + o["endpoint"]
        if o.get("query"):
            url += "?" + urllib.parse.urlencode(o["query"])
        body = json.dumps(o["json"]).encode() if "json" in o else None
        st, d = http(o["method"], url, {**auth, "Content-Type": "application/json"}, body)
        say(f"  {o['label']}: {st}")
        failures += st >= 400 or st == 0
    for ep, field, fname, data in img_ops:
        body, ctype = multipart(field, fname.split("_", 1)[-1] if "_" in fname else fname, data)
        st, d = http("PUT", f"{base}/{ep}", {**auth, "Content-Type": ctype}, body)
        say(f"  upload {ep}: {st}")
        failures += st >= 400 or st == 0
    if failures:
        say(f"  {failures} org write(s) failed (check token has Full Access)")


# --- backfill --------------------------------------------------------------
def step_backfill(ctx):
    say("== backfill ==")
    token = ctx.prod_token or keychain_get(PROD_TOKEN_KEYCHAIN)
    if not token:
        say(f"  prod API token missing ({PROD_TOKEN_KEYCHAIN}); skipped. See org step for how to create it.")
        return
    h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    api = f"{PROD_URL}/api/v1/mka"
    q = f"org_slug={ORG_SLUG}"
    if ctx.apply:
        st, d = http("POST", f"{api}/attributes/recompute?{q}", h, json.dumps({"dry_run": False}).encode())
        if st in (401, 403):
            say("  recompute rejected API tokens. Manual: sign in to prod as an org admin, then in the browser console run")
            say(f"    fetch('/api/v1/mka/attributes/recompute?org_id=1',{{method:'POST',credentials:'include',headers:{{'Content-Type':'application/json'}},body:'{{\"dry_run\":false}}'}})")
        else:
            say(f"  recompute: {st} {summarize(d)}")
    else:
        say("  WOULD POST /mka/attributes/recompute {dry_run:false}")
    st, d = http("POST", f"{api}/identity/sync?{q}&dry_run=true", h, b"")
    say(f"  identity sync (dry-run): {st} {summarize(d)}")
    if ctx.apply and st == 200:
        st, d = http("POST", f"{api}/identity/sync?{q}&dry_run=false", h, b"")
        say(f"  identity sync (real): {st} {summarize(d)}")
    st, d = http("GET", f"{api}/identity/status?{q}", h)
    say(f"  identity status: {st} {summarize(d)}")


def summarize(d, limit=300):
    """Counts only: reduce lists to lengths, never echo free text."""
    if isinstance(d, dict):
        out = {k: (len(v) if isinstance(v, (list, dict)) else v) for k, v in d.items()}
        s = json.dumps(out, default=str)
    else:
        s = str(d)[:120]
    return s[:limit]


# ---------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description="Promote dev to prod (dry-run unless --apply).")
    ap.add_argument("--apply", action="store_true", help="execute the plan (default is dry-run)")
    ap.add_argument("--skip-code", action="store_true", help="do not merge/deploy code")
    ap.add_argument("--only", default="", help="comma list of: " + ",".join(ALL_STEPS))
    ap.add_argument("--urgent", action="store_true", help="pass urgent=true to the deploy workflow (ignores PROD_FREEZE)")
    a = ap.parse_args(argv)
    only = [s for s in a.only.split(",") if s] or ALL_STEPS
    bad = [s for s in only if s not in ALL_STEPS]
    if bad:
        ap.error(f"unknown step(s): {bad}")
    ctx = Ctx(a.apply, a.urgent)
    say(f"promote dev -> prod  [{'APPLY' if a.apply else 'DRY-RUN'}]  steps: {','.join(s for s in ALL_STEPS if s in only)}")
    fns = {"env": lambda: step_env(ctx), "compose": lambda: step_compose(ctx),
           "code": lambda: step_code(ctx, a.skip_code), "org": lambda: step_org(ctx),
           "backfill": lambda: step_backfill(ctx)}
    rc = 0
    for s in ALL_STEPS:
        if s not in only:
            continue
        try:
            fns[s]()
        except Exception as e:
            say(f"  STEP {s} FAILED: {e}")
            rc = 1
            if s in ("env", "compose", "code"):
                say("  stopping: later steps depend on this one")
                break
    return rc


if __name__ == "__main__":
    sys.exit(main())
