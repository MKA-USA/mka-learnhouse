# MKA roles and groups (identity sync)

Audience: an Ilm org admin or the person running the provisioner. Design: `docs/superpowers/specs/2026-10-07-mka-roles-groups-scope-design.md`.

## What it does
When an officeholder signs in with their role mailbox, the platform (a) gives national Mohtamim and Naib Mohtamim accounts the **Mohtamim** role and (b) puts every officeholder in the groups that match their Majlis, region, department and level. Nobody is added by hand. Sync runs on every Google sign-in (fail-open: a sync problem never blocks login) and can be run in bulk as a backfill.

It is off until `MKA_IDENTITY_SYNC_ENABLED=true` and `MKA_IDENTITY_SYNC_ORG_IDS` lists the org (see below).

## The Mohtamim role
Applies to `mohtamim` and `naib_mohtamim` at national level, only when the account's current role is plain User (role id 4).

| Grants | Does not grant |
|---|---|
| Everything the Instructor role has, so Mohtamims can create courses | Users, roles, or organization settings |
| Chapters, activities and assignments: create, read, update | Edit or delete of courses they did not create and are not an ACTIVE author of |
| Media and folders: create and read only; update and delete come from authorship of one's own items | |
| Read user groups, dashboard access, read organization | |

A Mohtamim edits and publishes courses they created or are an ACTIVE author of. The provisioner's `assign-authors` already makes each Mohtamim a contributor on their department course.

If an org already has a custom role named "Mohtamim", the sync **adopts** it: its rights are overwritten with the managed set above, and holders who do not qualify are reverted to User. Review that role's current holders before the first `--apply`.

Rules the sync never breaks:
- Admin (1), Maintainer (2), Instructor (3) and any other custom role are never changed.
- If someone stops qualifying (attributes change) and still holds the Mohtamim role, they are set back to User.
- The Google sign-in default role stays User. No role-change email is sent.

## Group catalogue
Exact display names. The binding is a stored key, not the name, so renaming a group in the UI is safe. Groups outside the catalogue are never touched.

| Kind | Count | Display names | Who is in it |
|---|---|---|---|
| Majlis | 52 | `Majlis: Albany`, `Majlis: <name>` ... | officeholders of that Majlis |
| Region | 10 | `Region: East`, `Region: Great Lakes`, `Region: Gulf`, `Region: Midwest`, `Region: New York Metro`, `Region: Northeast`, `Region: Northwest`, `Region: Southeast`, `Region: Southwest`, `Region: Virginia` | officeholders of that region |
| Department | 20 | `Department: Maal`, `Department: Tabligh`, ... (Atfal excluded, like the roster) | officeholders of that department |
| Level | 3 | `National Amila`, `Regional Amila`, `Local Amila` | officeholders at that level |

Description on each: "Managed by MKA identity sync; membership follows the role mailbox". A person is in every group that applies. Example: a local Nazim Maal in Albany sits in `Department: Maal`, `Majlis: Albany`, `Region: Northeast` and `Local Amila`.

## Limit a course to groups
1. Open the course, **Access** tab, link groups.
2. The group picker is a plain select. Search by typing the display name.
3. **OR caveat:** several linked groups mean a learner needs membership in **any one** of them. There is no AND. To target "Maal people in Albany" you cannot combine `Department: Maal` AND `Majlis: Albany`; link the narrowest single group instead.
4. Membership is whatever the sync last wrote. A person whose mailbox attributes change moves groups at their next sign-in or the next backfill.

## Backfill existing accounts
Run after the API with this feature is deployed and attributes are recomputed (admins: recompute attributes after a deploy that bumps the identity rules version). Token: Full Access preset org API token in the keychain item `MKA_LH_DEV_API_TOKEN`. Staging only.

```
cd custom/compliance/apps/provisioner
bun run lh identity-status
bun run lh sync-identity                          # dry run (default): counts, nothing written
bun run lh sync-identity --apply --confirm-staging
bun run lh identity-status
```

- Console shows counts only: `users_seen, groups_created, memberships_added, memberships_removed, roles_set, roles_reverted, errors`.
- Per-row detail (the planned changes, capped at 200 in a dry run) goes to `out/sync-identity-report.json`.
- Run the dry run first and read the counts. `roles_set` should match the number of national Mohtamim and Naib Mohtamim accounts you expect.
- Re-running `--apply` is idempotent: the second run reports zero added, removed, set and reverted.
- Exit code is 1 if the server reports any errors.
- `identity-status` prints `enabled`, `role_id`, `group_count`, `last_sync_at`. The flag gates **all writes**: with it off, both sign-in sync and `sync-identity --apply` write nothing. A dry run always works regardless of the flag.

## Enable the sign-in sync
Two env vars on the **API** service:

| Var | Value |
|---|---|
| `MKA_IDENTITY_SYNC_ENABLED` | default `false`; `true` allows writes |
| `MKA_IDENTITY_SYNC_ORG_IDS` | comma-separated org ids the sync may write to; **required**. Empty means the sync writes nothing anywhere. On ilm-dev the org id is `1` (slug `default`). |

Both must allow the org before anything is written. The deployment compose file must pass both through on both services that run the API code (same pattern as the other `MKA_*` vars):

```
- MKA_IDENTITY_SYNC_ENABLED=${MKA_IDENTITY_SYNC_ENABLED:-false}
- MKA_IDENTITY_SYNC_ORG_IDS=${MKA_IDENTITY_SYNC_ORG_IDS:-}
```

Set it in the deploy environment (dev: `true` after merge; prod: later, by the owner) and redeploy. Set `MKA_IDENTITY_SYNC_ORG_IDS=1` on ilm-dev. Confirm with `bun run lh identity-status` (`enabled true`).

## Verify after enabling
1. Sign in as a test Mohtamim mailbox (for example `tabligh@`): role is Mohtamim, groups are `Department: Tabligh` and `National Amila`, and course creation works.
2. Sign in as a local Nazim (for example `nazim.maal.albany@`): role stays User, four groups as above, no Compliance nav.

## Rollback
1. Set `MKA_IDENTITY_SYNC_ENABLED=false` (or empty `MKA_IDENTITY_SYNC_ORG_IDS` to stop one org or all) and redeploy. All writes stop: sign-in sync and `sync-identity --apply` do nothing. A dry run still works.
2. Roles and group memberships already written **stay as set**; nothing is reverted automatically.
3. To undo a role by hand: Settings, Users, open the person, set the role back to User. To remove a group: Settings, User groups. Do not delete managed groups; remove members instead. Deleting one drops every course Access link to it, and a recreated group gets a new id. If one is deleted, run `sync-identity --apply` to recreate it and re-link courses by hand.
