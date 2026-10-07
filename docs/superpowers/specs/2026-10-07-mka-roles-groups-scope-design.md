# MKA roles, user groups and reporting scope — design / build contract

Date: 2026-10-07. Status: approved by the user (decisions below). Fork-only unless stated. Base: `origin/dev`.

## 0. Job to be done

When an MKA officeholder signs in to Ilm with their role mailbox, the platform should already know what they may do and who they belong to: a Mohtamim can create and run courses for their department; every officeholder sits in the groups for their Majlis, region, department and level; and a Qaid, Naib Qaid, Mohtamim or Naib Mohtamim can see completion reports for exactly the people they are responsible for. Nobody is added by hand.

## 1. Decisions (user, 2026-10-07)

- **D1 Mohtamim rights:** own courses + their department course. Create courses; edit/publish courses they created or are an ACTIVE author of. No rights over other courses, users, roles or org settings.
- **D2 Assignment:** automatic from the mailbox on sign-in, re-synced every sign-in, plus a bulk backfill for existing accounts. Admins/maintainers are never downgraded.
- **D3 Groups:** Majlis (52), Region (10), Department (20, Atfal excluded like the roster), Level (National Amila, Regional Amila, Local Amila). A person is in every group that applies.
- **D4 Reporting scope:** Compliance page only (no upstream Analytics change). Scope by attributes: Mohtamim and Naib Mohtamim → own department; Regional Qaid and Naib → own region; Majlis Qaid and Naib → own Majlis. Sadr/Motamid/Aitmad/admins keep `all`.

## 2. Facts the build relies on (verified 2026-10-07 on origin/dev)

- Roles: `db/roles.py` `Role(org_id, role_type, role_uuid, rights JSON)`, membership `UserOrganization(user_id, org_id, role_id)`. Built-ins are GLOBAL ids 1 admin, 2 maintainer, 3 instructor, 4 user. Custom org roles are supported (`routers/roles.py`, `services/roles/*`, type `TYPE_ORGANIZATION`). Course creation needs `courses.action_create` (`security/rbac/resource_access.py:_check_create_permission`); creator becomes `ResourceAuthor` CREATOR. Google SSO hardcodes `role_id=4` on first join (`services/auth/utils.py` ~273) — do NOT change it.
- Login hook: `services/auth/session.py:issue_session_or_challenge` → `mka_refresh_on_login(db_session, user, amr)` (fork, `services/mka/attributes.py`), which then calls `_autoenroll_after_refresh`. Fail-open, Google only, own DB session, `is_address_proven` gate. New sync work hangs off the same place: **no new upstream hook**.
- Attributes (`services/mka/attributes.py`): `status, is_officeholder, level, department, role, role_title, majlis, region`. Mohtamim = `role == "mohtamim"`, level national. Rules `identity_rules/2026.3.json`. Check how the parser names Naib roles (`naib_mohtamim`, `naib_qaid`, regional naib) and extend the rules file (bump to 2026.4) if a Naib role is not recognised; the user wants Naibs covered.
- Groups: `db/usergroups.py` `UserGroup(org_id, name, description, usergroup_uuid)`, `UserGroupUser(usergroup_id, user_id, org_id)`, many-to-many, names NOT unique, duplicates rejected in `services/users/usergroups.py:add_users_to_usergroup`. Groups gate course access (OR of linked groups) via `_check_usergroup_membership`. API `routers/usergroups.py` (`POST /`, `POST /{id}/add_users?user_ids=`, `DELETE /{id}/remove_users`). No "groups of a user" endpoint.
- Compliance scope today: `services/mka/compliance_scope.py:resolve_scope` returns `all|own|none`; `own` = ACTIVE author of a cycle course. Nav shows Compliance when scope != none (`DashLeftMenu.tsx:845`, `DashMobileMenu.tsx:236`). Learner endpoints in `routers/mka_compliance.py` (`/overview`, `/courses/{uuid}/summary`, `/learners`, `/learners.csv`, `/remind`).
- Provisioner: `custom/compliance/apps/provisioner` (`bun run lh …`), canonical Majlis/region/department lists in `custom/compliance/packages/core` config; `assign-authors` already makes Mohtamims contributors of their department course. Staging token in keychain `MKA_LH_DEV_API_TOKEN` (Full Access preset includes `usergroups` update).
- Upstream-fork policy: new files under `services/mka/`, `routers/mka_*.py`, `apps/web/components/mka/**`, `custom/**`. Any touch of an upstream file = one tagged `# MKA fork` line + an entry in `.codebase-memory/upstream-modifications.md` with the verbatim diff.

