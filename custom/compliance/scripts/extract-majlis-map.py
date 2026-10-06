#!/usr/bin/env python3
"""Extract MAJLIS_TO_REGION from the fork's mka_profile.py (single source of truth; never retype).
Usage: python3 scripts/extract-majlis-map.py  -> packages/core/src/data/majlis-regions.json"""
import ast, json, pathlib, subprocess
root = pathlib.Path(__file__).resolve().parents[1]
src = root.parents[1] / "apps/api/src/services/users/mka_profile.py"
tree = ast.parse(src.read_text())
mapping = None
for n in ast.walk(tree):
    if isinstance(n, ast.AnnAssign) and getattr(n.target, "id", "") == "MAJLIS_TO_REGION":
        mapping = ast.literal_eval(n.value)
assert mapping, "MAJLIS_TO_REGION not found"
commit = subprocess.run(["git", "-C", str(root), "log", "-1", "--format=%h", "--", str(src)], capture_output=True, text=True).stdout.strip()
out = {"_source": "apps/api/src/services/users/mka_profile.py::MAJLIS_TO_REGION", "_source_commit": commit, "majlis_to_region": mapping}
(root / "packages/core/src/data/majlis-regions.json").write_text(json.dumps(out, indent=1) + "\n")
print(len(mapping), "majlis")
