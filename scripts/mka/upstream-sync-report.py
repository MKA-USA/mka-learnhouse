#!/usr/bin/env python3
"""Fork-only: build the PR body for an upstream sync and decide the review gate.

Usage: upstream-sync-report.py [--base origin/dev] [--head upstream/dev] [--gate-head REF]
                               [--upstream-repo learnhouse/learnhouse] [--github-output FILE]

Prints the Markdown PR body on stdout. With --github-output, also appends
`needs_review=true|false`, `commit_count=N` and `reasons=...` lines.
Only reads git; never writes to the repo. All paths are parsed from NUL-delimited git output
(mka_gitpaths), matched on a Unicode-NFC/case-folded key, and BOTH sides of renames are checked.
Commit text and paths are untrusted: only emitted into Markdown code spans.

Fail-safe: on ANY error (including an unparseable diff entry) the gate defaults to
needs_review=true. Run it from a TRUSTED checkout (origin/dev), never from the merged tree.
"""
import argparse
import ast
import os
import posixpath
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mka_gitpaths import dec, disp, git, mode_changed, norm, parse_raw_z, special, weird  # noqa: E402

MIGRATIONS_DIR = "apps/api/migrations/versions/"
MODS_FILE = ".codebase-memory/upstream-modifications.md"
PATH_RE = re.compile(r"`((?:apps|custom|scripts|docs|\.github)/[\w./\[\]()@+-]+\.\w+)`")
CC_RE = re.compile(r"^(\w+)(?:\([^)]*\))?(!)?:\s")
PR_RE = re.compile(r"\(#(\d+)\)\s*$")
# Alembic ops that change an EXISTING table. create_all (our startup) never applies these, so a sync carrying one
# must be reviewed and checked with /api/v1/mka/health/schema after deploy.
SCHEMA_OPS_RE = re.compile(
    r"\bop\.(add_column|alter_column|drop_column|create_index|drop_index|create_foreign_key|drop_constraint|"
    r"create_unique_constraint|create_check_constraint|rename_table|drop_table|execute)\b|\bbatch_alter_table\b"
)
MAX_DIFF_LINES = 40
MAX_LIST = 60

CONFIG_EXACT = {"apps/api/config/config.yaml", "apps/api/config/config.py"}
ENV_BASENAME_RE = re.compile(r"^\.env(\..*)?$|^.+\.env(\..*)?$|^env\.(ts|js|mjs|cjs)$")
ENV_DOC_RE = re.compile(r"^docs/.*[^/]*env[^/]*\.(md|mdx)$")
DEP_BASENAMES = {
    "package.json", "bun.lock", "bun.lockb", "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
    "pyproject.toml", "uv.lock", "poetry.lock", "pipfile", "pipfile.lock",
}
DEP_RE = re.compile(r"^requirements[^/]*\.txt$")
DEPLOY_BASENAME_RE = re.compile(r"^(dockerfile.*|.*\.dockerfile|docker-compose.*|compose(\..*)?\.ya?ml|\.dockerignore|caddyfile|nginx.*\.conf)$")
DEPLOY_DIR_RE = re.compile(r"(^|/)(\.?coolify|deploy|deployment|deployments|infra|infrastructure)(/|$)")
GITCFG_RE = re.compile(r"(^|/)(\.gitattributes|\.gitmodules)$")
AUTH_RE = re.compile(r"auth|security|permission|rbac|session|oauth|sso")
NEXT_CFG_RE = re.compile(r"^(next\.config\.[^/]+|middleware\.(ts|js|mjs)|proxy\.(ts|js|mjs))$")


def upgrade_body(src):
    """Source of the migration's upgrade() only (downgrade() reverses every op and would double-count). Falls back to
    the whole file when it cannot be parsed, which errs towards flagging."""
    try:
        for node in ast.parse(src).body:
            if isinstance(node, ast.FunctionDef) and node.name == "upgrade":
                return ast.get_source_segment(src, node) or src
    except SyntaxError:
        pass
    return src


def base(p):
    return posixpath.basename(p)


# All predicates take the NORMALISED key (NFC + lowercase).
def is_config(n):
    return n in CONFIG_EXACT or bool(ENV_BASENAME_RE.match(base(n))) or bool(ENV_DOC_RE.match(n))


