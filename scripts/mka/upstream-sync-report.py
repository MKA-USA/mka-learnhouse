#!/usr/bin/env python3
"""Fork-only: build the PR body for an upstream sync and decide the review gate.

Usage: upstream-sync-report.py [--base origin/dev] [--head upstream/dev]
                               [--upstream-repo learnhouse/learnhouse]
                               [--github-output FILE]

Prints the Markdown PR body on stdout. With --github-output, also appends
`needs_review=true|false`, `commit_count=N` and `reasons=...` lines.
Only reads git; never writes to the repo. Upstream commit text is untrusted:
it is only ever emitted into Markdown, never executed or interpolated in shell.
"""
import argparse
import re
import subprocess
import sys

MIGRATIONS_DIR = "apps/api/migrations/versions/"
CONFIG_EXACT = {"apps/api/config/config.yaml", "apps/api/config/config.py"}
CONFIG_RE = re.compile(r"(^|/)\.env[^/]*(\.example|\.sample|\.template)?$|(^|/)[^/]*\.env\.(example|sample|template)$")
WORKFLOW_RE = re.compile(r"^\.github/workflows/")
MODS_FILE = ".codebase-memory/upstream-modifications.md"
PATH_RE = re.compile(r"`((?:apps|custom|scripts|docs|\.github)/[\w./\[\]()@+-]+\.\w+)`")
CC_RE = re.compile(r"^(\w+)(?:\([^)]*\))?(!)?:\s")
PR_RE = re.compile(r"\(#(\d+)\)\s*$")
MAX_DIFF_LINES = 40


def git(*args):
    r = subprocess.run(["git", *args], capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(r.stderr)
        sys.exit(r.returncode)
    return r.stdout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="origin/dev")
    ap.add_argument("--head", default="upstream/dev")
    ap.add_argument("--upstream-repo", default="learnhouse/learnhouse")
    ap.add_argument("--github-output")
    a = ap.parse_args()

    commits = []
    for line in git("log", "--no-merges", "--format=%h%x09%s", f"{a.base}..{a.head}").splitlines():
        sha, _, subj = line.partition("\t")
        commits.append((sha, subj))
    total = int(git("rev-list", "--count", f"{a.base}..{a.head}").strip())

    changed = {}
    for line in git("diff", "--name-status", "--no-renames", f"{a.base}...{a.head}").splitlines():
        status, _, path = line.partition("\t")
        changed[path] = status

    migrations = sorted(p for p, s in changed.items() if p.startswith(MIGRATIONS_DIR) and s == "A" and p.endswith(".py"))
    config = sorted(p for p in changed if p in CONFIG_EXACT or CONFIG_RE.search(p))
    workflows = sorted(p for p in changed if WORKFLOW_RE.match(p))

    try:
        mods = git("show", f"{a.base}:{MODS_FILE}")
    except SystemExit:
        mods = ""
    hook_paths = set(PATH_RE.findall(mods))
    hooks = sorted(p for p in changed if p in hook_paths)

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
    out = []
    out.append("## Upstream sync\n")
    out.append(f"Merges `{a.head}` into `dev`: **{total}** upstream commit(s) ({len(changed)} files changed). "
               "This PR must be merged with a **merge commit** (never squash/rebase) so future syncs share a merge-base.\n")

    out.append("### Needs human attention\n")
    gates = [
        ("New alembic migrations", migrations),
        ("Config / env changes", config),
        ("Changed GitHub workflows", workflows),
        ("Touches fork hook sites (see upstream-modifications.md)", hooks),
    ]
    for title, items in gates:
        if items:
            reasons.append(title)
            out.append(f"**{title}** ({len(items)})\n")
            out.extend(f"- `{p}`" for p in items)
            out.append("")
        else:
            out.append(f"- {title}: none")
    out.append("")

    if config:
        out.append("<details><summary>Config / env diffs (added or removed lines)</summary>\n")
        for p in config:
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
    out.append("Auto-merge: **disabled** (review required)" if needs_review else "Auto-merge: **enabled** (no migrations, config, workflow or hook-site changes)")

    sys.stdout.write("\n".join(out) + "\n")
    if a.github_output:
        with open(a.github_output, "a") as f:
            f.write(f"needs_review={'true' if needs_review else 'false'}\n")
            f.write(f"commit_count={total}\n")
            f.write(f"reasons={'; '.join(reasons)}\n")


if __name__ == "__main__":
    main()
