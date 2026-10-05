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

## Org API token: how to create it and which scopes to tick
Only an org **admin** can do this, in the ilm-dev admin UI (Organization settings, API Tokens; Pro plan). Name it e.g. `compliance-provisioner`, set an expiry,
then pick the **Full Access** permission preset (the Read-only preset is enough for reads only; `push-cycle`, `push-roster`, `push-*`, `apply` and `assign-authors` need Full Access). The UI cannot grant `users` / `organizations` rights, so the fork maps its checks onto rights it can grant (API token `rights`, `db/roles.py::Rights`):

| Resource | Actions | Needed for |
|---|---|---|
| courses + assignments | read | fork compliance / attributes **reads** (`courses.action_read` AND `assignments.action_read`; Read-only preset has both) |
| courses, activities, assignments, coursechapters, usergroups, certifications | update (all six) | fork **imports, deletes, roster writes**: `push-*`, `apply`, `assign-authors`, `reconcile --apply` (Full Access preset only) |
| courses | create, read, update, delete | apply / plan / publish / assign-authors |
| coursechapters, activities, assignments | create, read, update, delete | apply / publish |
| certifications | read | probes |
| usergroups | read | probes |

Copy the token once (it is shown once) into the macOS keychain item `MKA_LH_DEV_API_TOKEN`
(`security add-generic-password -s MKA_LH_DEV_API_TOKEN -a "$USER" -w` then paste at the prompt; never put it in a file or chat).
The fork API returns **403 "API token lacks activities.action_update, ... create the token with the 'Full Access' permission preset"** (or `courses.action_read` / `assignments.action_read` for reads) when a right is missing, and **403 "no permissions configured"** for an empty token.
`push-cycle` and `push-roster` stop at the first 403 with that message (`push-roster --apply` first sends a one-row server `dry_run` as a preflight, so a missing right
fails before anything is written). A 409 means a concurrent import hit the same key: re-run.

## Verify payloads against the real fork code (before any push)
```
bun run lh push-cycle ; bun run lh push-roster --all          # dry runs dump out/payload-cycle.json and out/payload-expected.json
FORK_API_DIR=<fork worktree>/apps/api uv run --project "$FORK_API_DIR" python scripts/validate-against-api.py
```

## Token hygiene
- Writes (`push-*`, `apply`, `assign-authors`, `reconcile --apply`) need a token created with the **Full Access** preset; narrower Custom tokens (e.g. course editing only) are refused because writes change the identity roster.
- A Read-only-preset token can still read learner lists (names, emails, answers): treat every token as a secret, store it only in the keychain / a secret manager.
- Use a SEPARATE Read-only token for any reminder or reporting workflow (Make.com, n8n); never reuse the Full Access token there.
- Rotate tokens on staff changes.
