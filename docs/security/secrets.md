# Keeping secrets out of this repo

This fork is public. Real secrets (API keys, DB passwords, tokens) live **only in Coolify server env vars**, one set per environment. `.env.example` files hold variable names and placeholder values only.

## The four layers

1. **GitHub push protection** (already enabled): rejects pushes with recognised provider secrets.
2. **CI** (`.github/workflows/secret-scan.yaml`): gitleaks over the commits in each PR/push, plus a forbidden-path check.
3. **Pre-commit hook** (`.githooks/pre-commit`): same checks locally, before the commit exists. Fails closed if gitleaks is missing.
4. **`.gitignore`**: the `MKA fork` block keeps `.env.*`, keys, and local agent state (`.hermes/`, `.kiro/`, `.serena/`, `DEVLOG*.md`, ...) from being staged by accident.

Rules live in `.gitleaks.toml` (defaults plus Coolify, Tinybird, Fireworks and DB-URL-with-password rules) and `scripts/check-forbidden-paths.sh`.

## One-time setup

```sh
brew install gitleaks && scripts/install-git-hooks.sh
```

The installer sets `core.hooksPath=.githooks` (idempotent). Emergency bypass: `SKIP_SECRET_SCAN=1 git commit ...` (prints a warning; push protection and CI still run).

## If something leaks

1. **Rotate the credential first** (Coolify, Tinybird, Fireworks, DB, ...), then update the Coolify env var.
2. Then remove it from the repo (and history if needed). Treat it as compromised regardless, since the repo is public.

## False positives

- Narrowest fix: an inline `gitleaks:allow` comment on the line.
- Otherwise add a narrow path or regex allowlist to `.gitleaks.toml` in a reviewed PR. Never allowlist broad directories.
