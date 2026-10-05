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
bun run db:seed                   # idempotent upsert of 21 departments (Atfal is stored with `active=false`)
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
bun run lh plan --pilot                                  # dry run (default): General + Aitmad + Tabligh (all other commands: Atfal excluded unless --include-atfal)
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

## Excluded departments (Atfal is OFF by default)
Product decision 2026-10-05: ignore Atfal for now. One config concept, `DEFAULT_EXCLUDED_DEPARTMENTS = ["atfal"]` in `packages/core/src/config.ts`
(`resolveConfig`, `activeDepartments`, `withoutExcluded`), is the only place that knows. Everything derives from it: `roster` (no Atfal `person_role` rows: no national,
regional or local `nazim.{majlis}@atfalusa.org` / `murabbi.{majlis}@atfalusa.org`; stale generated rows are pruned), `plan` / `apply` / `publish` / `export-courses`
(no Atfal course; `out/cycle-courses.json` has General + 20 department courses), `push-cycle`, `push-roster`, `reconcile`, `gap-report` (counts exclude Atfal),
`assign-authors` (CSV rows for Atfal are skipped with a message). `--only atfal` fails with a clear error. The `department` table keeps Atfal as a canonical department with `active=false`.
**Switch it back on:** add `--include-atfal` to the commands (roster, plan, apply, push-*, reconcile, gap-report), or empty the config list; then `roster`, `plan`, `apply`.
Roster totals (52 Majlis): 27 national + 210 regional (10 regional Qaids + 200 regional department officers) + 1143 local (52 x 22 minus the Muqami Qaid, which is `muqami@`) = **1380** (was 1485 with Atfal).

## Unconfirmed flag
Regional department mailboxes `{dept}.{region}@mkausa.org` are CONFIRMED (2026-10-05) and use source `formula`. The mechanism stays for anything else unconfirmed:
rows with source `formula-unconfirmed` (`UNCONFIRMED_SOURCE` in `roster/generate.ts`) are pushed with `formula_unconfirmed: true` and counted in the gap report.

## Fork compliance API (push to the in-LearnHouse analytics)
Not deployed anywhere yet; nothing here has been applied. All commands are dry-run by default and refuse non-staging hosts.
```
bun run lh push-cycle [--apply --confirm-staging] [--starts-on 2026-11-01 --deadline-on 2026-12-01]
bun run lh push-roster --all|--pilot|--only a,b [--apply --confirm-staging] [--batch-size 1000] [--server-dry-run]
bun run lh assign-authors --map mohtamims.csv [--apply --confirm-staging]
```
Cycle dates are config, not code: flags > `cycle` table row > built-in default for known labels (`roster --starts-on ... --deadline-on ...` stores them).
`push-cycle` sends `out/cycle-courses.json` to `POST /mka/compliance/cycles`; `push-roster` sends the expected roster (every role of the non-excluded departments, regional included;
rows with source `formula-unconfirmed` carry `formula_unconfirmed: true`, currently none) to `POST /mka/compliance/expected/import` in batches (API limit 2000). Auth: org API token plus `org_slug`.
Per-row errors go to `out/push-roster-report.json`; console shows counts only. Runbook: `docs/runbooks/cycle-rollout.md`.

## Contract check against the fork's real code
`scripts/validate-against-api.py` imports the fork's actual request models and validators (cycles, expected import, contributor routes, `CONTACT_CHECK_RULES`)
and validates the payloads dumped by the dry runs (`out/payload-*.json`). See `docs/runbooks/cycle-rollout.md`. Mid-year appointees: add an `appointed_on`
(YYYY-MM-DD) column to `directory_overrides.csv`; it is sent as `appointed_on` and the fork derives the due date from it.
Token rights needed: create the org API token with the **Full Access** preset (reads work with Read-only, writes need Full Access; the UI cannot grant users/organizations rights) (runbook).
