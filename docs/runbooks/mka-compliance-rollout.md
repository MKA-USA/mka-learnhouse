# MKA compliance + identity attributes: rollout to ilm-dev

Branch `feature/mka-compliance-integration` = attributes API (hidden identity attributes, login hook, admin/me API) +
native compliance analytics API + compliance UI. Design record: `docs/superpowers/specs/2026-10-04-mka-*.md`.
Role/access setup for viewers: `docs/runbooks/mka-compliance-roles.md`.

## What ships
- API: `/api/v1/mka/attributes/*`, `/api/v1/mka/compliance/*`; login hook in `services/auth/session.py`.
- Tables, no ALTER of upstream tables. NEW in this branch (6): `mka_user_attributes`, `mka_user_attributes_audit`,
  `mka_roster_override`, `mka_compliance_cycle`, `mka_compliance_cycle_course`, `mka_compliance_expected`.
  `mka_user_profile` (Majlis/mobile/AMC ID/tanzeem) is NOT new: it is already live on dev and holds members' data.
- Web: `/orgs/<slug>/dash/compliance`, course tab `compliance`, nav items (hooks H1-H3).

## Schema: how the tables get created (verified locally)
Nothing runs Alembic automatically (entrypoint does not call it); the API creates missing tables at startup via
`SQLModel.metadata.create_all` (`core/events/database.py::_bootstrap_schema`). So after the first deploy of this
branch the 6 new tables above already exist, with the indexes/constraints declared on the models, and `alembic_version`
does not know about them.

The three migrations (`mka_20261004_user_profile` -> `mka_20261004_user_attributes` -> `mka_20261004_compliance`,
single head, parent `b1c2d3e4f5a6`) are idempotent (every create is guarded by an inspector check). Verified on a
DB built by `create_all`: `alembic stamp b1c2d3e4f5a6 && alembic upgrade head` runs all three as no-ops and ends at
`mka_20261004_compliance (head)`; a second `upgrade head` is a no-op. Conclusion: running `alembic upgrade head`
is optional on ilm-dev but recommended once, so `alembic_version` matches the code (otherwise a later upstream
migration run starts from the wrong revision). If ilm-dev `alembic current` is neither `b1c2d3e4f5a6` nor `mka_20261004_user_profile` (the profile migration is already live on dev), stop and check
`alembic heads` before upgrading.

## Env vars
| Var | Where | Value |
|---|---|---|
| `MKA_COMPLIANCE_TZ` | API | optional; default `America/New_York`. Decides the deadline-day boundary for "overdue". |
| `MKA_GOOGLE_ONLY_DOMAINS` | API | UNCHANGED. Also feeds the identity proof (see risks). Do not edit as part of this rollout. |
| `NEXT_PUBLIC_MKA_COMPLIANCE_MOCK` | web build | MUST be unset / not `1`. (The mock is also hard-disabled when `NODE_ENV=production`, and `/examples/mka-compliance-preview*` 404s.) |
| `NEXT_PUBLIC_MKA_COMPLIANCE_REMIND` | web build | leave unset (the "Remind" placeholder stays hidden pending a product decision). |

## Order of steps
1. Back up the DB (or take a snapshot).
2. Deploy the API image of this branch. On startup `create_all` creates the 6 new tables. Check the API log for errors.
3. (Recommended) `alembic current` should show `b1c2d3e4f5a6` or `mka_20261004_user_profile`; then `alembic upgrade head` (no-ops, advances the stamp).
4. Deploy the web image (build with the env above).
5. Backfill attributes for existing Google users (idempotent, safe to repeat; it can only reuse proof recorded by a
   Google login, never create it): `cd apps/api && python -m src.services.mka.backfill --dry-run`, then without `--dry-run`.
6. Create an org API token with the **Full Access** permission preset (reads work with Read-only, writes need Full Access; the UI cannot grant users/organizations rights, so the fork maps reads to courses+assignments read and writes to courses.action_update; `push-cycle`, `push-roster`, `apply` and `assign-authors` need Full Access) and import the cycle and roster with the
   provisioner: `POST /api/v1/mka/compliance/cycles` then `POST /api/v1/mka/compliance/expected/import?org_slug=<slug>`
   (re-import is idempotent; `dry_run: true` first). Give viewers access per the roles runbook.

## Pre-go-live checklist
- Verify ONE real @atfalusa.org Google sign-in carries `hd=atfalusa.org` (or whether atfalusa.org is a secondary domain
  of the mkausa.org Workspace, in which case Google reports `hd=mkausa.org`). Until then Atfal officeholders appear
  unrecognized / not signed in.

## Post-deploy checks
- `GET /api/v1/mka/compliance/scope?org_id=<id>` as an org admin -> `scope: all`, the cycle and its courses; as a plain
  learner -> `scope: none` and no Compliance nav item.
- Overview totals: `expected` equals the imported roster size; `not_signed_in` is high until people sign in with Google
  (an account counts only when its CURRENT email was proven by a Google login).
- A course author sees only their course (other course = 404); CSV download works and is capped.
- No request to `/mka/compliance/*` returns 5xx in the API log; `Cache-Control: private, no-store` on responses.
- Sign in with Google as a test officeholder, then the admin attributes list shows the derived row.

## After an identity-rules version bump
Bumping the rules version marks stored ATTRIBUTES for refresh (the fail-closed reader reports them unrecognized, and
attribute-based compliance scope `all` is withheld until refreshed) but does NOT change who is matched in compliance or
their progress (proof depends on the mailbox only). Run `python -m src.services.mka.backfill` (or the admin recompute)
after any rules bump so attributes are refreshed.

## Rollback
- Web: redeploy the previous web image (hooks are inert without it).
- API: redeploy the previous image. The new tables are unused by old code and harmless; leave them. The login hook
  is fail-open, so the previous image is not affected by the extra rows.
- Data removal (only if requested), export first. **WARNING: never run `alembic downgrade b1c2d3e4f5a6`** - it also
  runs `mka_20261004_user_profile.downgrade()`, which drops `mka_user_profile` and DELETES every member's Majlis, mobile,
  AMC ID and tanzeem. To remove only what this branch adds use `alembic downgrade mka_20261004_user_profile` (chain:
  `b1c2d3e4f5a6` -> `mka_20261004_user_profile` -> `mka_20261004_user_attributes` -> `mka_20261004_compliance`); it drops
  the 6 new tables (imported cycles, rosters, derived attributes and audit rows). Clearing just a roster:
  `DELETE /mka/compliance/cycles/{id}/expected`.

## Known risks to keep in mind
- Identity proof for Google-only domains: a Google-signup account on a domain in `MKA_GOOGLE_ONLY_DOMAINS` is treated
  as proven for ANY address of that domain on recompute, even if its email was later changed by a non-self-service
  route (admin edit/DB). Self-service changes within a Google-only domain are blocked by `block_email_change`. Not
  reachable by normal users; revisit if admins edit emails of officeholders.
- An admin attribute override does not make an account "matched" for compliance (override is not proof of the mailbox).
