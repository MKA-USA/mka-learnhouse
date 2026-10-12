#!/usr/bin/env python3
"""Fork-only: publish-job check of a sync candidate's TREE against a trusted recomputation.

  upstream-sync-verify-diff.py --p1 SHA --up SHA --cand-tree TREE --mode clean|ai-resolved --out-dir DIR

Recomputes `git merge-tree --write-tree -z --name-only P1 UP` (the pure merge + our own conflicted set),
then:
  clean        : candidate tree must equal the pure merge tree            (else exit 2 = tampering)
  ai-resolved  : candidate may differ from the pure merge ONLY in
                 - files that conflicted in this recomputation,
                 - lockfiles (uv.lock/bun.lock) whose manifest (pyproject.toml/package.json) conflicted,
                 - .codebase-memory/upstream-modifications.md,
                 - new alembic revision files;
                 never in CI-sensitive paths (.github/, scripts/, Docker/compose, bun/npm config,
                 .gitattributes/.gitmodules), never symlinks/submodules, never file-mode changes.
                 A CONFLICT in a CI-sensitive path also blocks.
Paths are NUL-delimited (-z) and matched on a NFC/case-folded key. Prints key=value lines:
verdict=ok|blocked, reason=..., pure_tree=.... Writes DIR/conflicts.safe and DIR/conflicts.md (display-escaped).
Run from a TRUSTED checkout; it only reads objects.
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mka_gitpaths import dec, disp, git, mode_changed, norm, parse_raw_z, special  # noqa: E402

PROT = re.compile(
    r"^(\.github/|scripts/|\.bun-version$|(.*/)?\.npmrc$|(.*/)?bunfig\.toml$|(.*/)?dockerfile[^/]*$"
    r"|(.*/)?docker-compose[^/]*$|(.*/)?\.gitattributes$|(.*/)?\.gitmodules$)")
MIGRATION = re.compile(r"^apps/api/migrations/versions/[a-z0-9_]+\.py$")
MODS = ".codebase-memory/upstream-modifications.md"


def parse_merge_tree(out):
    toks = out.split(b"\0")
    tree = dec(toks[0])
    names = []
    for t in toks[1:]:
        if t == b"":
            break
        names.append(dec(t))
    return tree, names


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--p1", required=True)
    ap.add_argument("--up", required=True)
    ap.add_argument("--cand-tree", required=True)
    ap.add_argument("--mode", choices=["clean", "ai-resolved"], required=True)
    ap.add_argument("--out-dir", required=True)
    a = ap.parse_args()

    rc, out = git("merge-tree", "--write-tree", "--name-only", "-z", "--no-messages", a.p1, a.up, allow_rc=(0, 1))
    pure_tree, conflicts = parse_merge_tree(out)
    cset = {norm(c): c for c in conflicts}

    with open(os.path.join(a.out_dir, "conflicts.safe"), "w") as f:
        f.writelines(disp(c) + "\n" for c in sorted(conflicts))
    with open(os.path.join(a.out_dir, "conflicts.md"), "w") as f:
        f.writelines(f"- `{disp(c)}`\n" for c in sorted(conflicts))

    def emit(verdict, reason=""):
        print(f"pure_tree={pure_tree}")
        print(f"verdict={verdict}")
        print("reason=" + "".join(ch for ch in reason if ch.isprintable())[:200])
        sys.exit(0)

    if a.mode == "clean":
        if rc == 0 and a.cand_tree == pure_tree:
            emit("ok")
        sys.stderr.write("clean candidate differs from the pure merge\n")
        sys.exit(2)

    prot_conf = [c for c in conflicts if PROT.match(norm(c))]
    if prot_conf:
        emit("blocked", "conflicts in CI-sensitive paths need a human (not pushing AI output): " + ", ".join(disp(c) for c in prot_conf[:3]))

    _, raw = git("diff", "--raw", "-z", "--no-renames", "--no-ext-diff", "--no-textconv", pure_tree, a.cand_tree)
    bad = []
    for e in parse_raw_z(raw):
        p = e["paths"][0]
        n = norm(p)
        if special(e):
            bad.append(f"{disp(p)} (symlink/submodule)")
        elif mode_changed(e):
            bad.append(f"{disp(p)} (file mode change)")
        elif PROT.match(n):
            bad.append(f"{disp(p)} (CI-sensitive path)")
        elif n in cset or n == MODS:
            pass
        elif e["status"] == "A" and MIGRATION.match(n):
            pass
        else:
            d, b = os.path.dirname(n), os.path.basename(n)
            manifest = {"uv.lock": "pyproject.toml", "bun.lock": "package.json"}.get(b)
            if manifest and (f"{d}/{manifest}" if d else manifest) in cset:
                pass
            else:
                bad.append(f"{disp(p)} (not in conflicted set)")
    if bad:
        emit("blocked", "AI changed files outside the conflicted set (rejected, not pushed): " + ", ".join(bad[:4]))
    emit("ok")


if __name__ == "__main__":
    main()
