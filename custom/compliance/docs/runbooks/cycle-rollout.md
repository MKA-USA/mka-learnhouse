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

Open confirmations before go-live: regional department mailbox pattern `{dept}.{region}@mkausa.org`; Muqami as a Majlis; Atfal regional officers; the fork's deployment of the compliance API.
