# Roles and managed groups runbook

Spec: `docs/superpowers/specs/2026-10-07-mka-roles-groups-scope-design.md` (sections 3A, 7, 8).

## Flags
- `MKA_IDENTITY_SYNC_ENABLED` (default off): off means zero writes from any trigger.
- `MKA_IDENTITY_SYNC_ORG_IDS`: comma-separated org ids; empty means nothing is written anywhere.

## Who is in which group
- Managed groups: `Majlis: <X>` (52), `Region: <Y>` (11, including **Muqami**), `Department: <D>`, and `National/Regional/Local Amila`. Groups not in `mka_managed_group` are never touched.
- **Members** (anyone with a profile): `Majlis` and `Region` from the profile they filled in.
- **Officeholders** (proven mkausa role mailbox): groups from the mailbox. A gap in the mailbox is filled from the profile: regional and national accounts get the profile Majlis, national accounts also the profile Region. The mailbox always wins where it gives a value.
- No profile and not proven: no managed groups.

**Majlis: and Region: groups are self-selected by members. Never use them alone to restrict officeholder-only material; use Department or Level groups.**

## When groups are recomputed
- Profile saved (signup, own edit, admin edit): immediately, for each allowlisted org the user belongs to. Failures are logged and never fail the save.
- Google login: as before.
- Backfill: `POST /mka/identity/sync` (dry run first) covers users with an attribute row or a profile row. Run it once after enabling the flag to place existing members.

## Checks
- Moving a member between Majlis moves both their Majlis and Region group.
- Admin edit of a profile re-syncs that member the same way.
- The first sync after deploy creates `Region: Muqami`; existing groups are untouched.
