#!/usr/bin/env python3
"""Fork-only: build the PR body for an upstream sync and decide the review gate.

Usage: upstream-sync-report.py [--base origin/dev] [--head upstream/dev]
                               [--upstream-repo learnhouse/learnhouse]
                               [--github-output FILE]

Prints the Markdown PR body on stdout. With --github-output, also appends
`needs_review=true|false`, `commit_count=N` and `reasons=...` lines.
Only reads git; never writes to the repo. Upstream commit text is untrusted:
it is only ever emitted into Markdown, never executed or interpolated in shell.

Fail-safe: on ANY error the gate defaults to needs_review=true (no auto-merge).
Must be run from a TRUSTED checkout (origin/dev), never from the merged tree.
"""
import argparse
import posixpath
import re
import subprocess
import sys

MIGRATIONS_DIR = "apps/api/migrations/versions/"
MODS_FILE = ".codebase-memory/upstream-modifications.md"
PATH_RE = re.compile(r"`((?:apps|custom|scripts|docs|\.github)/[\w./\[\]()@+-]+\.\w+)`")
CC_RE = re.compile(r"^(\w+)(?:\([^)]*\))?(!)?:\s")
PR_RE = re.compile(r"\(#(\d+)\)\s*$")
MAX_DIFF_LINES = 40
MAX_LIST = 60

CONFIG_EXACT = {"apps/api/config/config.yaml", "apps/api/config/config.py"}
ENV_BASENAME_RE = re.compile(r"^\.env(\..*)?$|^.+\.env(\..*)?$|^env\.(ts|js|mjs|cjs)$", re.I)
ENV_DOC_RE = re.compile(r"^docs/.*(^|/)[^/]*env[^/]*\.(md|mdx)$", re.I)
DEP_BASENAMES = {
    "package.json", "bun.lock", "bun.lockb", "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
    "pyproject.toml", "uv.lock", "poetry.lock", "pipfile", "pipfile.lock",
}
DEP_RE = re.compile(r"^requirements[^/]*\.txt$", re.I)
DEPLOY_BASENAME_RE = re.compile(r"^(dockerfile.*|.*\.dockerfile|docker-compose.*|compose(\..*)?\.ya?ml|\.dockerignore|caddyfile|nginx.*\.conf)$", re.I)
DEPLOY_DIR_RE = re.compile(r"(^|/)(\.?coolify|deploy|deployment|deployments|infra|infrastructure)(/|$)", re.I)
AUTH_RE = re.compile(r"auth|security|permission|rbac|session|oauth|sso", re.I)
NEXT_CFG_RE = re.compile(r"^(next\.config\.[^/]+|middleware\.(ts|js|mjs)|proxy\.(ts|js|mjs))$")


def git(*args):
    r = subprocess.run(["git", *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip()[:300]}")
    return r.stdout


def base(p):
    return posixpath.basename(p)


def is_config(p):
    return p in CONFIG_EXACT or bool(ENV_BASENAME_RE.match(base(p))) or bool(ENV_DOC_RE.match(p))


def is_auth(p):
    return p.startswith(("apps/api/src/", "apps/web/")) and bool(AUTH_RE.search(p))


def build(a):
    commits = []
    for line in git("log", "--no-merges", "--format=%h%x09%s", f"{a.base}..{a.head}").splitlines():
        sha, _, subj = line.partition("\t")
        commits.append((sha, subj))
    total = int(git("rev-list", "--count", f"{a.base}..{a.head}").strip())

    changed = {}
    for line in git("diff", "--name-status", "--no-renames", f"{a.base}...{a.head}").splitlines():
        status, _, path = line.partition("\t")
        changed[path] = status

    try:
        mods = git("show", f"{a.base}:{MODS_FILE}")
    except RuntimeError:
        mods = ""
    hook_paths = set(PATH_RE.findall(mods))

    def fork_only(p):
        b = base(p)
        return b.startswith(("mka-", "mka_")) or p.startswith("custom/") or p in hook_paths

    paths = sorted(changed)
    categories = [
        ("New alembic migrations",
         [p for p in paths if p.startswith(MIGRATIONS_DIR) and changed[p] == "A" and p.endswith(".py")]),
        ("Config / env changes (config.yaml/py, .env*, env.ts, env docs)", [p for p in paths if is_config(p)]),
        ("Dependency manifests and lockfiles", [p for p in paths if base(p).lower() in DEP_BASENAMES or DEP_RE.match(base(p))]),
        ("Docker / compose / deploy files", [p for p in paths if DEPLOY_BASENAME_RE.match(base(p)) or DEPLOY_DIR_RE.search(p)]),
        ("GitHub config (.github/**: workflows, actions, CODEOWNERS, mka/)", [p for p in paths if p.startswith(".github/")]),
        ("Scripts (scripts/**)", [p for p in paths if p.startswith("scripts/")]),
        ("Auth / security / permission / session code", [p for p in paths if is_auth(p)]),
        ("Next.js config / middleware / proxy", [p for p in paths if NEXT_CFG_RE.match(base(p))]),
        ("Deleted fork-only or fork-hooked files (mka-*, custom/, upstream-modifications.md)",
         [p for p in paths if changed[p] == "D" and fork_only(p)]),
        ("Touches fork hook sites (see upstream-modifications.md)", [p for p in paths if p in hook_paths]),
    ]

    groups = {"feat": [], "fix": [], "other": []}
    for sha, subj in commits:
        m = CC_RE.match(subj)
        kind = m.group(1).lower() if m else "other"
        groups[kind if kind in ("feat", "fix") else "other"].append((sha, subj))

    def fmt(sha, subj):
        subj = subj.replace("<", "&lt;").replace("@", "@​")  # no mentions/HTML from untrusted text
        pr = PR_RE.search(subj)
        link = f"https://github.com/{a.upstream_repo}/pull/{pr.group(1)}" if pr else f"https://github.com/{a.upstream_repo}/commit/{sha}"
        subj = PR_RE.sub(f"([#{pr.group(1)}]({link}))", subj) if pr else f"{subj} ([`{sha}`]({link}))"
        return f"- {subj}"

    reasons = []
    out = ["## Upstream sync\n",
           f"Merges `{a.head}` into `dev`: **{total}** upstream commit(s) ({len(changed)} files changed). "
           "Merge with a **merge commit** only (never squash/rebase) so future syncs share a merge-base.\n",
           "### Needs human attention\n"]
    for title, items in categories:
        if items:
            reasons.append(title)
            out.append(f"**{title}** ({len(items)})\n")
            out.extend(f"- `{p}`" for p in items[:MAX_LIST])
            if len(items) > MAX_LIST:
                out.append(f"- ... and {len(items) - MAX_LIST} more")
            out.append("")
        else:
            out.append(f"- {title}: none")
    out.append("")

    cfg = [p for p in paths if is_config(p)]
    if cfg:
        out.append("<details><summary>Config / env diffs (added or removed lines)</summary>\n")
        for p in cfg[:15]:
            d = git("diff", "-U0", f"{a.base}...{a.head}", "--", p).splitlines()
            body = [l for l in d if l[:1] in "+-" and not l.startswith(("+++", "---"))]
            out.append(f"`{p}`\n\n```diff")
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
    ap.add_argument("--upstream-repo", default="learnhouse/learnhouse")
    ap.add_argument("--github-output")
    a = ap.parse_args()

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
