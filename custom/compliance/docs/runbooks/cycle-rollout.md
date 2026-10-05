# Cycle rollout checklist (new cycle, e.g. 2027-28)

Roles: **Provisioner operator** (runs the CLI), **Aitmad/Raza** (owns the yearly data), **Mohtamims** (department plans), **Owner** (user; spot-check + publish).
Everything below is staging first; production only with the owner's explicit say-so. Run from `custom/compliance/apps/provisioner`.

| # | Step | Who | Command / action | Rollback |
|---|---|---|---|---|
| 0 | Set cycle dates | Operator | `bun run start roster --cycle 2027-28 --starts-on 2027-11-01 --deadline-on 2027-12-01` | rerun with new dates |
| 1 | Import data: roster, plans, overrides, names | Aitmad/Mohtamims supply CSVs; Operator imports | `import dept-plans|overrides|names <csv>`; then `gap-report --data <dir>` and send `out/data-gap-report.md` back for fixes | imports are idempotent; fix CSV and re-import |
| 2 | Plan | Operator | `bun run lh plan --all` (dry run); read flags (stale plans, conflicts) | nothing written |
| 3 | Apply pilot | Operator | `bun run lh apply --confirm-staging --pilot` | delete the draft courses in the LearnHouse UI (and the `course_map` rows); never published |
| 4 | Spot-check | Owner | open the drafts, check lessons, tables, quizzes, attestation tasks as a test learner | edit content in CSV/templates, `apply` again (updates in place) |
| 5 | Apply the rest | Operator | `apply --confirm-staging --all` after the owner approves | as step 3 |
| 6 | Push cycle | Operator | `push-cycle` (dry run) then `--apply --confirm-staging` | `push-cycle` is an idempotent upsert; re-run |
| 7 | Push roster | Operator | `push-roster --all` then `--apply --confirm-staging`; read `out/push-roster-report.json` | fork `DELETE /mka/compliance/cycles/{id}/expected` clears it for a re-import |
| 8 | Assign authors | Operator with `mohtamims.csv` from Aitmad | `assign-authors --map mohtamims.csv` then `--apply --confirm-staging`; re-run after Mohtamims first sign in | set the contributor INACTIVE in the UI |
| 9 | Enroll | Operator | `reconcile --all` (dry run) then `--apply --confirm-staging`; schedule it (users appear at first Google sign-in) | `POST /admin/{org}/enrollments/bulk/unenroll` |
| 10 | Publish | **Owner (human)** | `bun run lh publish --all` (dry run lists the flips), then `--execute --confirm-staging`, or publish in the UI | unpublish in the UI |
| 11 | Monitor | Operator | scheduled `reconcile`; the fork API serves the analytics | n/a |

Confirmed: regional department mailbox pattern `{dept}.{region}@mkausa.org` (2026-10-05). Open before go-live: Muqami as a Majlis; the fork's deployment of the compliance API.

**Atfal is excluded by config** (decision 2026-10-05): no Atfal course, no Atfal roster rows (national, regional or local `@atfalusa.org` roles), no Atfal rows pushed or enrolled, and the analytics/gap counts leave it out
(those accounts cannot be proven under the Google-only SSO and would show as "not signed in" forever). The switch is `DEFAULT_EXCLUDED_DEPARTMENTS` in `packages/core/src/config.ts`.
To include Atfal later: pass `--include-atfal` to `roster`, `plan`, `apply`, `export-courses`, `push-cycle`, `push-roster`, `reconcile`, `publish`, `assign-authors` and `gap-report` (or empty the list),
run `bun run db:seed -- --include-atfal` (flips `department.active`), then `roster`, `plan`, `apply --only atfal`, and re-push. Removing Atfal after it was provisioned: re-run `roster` (prunes generated rows), delete the draft course by hand; the toolkit never deletes LearnHouse courses.

## Org API token: how to create it and which scopes to tick
Only an org **admin** can do this, in the ilm-dev admin UI (Organization settings, API Tokens; Pro plan). Name it e.g. `compliance-provisioner`, set an expiry,
then tick exactly these rights (API token `rights`, `db/roles.py::Rights`):

| Resource | Actions | Needed for |
|---|---|---|
| **users** | read | fork compliance **reads**, user lookups by email (`users.action_read`) |
| **organizations** | update | fork **imports and deletes**: `push-cycle`, `push-roster` (`organizations.action_update`) |
| courses | create, read, update, delete | apply / plan / publish / assign-authors |
| coursechapters, activities, assignments | create, read, update, delete | apply / publish |
| certifications | read | probes |
| usergroups | read | probes |

Copy the token once (it is shown once) into the macOS keychain item `MKA_LH_DEV_API_TOKEN`
(`security add-generic-password -s MKA_LH_DEV_API_TOKEN -a "$USER" -w` then paste at the prompt; never put it in a file or chat).
The fork API returns **403 "API token lacks users.action_read" / "organizations.action_update"** when a right is missing, and **403 "no permissions configured"** for an empty token.
`push-cycle` and `push-roster` stop at the first 403 with that message (`push-roster --apply` first sends a one-row server `dry_run` as a preflight, so a missing right
fails before anything is written). A 409 means a concurrent import hit the same key: re-run.

## Verify payloads against the real fork code (before any push)
```
bun run lh push-cycle ; bun run lh push-roster --all          # dry runs dump out/payload-cycle.json and out/payload-expected.json
FORK_API_DIR=<fork worktree>/apps/api uv run --project "$FORK_API_DIR" python scripts/validate-against-api.py
```
