"""Fork-only helpers: parse git path output safely (NUL-delimited, never line/quote based).

Every path decision in the upstream-sync tooling goes through here so the report script and the
publish-job verifier cannot disagree (parser differentials) about what a path is.
Any entry we cannot parse raises, and callers fail safe (needs_review / abort).
"""
import os
import subprocess
import unicodedata

SPECIAL_MODES = {"120000", "160000"}  # symlink, gitlink (submodule)
ZERO_MODE = "000000"


def git(*args, allow_rc=(0,)):
    """Run git with repo-controlled drivers neutralised; returns (rc, stdout bytes)."""
    env = dict(os.environ, GIT_ATTR_NOSYSTEM="1", GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0")
    cmd = ["git", "-c", "core.attributesFile=/dev/null", "-c", "core.fsmonitor=false", "-c", "core.quotePath=false", *args]
    r = subprocess.run(cmd, capture_output=True, env=env)
    if r.returncode not in allow_rc:
        raise RuntimeError(f"git {' '.join(args)[:120]} failed rc={r.returncode}: {r.stderr.decode('utf-8', 'replace')[:200]}")
    return r.returncode, r.stdout


def dec(b):
    return b.decode("utf-8")  # strict: undecodable path => raise => fail safe


def norm(p):
    """Match key: Unicode-NFC + case-folded, so case/normalisation tricks cannot dodge a category."""
    return unicodedata.normalize("NFC", p).lower()


def weird(p):
    """Paths we never trust to render or match normally."""
    return (not p.isprintable()) or p != p.strip() or "\\" in p or p.startswith("/") or ".." in p.split("/")


def disp(p):
    s = p if p.isprintable() else p.encode("unicode_escape").decode("ascii")
    return s.replace("`", "'")


def parse_raw_z(out):
    """Parse `git diff --raw -z` output into [{status, old_mode, new_mode, paths}] (paths: 1, or 2 for R/C)."""
    toks = out.split(b"\0")
    i, entries = 0, []
    while i < len(toks):
        t = toks[i]
        if t == b"":
            i += 1
            continue
        if not t.startswith(b":"):
            raise ValueError("unparseable diff entry")
        f = t[1:].split(b" ")
        if len(f) != 5:
            raise ValueError("unexpected raw field count")
        old_mode, new_mode = dec(f[0]), dec(f[1])
        status = dec(f[4])
        if not status or status[0] not in "AMDTRC":
            raise ValueError(f"unknown status {status!r}")
        n = 2 if status[0] in "RC" else 1
        paths = [dec(x) for x in toks[i + 1:i + 1 + n]]
        if len(paths) != n or any(p == "" for p in paths):
            raise ValueError("missing path in diff entry")
        entries.append({"status": status[0], "old_mode": old_mode, "new_mode": new_mode, "paths": paths})
        i += 1 + n
    return entries


def special(e):
    return e["old_mode"] in SPECIAL_MODES or e["new_mode"] in SPECIAL_MODES


def mode_changed(e):
    return e["old_mode"] != e["new_mode"] and ZERO_MODE not in (e["old_mode"], e["new_mode"])