## 3. Components

### A. Identity sync: Mohtamim role + groups (seam A)

New module `apps/api/src/services/mka/identity_sync.py` plus a small fork table and a router.

**A1 Role definition (constant in code, applied idempotently):** org-scoped role, `role_type=TYPE_ORGANIZATION`, name `Mohtamim`, description "MKA department head: creates and runs courses for their department". Rights = Instructor's rights plus: `coursechapters` create/read/update, `activities` create/read/update, `assignments` create/read/update, `media` and `folders` create/read/update/delete, `usergroups.action_read`, `dashboard.action_access`, `organizations.action_read`. No `users`, `roles`, `organizations.update`, no non-own course update/delete. Store the binding in fork table `mka_managed_role(org_id, key='mohtamim', role_id, rights_version)`; `ensure_mohtamim_role(org_id)` creates or updates the role when `rights_version` changes (PUT via the roles service, never the HTTP layer). Migration file `mka_20261007_identity_sync.py`, idempotent (`IF NOT EXISTS`), plus the `create_all` guard the other fork tables use.

**A2 Group catalogue:** fork table `mka_managed_group(org_id, key, usergroup_id)` with keys `majlis:<slug>`, `region:<slug>`, `department:<slug>`, `level:national|regional|local`. Display names: `Majlis: Albany`, `Region: Northeast`, `Department: Maal`, `National Amila`, `Regional Amila`, `Local Amila`. Description "Managed by MKA identity sync; membership follows the role mailbox". Canonical lists come from the identity rules JSON (regions, departments) and the Majlis list the roster uses; if the API has no Majlis list, read it from `identity_rules` (add a `majalis` section) rather than hardcoding twice. `ensure_groups(org_id)` creates missing groups through `services/users/usergroups.create_usergroup` (no HTTP) and records them; renames in the UI do not matter because the key, not the name, is the binding. Never delete or touch groups not in the table.

**A3 Per-user sync (login):** `sync_user_identity(db, org_id, user)` called from `attributes.py` right after `_autoenroll_after_refresh`, same failure handling (fail-open, log, never block login), gated by env `MKA_IDENTITY_SYNC_ENABLED` (default false) and `is_address_proven`.
- Desired groups from effective attributes: `majlis:<majlis>` when majlis set; `region:<region>` when region set; `department:<department>` when department set; `level:<level>` when is_officeholder. Add missing memberships (direct `UserGroupUser` insert, skip duplicates); remove the user from managed groups no longer desired; never touch unmanaged groups.
- Role: if attributes say `role in {mohtamim, naib_mohtamim}` and level national and current `role_id == 4` → set to the Mohtamim role id. If current role is the managed Mohtamim role and attributes no longer qualify → set `role_id = 4`. Never change role ids 1, 2, 3 or any other custom role. Invalidate the session cache the same way `update_user_role` does (`routers.users._invalidate_session_cache` or equivalent). Do not send the role-change email.
- Idempotent: a second sign-in with the same attributes performs zero writes.

**A4 Backfill endpoint:** `POST /mka/identity/sync?org_slug=&dry_run=true` (org admin session or org API token with `organizations.action_update`): ensures role + groups, then iterates every org user with a stored attribute row and runs A3; returns counts `{users_seen, groups_created, memberships_added, memberships_removed, roles_set, roles_reverted, errors}` and, in dry-run, the planned changes capped at 200 rows. Pace to stay under existing rate limits; no per-user HTTP calls. Also `GET /mka/identity/status?org_slug=` → flag state, role id, group count, last sync time.