def is_auth(n):
    return n.startswith(("apps/api/src/", "apps/web/")) and bool(AUTH_RE.search(n))


def build(a):
    commits = []
    _, raw = git("log", "-z", "--no-merges", "--format=%h%x1f%s", f"{a.base}..{a.head}")
    for rec in raw.split(b"\0"):
        if rec:
            sha, _, subj = dec(rec).partition("\x1f")
            commits.append((sha, subj))
    total = int(dec(git("rev-list", "--count", f"{a.base}..{a.head}")[1]).strip())

    _, rawdiff = git("diff", "--raw", "-z", "-M", "--no-ext-diff", "--no-textconv", f"{a.base}...{a.gate_head}")
    entries = parse_raw_z(rawdiff)

    # Every path on either side of a rename/copy counts; the old side of a rename counts as a deletion.
    touched, deleted, added = {}, set(), set()
    for e in entries:
        for p in e["paths"]:
            touched[norm(p)] = p
        if e["status"] == "D":
            deleted.add(norm(e["paths"][0]))
        elif e["status"] == "R":
            deleted.add(norm(e["paths"][0]))
            added.add(norm(e["paths"][1]))
        elif e["status"] in "AC":
            added.add(norm(e["paths"][-1]))
    keys = sorted(touched)

    try:
        mods = dec(git("show", f"{a.base}:{MODS_FILE}")[1])
    except RuntimeError:
        mods = ""
    hook_keys = {norm(p) for p in PATH_RE.findall(mods)}

    def fork_only(n):
        b = base(n)
        return b.startswith(("mka-", "mka_")) or n.startswith("custom/") or n in hook_keys

    def schema_changes():
        """Migration files in the range (added or modified) that alter existing tables, with the ops they use."""
        found = []
        for n in keys:
            if not (n.startswith(MIGRATIONS_DIR) and n.endswith(".py")) or n in deleted - added:
                continue
            try:
                src = dec(git("show", f"{a.gate_head}:{touched[n]}")[1])
            except RuntimeError:
                continue
            ops = sorted({m.group(1) or "batch_alter_table" for m in SCHEMA_OPS_RE.finditer(upgrade_body(src))})
            if ops:
                found.append(f"{touched[n]}: {', '.join(ops)}")
        return found

    special_entries = sorted({touched[norm(e["paths"][-1])] for e in entries if special(e) or mode_changed(e)}, key=norm)
    categories = [
        ("New alembic migrations",
         [touched[n] for n in keys if n in added and n.startswith(MIGRATIONS_DIR) and n.endswith(".py")]),
        ("Schema changes (migrations altering existing tables: create_all will NOT apply these; "
         "check /api/v1/mka/health/schema after deploy)", schema_changes()),
        ("Config / env changes (config.yaml/py, .env*, env.ts, env docs)", [touched[n] for n in keys if is_config(n)]),
        ("Dependency manifests and lockfiles", [touched[n] for n in keys if base(n) in DEP_BASENAMES or DEP_RE.match(base(n))]),
        ("Docker / compose / deploy files", [touched[n] for n in keys if DEPLOY_BASENAME_RE.match(base(n)) or DEPLOY_DIR_RE.search(n)]),
        ("GitHub config (.github/**: workflows, actions, CODEOWNERS, mka/)", [touched[n] for n in keys if n.startswith(".github/")]),
        ("Scripts (scripts/**)", [touched[n] for n in keys if n.startswith("scripts/")]),
        ("Auth / security / permission / session code", [touched[n] for n in keys if is_auth(n)]),
        ("Next.js config / middleware / proxy", [touched[n] for n in keys if NEXT_CFG_RE.match(base(n))]),
        ("Git behaviour files (.gitattributes, .gitmodules)", [touched[n] for n in keys if GITCFG_RE.search(n)]),
        ("Symlinks, submodules, file-mode (exec bit) changes", special_entries),
        ("Unusual path names (control chars, backslashes, leading/trailing space, ..)", [touched[n] for n in keys if weird(touched[n])]),
        ("Deleted or renamed-away fork-only/hooked files (mka-*, custom/, upstream-modifications.md)",
         [touched[n] for n in keys if n in deleted and fork_only(n)]),
        ("Touches fork hook sites (see upstream-modifications.md)", [touched[n] for n in keys if n in hook_keys]),
    ]

    groups = {"feat": [], "fix": [], "other": []}
    for sha, subj in commits:
        m = CC_RE.match(subj)
        kind = m.group(1).lower() if m else "other"
        groups[kind if kind in ("feat", "fix") else "other"].append((sha, subj))

    def fmt(sha, subj):
        # Subjects are untrusted text: always a code span (no links/images/mentions/HTML); the link is built
        # only from digits / hex.
        pr = PR_RE.search(subj)
        subj = PR_RE.sub("", subj).strip()
        subj = "".join(ch for ch in subj if ch.isprintable())[:200].replace("`", "'")
        sha = re.sub(r"[^0-9a-f]", "", sha)
        if pr:
            return f"- `{subj}` ([#{pr.group(1)}](https://github.com/{a.upstream_repo}/pull/{pr.group(1)}))"
        return f"- `{subj}` ([`{sha}`](https://github.com/{a.upstream_repo}/commit/{sha}))"

    reasons = []
    out = ["## Upstream sync\n",
           f"Merges `{a.head}` into `dev`: **{total}** upstream commit(s) ({len(entries)} files changed). "
           "Gate computed on the cumulative diff of everything this PR lands (both sides of renames). "
           "Merge with a **merge commit** only (never squash/rebase) so future syncs share a merge-base.\n",
           "### Needs human attention\n"]
    for title, items in categories:
        if items:
            reasons.append(title)
            out.append(f"**{title}** ({len(items)})\n")
            out.extend(f"- `{disp(p)}`" for p in items[:MAX_LIST])
            if len(items) > MAX_LIST:
                out.append(f"- ... and {len(items) - MAX_LIST} more")
            out.append("")
        else:
            out.append(f"- {title}: none")
    out.append("")

    cfg = [touched[n] for n in keys if is_config(n)]
    if cfg:
        out.append("<details><summary>Config / env diffs (added or removed lines)</summary>\n")
        for p in cfg[:15]:
            d = dec(git("diff", "-U0", "--no-ext-diff", "--no-textconv", f"{a.base}...{a.gate_head}", "--", p)[1]).splitlines()
            body = [l for l in d if l[:1] in "+-" and not l.startswith(("+++", "---"))]
            out.append(f"`{disp(p)}`\n\n```diff")
            out.extend(l.replace("```", "'''") for l in body[:MAX_DIFF_LINES])
            if len(body) > MAX_DIFF_LINES:
                out.append(f"... {len(body) - MAX_DIFF_LINES} more lines")
            out.append("```\n")
        out.append("</details>\n")

    out.append("### Upstream commits\n")
    for key, title in (("feat", "Features"), ("fix", "Fixes"), ("other", "Other")):
        items = groups[key]
        out.append(f"**{title}** ({len(items)})\n")
        out.extend(fmt(*c) for c in items[:150])
        if len(items) > 150:
            out.append(f"- ... and {len(items) - 150} more")
        out.append("")

    needs_review = bool(reasons)
    out.append("---")
    out.append("Auto-merge: **disabled** (review required)" if needs_review
               else "Auto-merge: **enabled** (no sensitive categories touched)")
    return "\n".join(out) + "\n", needs_review, reasons, total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="origin/dev")
    ap.add_argument("--head", default="upstream/dev")
    ap.add_argument("--gate-head", help="ref whose cumulative diff vs --base drives the gate (default: --head)")
    ap.add_argument("--upstream-repo", default="learnhouse/learnhouse")
    ap.add_argument("--github-output")
    a = ap.parse_args()
    a.gate_head = a.gate_head or a.head

    try:
        body, needs_review, reasons, total = build(a)
    except Exception as e:  # fail safe: never allow auto-merge if the report broke
        body = ("## Upstream sync\n\n**The report script failed; treat this PR as needing full review.**\n\n"
                f"Error: `{str(e)[:300]}`\n\nAuto-merge: **disabled** (report error)\n")
        needs_review, reasons, total = True, ["report script error"], -1
        sys.stderr.write(f"report error: {e}\n")

    sys.stdout.write(body)
    if a.github_output:
        with open(a.github_output, "a") as f:
            f.write(f"needs_review={'true' if needs_review else 'false'}\n")
            f.write(f"commit_count={total}\n")
            f.write(f"reasons={'; '.join(reasons)}\n")


if __name__ == "__main__":
    main()
