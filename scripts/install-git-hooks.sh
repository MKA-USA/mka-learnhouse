#!/bin/sh
# One-time (idempotent) setup: point git at the tracked .githooks directory.
set -e
cd "$(git rev-parse --show-toplevel)"

if [ -d .husky ] || [ -f .pre-commit-config.yaml ] || [ -f lefthook.yml ] || grep -qE '"(husky|lefthook|simple-git-hooks)"' package.json apps/*/package.json 2>/dev/null; then
  echo "ERROR: another hook manager (husky/pre-commit/lefthook) is configured; not overriding. Integrate manually." >&2
  exit 1
fi

current=$(git config --get core.hooksPath || true)
case "$current" in
  ""|.githooks) ;;
  "$(git rev-parse --absolute-git-dir)/hooks"|.git/hooks) ;; # default location, safe to replace (post-merge is chained)
  *) echo "ERROR: core.hooksPath is already '$current'; not overriding." >&2; exit 1 ;;
esac

if ! command -v gitleaks >/dev/null 2>&1; then
  echo "ERROR: gitleaks not found. Install with: brew install gitleaks" >&2
  exit 1
fi

chmod +x .githooks/* scripts/check-forbidden-paths.sh
git config core.hooksPath .githooks
echo "Git hooks installed (core.hooksPath=.githooks); gitleaks $(gitleaks version)."
