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
cp .env.example .env              # set COMPLIANCE_DB_PASSWORD (openssl rand -hex 16) and LH_ORG_SLUG=default
bun run db:up                     # docker postgres bound to 127.0.0.1:5433 (password from .env)
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

## Provisioner commands (run from `apps/provisioner`; `lh` wraps the keychain token + `.env`)
```
bun run start roster | import ... | seed-thinkific | gap-report      # data (no LearnHouse access)
bun run lh plan --pilot                                  # dry run (default): General + Aitmad + Tabligh
bun run lh apply --confirm-staging --pilot               # creates DRAFT courses on STAGING only (refuses any other host)
bun run lh reconcile --pilot                             # dry run: enroll existing users only
bun run lh reconcile --pilot --apply --confirm-staging
```
`apply` needs `--pilot`, `--only a,b` or `--all`; it never publishes (API wrappers reject `published: true`) and is idempotent
through `course_map` (change detection per activity). Outputs: `out/idmap.json`, `out/apply-report.md`, `out/reconcile-report.md`, `out/data-gap-report.md`.
Formats for yearly CSV data: `docs/data-formats.md`.

## Publishing (explicit, never automatic)
`plan`, `apply` and `reconcile` never publish: courses, activities and assignments stay drafts, and the API wrappers reject `published: true`.
A human publishes with the separate command (staging only, **dry run by default**, prints exactly what it will flip):
```
bun run lh publish --course "MKA 2026-27 · Tabligh"                     # dry run (name or uuid)
bun run lh publish --all                                                # dry run, every provisioned course
bun run lh publish --course <name|uuid> --execute --confirm-staging     # sets published=true on activities, assignments, then the course
```
Courses stay `public: false` (visible to enrolled learners only).

## Cycle -> courses mapping
`bun run start export-courses` (also run by `apply`) writes `out/cycle-courses.json`: cycle, deadline, and per course the activity uuids plus the
assignment/task uuids of the final sign-off and the contact self-check, for the in-LearnHouse analytics view.

## Unconfirmed
Regional department mailboxes `{dept}.{region}@mkausa.org` (200 roster rows, source `formula-unconfirmed`) come from the Thinkific directories and are not yet confirmed by the user. Atfal has none (no evidence).
