# Cycle rollout checklist (new cycle, e.g. 2027-28)

Roles: **Provisioner operator** (runs the CLI), **Aitmad/Raza** (owns the yearly data), **Mohtamims** (department plans), **Owner** (user; spot-check + publish).
Everything below is staging first; production only with the owner's explicit say-so. Run from `custom/compliance/apps/provisioner`.

| # | Step | Who | Command / action | Rollback |
|---|---|---|---|---|
| 0 | Set cycle dates | Operator | `bun run start roster --cycle 2027-28 --starts-on 2027-11-01 --deadline-on 2027-12-01` | rerun with new dates |
| 1 | Import data: roster, plans, overrides, names | Aitmad/Mohtamims supply CSVs; Operator imports | `import dept-plans|overrides|names <csv>`; then `gap-report --data <dir>` and send `out/data-gap-report.md` back for fixes | imports are idempotent; fix CSV and re-import |
| 2 | Plan | Operator | `bun run lh plan --all [--from-cycle 2026-27]` (dry run); read flags (stale plans, conflicts), `author-owned (skip)` pages and `remove` lines. `--from-cycle` seeds author pages from last cycle's courses (via course_map) | nothing written |
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

## Who edits what (department courses)
| Page / activity | Owner | Source | What `apply` does | Who changes it |
|---|---|---|---|---|
| **Your role and resources** (`role`) | Author (the Mohtamim) | Seeded once: last cycle's page if `--from-cycle` is given and that page exists, else the CSV (`responsibilities_md` + `resources_md`) | Creates it when missing; afterwards **never updates it** (plan shows `author-owned (skip)`) | The Mohtamim, in the LearnHouse editor |
| **Annual department plan and OKRs** (`plan`) | Generated | `dept_plans.csv` (`okrs_md`) | Overwrites on every change; carries a "generated" note | Update the plan with Aitmad (CSV), not the page |
| Knowledge check, Final sign-off | Generated | Built from the plan objectives / fixed template | Overwrites | Aitmad (template change) |
| **Contacts directory** (`directory`) | Generated | Roster + overrides + names | Overwrites; carries a "generated" note | Aitmad (overrides.csv / names.csv) |

Learner path (4 chapters, 5 activities): Your role > Your plan (plan page + knowledge check) > Contacts > Finish (sign-off). The old separate goals page, role-at-a-glance page and contact self-check were folded in or dropped; `apply` removes activities that left the spec, **drafts only** (it refuses a published course; `plan` dry-runs the removals).
A one-off: records created before ownership existed are handed over once (seeded from the spec) and are author-owned from then on.

## First prod push
The provisioner targets **dev** (ilm-dev) by default. Prod is a separate, guarded target; nothing below has been run yet.

**Prerequisites (all must be true before the first prod command)**
1. **The dev->prod release containing PR #46 (the fork API third course kind `majlis-plan` and its required-courses rule) is deployed on prod, and `https://ilm.mkausa.org/api/v1/mka/health/schema` shows `ok: true` and `alembic_at_head: true`.** Until then prod's `push-cycle` rejects the `majlis-plan` course ("kind must be 'general' or 'department'") and Qaideen would not be attested on the Majlis Plan. Do not push a cycle without it.
2. The Coolify DB backup for prod is recent (same rule as the sync checklist).
3. The prod org API token exists in the keychain item `MKA_LH_PROD_API_TOKEN` (Full Access preset, see "Org API token"). It is read only by `bun run lh:prod`, never printed, and never reused for dev.
4. `bun run db:migrate` has applied migration 0006 on the machine that runs the provisioner (adds `target` to `course_map`, `idmap` and `enrollment_log`; every existing row becomes `target=dev`).
5. The owner has said yes to touching prod.

**How the guard works**
- `--target dev|prod`, default `dev`. Prod needs `--confirm-prod ilm.mkausa.org` (the exact hostname from config; a flag cannot choose another host) for **any** use, reads and dry runs included. `--confirm-staging` never authorises prod.
- `--confirm-prod` only **selects** prod. Every prod write also needs an explicit `--write`: `apply`, `push-cycle/push-roster/assign-authors/sync-identity --apply`, `reconcile --apply`, `publish --execute`. Without `--write` a prod run is a dry run: `apply` prints the plan and stops, the others are refused.
- Run prod commands only through `bun run lh:prod ...` (token from `MKA_LH_PROD_API_TOKEN`). Both wrappers tag the token (`LH_TOKEN_TARGET`); the CLI refuses a dev token for prod, the prod token for dev, and any token without the tag (so never export `LH_API_TOKEN` by hand). The org slug for prod comes from the config (`TARGETS.prod.orgSlug`), not from `.env`.
- `course_map`, `idmap` and `enrollment_log` are namespaced by `target`; `out/` artefacts for prod go to `out/prod/`. A prod run never reads or updates a dev mapping, and the reverse. A prod run therefore starts with an empty `course_map` and **creates** its courses.
- `cycle-courses.json` records its `target` and `host`; `push-cycle` refuses a file from another target, and a file without a target for prod (regenerate it with `apply --write` or `export-courses` on prod).
- All the dev safety rules still apply: `apply` is drafts only, refuses to write to a published course, removals are drafts only, and publish is a separate command.

**Order (each write after its dry run; stop at the first surprise)**
```
cd custom/compliance/apps/provisioner
P="--target prod --confirm-prod ilm.mkausa.org"
bun run lh:prod plan --all $P                           # dry run: expect 22 CREATE (General, 20 department, Majlis Plan)
bun run lh:prod apply --all $P                          # no --write: prints the plan and stops
bun run lh:prod apply --all $P --write                  # creates DRAFT courses on prod; the owner spot-checks them
bun run lh:prod push-cycle $P                           # dry run, then add --apply --write
bun run lh:prod push-roster --all $P                    # dry run, then add --apply --write
bun run lh:prod assign-authors --map mohtamims.csv $P   # dry run, then --apply --write (after Mohtamims first sign in)
bun run lh:prod reconcile --all $P                      # dry run, then --apply --write
bun run lh:prod publish --all $P                        # dry run; --execute --write only with the owner's explicit say-so
```
Re-running any step is safe (idempotent upserts). Rollback is per step as in the table above, using the prod UI.

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