**A5 Tests** (`src/tests/services/mka/test_identity_sync.py`, routers test): role created once and updated on rights_version bump; a local Nazim Maal in Albany/Northeast lands in exactly `department:maal, majlis:albany, region:northeast, level:local`; a national Mohtamim gets the role and `department`, `level:national`; an admin keeps role 1; attribute change moves groups and reverts role; disabled flag = zero writes; duplicates on second run = zero writes; API token org boundary on the backfill.

### B. Provisioner + runbook (seam B, after A's contract is fixed)

- `bun run lh sync-identity [--apply --confirm-staging] [--dry-run]` calls A4 and prints the counts; `bun run lh identity-status`.
- `custom/compliance/docs/runbooks/roles-and-groups.md`: what the role grants, the group catalogue, how to limit a course to groups (Course → Access → link groups; OR semantics; the picker is a plain select, search by typing), how to run the backfill, env flag, rollback (set flag false; roles stay as set).
- Update `docs/runbooks/mka-compliance-rollout.md` with the new step (after `push-roster`).

### C. Attribute-based reporting scope (seam C)

Extend `compliance_scope.py` so `resolve_scope` can return a **filter**, not only `all|own|none`:
- `ScopeResult = {kind: all|filtered|none, department?: str, region?: str, majlis?: str, courses: [...]}`.
- Rules (attributes, address proven): `mohtamim` / `naib_mohtamim` (national) → `filtered{department}`; `qaid` / `naib_qaid` regional → `filtered{region}`; `qaid` / `naib_qaid` local → `filtered{majlis}`. Existing `all` rules unchanged; course-authorship `own` remains as a fallback for people without attributes.
- Every compliance read endpoint (`/overview`, `/courses/{uuid}/summary`, `/learners`, `/learners.csv`) and `/remind` applies the filter server-side to the expected-roster rows (department / region / majlis columns on `mka_compliance_expected`), so a Majlis Qaid's overview is their Majlis only and the CSV never contains other rows. `/scope` returns the new shape; keep `scope: "own"|"all"|"none"` for backward compatibility plus `filter`.
- Web: `useMkaComplianceScope` and the Compliance page read the new shape; nav unchanged (shows when kind != none). Page header shows the scope ("Your Majlis: Albany").
- Tests: unit vectors per role (incl. Naibs), router tests proving a regional Qaid cannot read another region's learners or CSV, and that `remind` is limited to the filtered set.

## 4. Environment and rollout

- Env: `MKA_IDENTITY_SYNC_ENABLED` (default `false`). Dev: set `true` after merge; prod: later, by the user. Add the compose pass-through line on both services when switching on.
- Rollout on dev: merge → deploy → `identity-status` → `sync-identity --dry-run` → review counts → `--apply` → sign in as a test Mohtamim mailbox → confirm role, groups, course creation, Compliance scope.
- Identity rules bump to 2026.4 if Naib roles are added; admins must recompute attributes after deploy (existing endpoint).

## 5. Out of scope

Upstream Analytics page access; AND-combined groups; changing the SSO default role; UI redesign of the group picker (noted as a later nicety); Atfal.

## 6. Acceptance

1. tabligh@ signs in on dev: role = Mohtamim, groups = Department: Tabligh + National Amila, can create a course, Compliance shows Tabligh only.
2. nazim.maal.albany@ signs in: role User, groups = Department: Maal + Majlis: Albany + Region: Northeast + Local Amila, no Compliance nav.
3. qaid.albany@: Compliance shows Albany only; CSV has only Albany rows; Remind reaches only Albany.
4. Backfill dry-run on the 126-row pilot reports counts; apply is idempotent on rerun.
5. All API tests green (`uv run --no-sync --with greenlet pytest src/tests/services/mka src/tests/routers -q`), web tests green, no upstream file touched except the documented one-line hook if any.
