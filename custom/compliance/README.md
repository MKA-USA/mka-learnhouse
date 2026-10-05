# MKA compliance companion (fork-isolated)

Companion service for the annual officeholder compliance training. Lives in `custom/compliance/`,
is its **own Bun project** and is deliberately NOT in the monorepo root workspaces, so pulling upstream
LearnHouse never conflicts with it. It talks to LearnHouse only through the HTTP API.

## Layout
- `packages/core`: Drizzle schema (`src/schema`), department seed (`src/seed`), LearnHouse client (`src/lh`).
- `apps/provisioner`: CLI skeleton + read-only `probe`.
- `apps/dashboard`: reserved for the dashboard workstream (empty).
- `scripts/with-lh-token.sh`: runs a command with `LH_API_TOKEN` from the macOS keychain (item `MKA_LH_DEV_API_TOKEN`), never printing it.
- `docs/lh-api-notes.md` (verified endpoints), `docs/probe-report.md` (latest staging scope matrix).

## Run
```bash
cd custom/compliance
bun install
cp .env.example .env              # optional; set LH_ORG_SLUG
bun run db:up                     # docker postgres on :5433
bun run db:migrate                # applies packages/core/drizzle/*.sql
bun run db:seed                   # idempotent upsert of 21 departments
bun test packages apps            # unit tests (no DB or network needed)
bun run typecheck
bun run probe                     # READ-ONLY GETs against STAGING; writes docs/probe-report.md
bun run db:generate               # after editing the schema
```
The analytics tables (`progress_snapshot`, ...) belong to the dashboard workstream: add `schema/analytics.ts` and re-export it from `schema/index.ts`.

## Rules
Staging only (`ilm-dev.mkausa.org`); the probe refuses other hosts. No secrets in files: the token lives only in the keychain.
The client logs only `METHOD path status`, redacts emails in paths and keeps response bodies out of errors.
