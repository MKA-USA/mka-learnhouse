# MKA compliance automation: runbook (skeleton)

Design record: `docs/superpowers/specs/2026-10-05-mka-compliance-automation-design.md` (the build contract).
Environment: ilm-dev (staging) only. Production is untouched. Status: **foundation (seam S1) only**: config, tables,
the central send function, templates, `GET /api/v1/mka/automation/status`. Auto-enrol (A), receipts/webhook (B) and
reminders/cron (C) land in later seams; sections marked TODO are filled in as they land.

## What ships in the foundation
- Tables `mka_automation_event` and `mka_automation_send_log` (migration `mka_20261005_automation`, idempotent; the API
  also creates them at startup via `create_all`). No ALTER of upstream tables.
- `services/mka/automation_send.py::send_automation_email`: the only code path that sends automation email.
- `GET /api/v1/mka/automation/status` (org admin session or Read-only-or-better org API token): flags, test mode (masked
  address), row counts. No secrets, no recipients.
- GDPR: export + anonymise cover the automation rows and the expected-roster rows; 18-month retention purge function.

## Environment variables
All are read at call time (a restart is enough; no rebuild). Everything defaults to OFF / safe.

| Variable | Default | Meaning |
|---|---|---|
| `MKA_AUTOMATION_ENABLED` | `false` | Master kill switch. Per-feature flags below only count while this is `true`. |
| `MKA_AUTOENROLL_ENABLED` | `false` | Auto-enrol on first Google sign-in (seam A). |
| `MKA_RECEIPTS_ENABLED` | `false` | Sign-off receipts + "all set" email (seam B). |
| `MKA_REMINDERS_ENABLED` | `false` | Reminders + weekly digest (seam C). |
| `MKA_AUTOMATION_TEST_RECIPIENT` | unset | When set, EVERY automation email goes only to this address, subject prefixed `[TEST -> <intended>]`, logged with `test_mode=true`. A malformed value REFUSES all sends (it never falls back to real recipients). |
| `MKA_AUTOMATION_WEBHOOK_SECRET` | unset | HMAC secret for the LearnHouse webhook (seam B). Unset = every delivery rejected. |
| `MKA_AUTOMATION_CRON_SECRET` | unset | Value of the `X-MKA-Cron-Secret` header for scheduler endpoints (seam C). Unset = 503, never open. Also a GitHub repo secret of the same name. |
| `MKA_AUTOMATION_CONTACT_EMAIL` | unset | "Who to contact" shown in every email and used as Reply-To (not in test mode). Malformed = ignored with a warning. |
| `MKA_REMINDER_SCHEDULE` | `11-08,11-15,11-22,11-28,weekly` | Reminder days: `MM-DD` (every year), `YYYY-MM-DD` (that day only), `weekly` = every 7 days after the cycle deadline. Invalid = default + warning. |
| `MKA_AUTOMATION_RUN_SEND_CAP` | `400` | Max sends per run (0 = send nothing). |
| `MKA_AUTOMATION_SEND_DELAY_SECONDS` | `0.25` | Pause between sends in a run (0-30). |
| `MKA_AUTOMATION_MAX_CONSECUTIVE_FAILURES` | `5` | Hard-stop a run after this many failures in a row. |
| `MKA_AUTOMATION_WEEKLY_REMINDER_CAP` | `1` | Max reminders per person per ISO week. |
| `MKA_COMPLIANCE_TZ` | `America/New_York` | Cycle timezone (existing variable): week boundaries, schedule days, receipt timestamps. |

## Manual steps for the product owner (spec section 7; none are coded)
1. On ilm-dev set `MKA_AUTOMATION_WEBHOOK_SECRET`, `MKA_AUTOMATION_CRON_SECRET`, `MKA_AUTOMATION_TEST_RECIPIENT` (your own
   address) and `MKA_AUTOMATION_CONTACT_EMAIL`. Leave every enable flag off until the test sends are reviewed.
2. Add the GitHub repository secret `MKA_AUTOMATION_CRON_SECRET` (same value).
3. In `/dash/developers/automations` create the webhook: URL
   `https://ilm-dev.mkausa.org/api/v1/mka/automation/webhooks/learnhouse`, the same secret as
   `MKA_AUTOMATION_WEBHOOK_SECRET`, events `assignment_submitted` and `course_completed`. (TODO seam B: confirm endpoint.)
4. Review the test emails. Only then remove `MKA_AUTOMATION_TEST_RECIPIENT` and enable the flags, with the product owner present.

## Kill switch and rollback
- Stop everything: set `MKA_AUTOMATION_ENABLED=false` (or unset it) and restart the API. Every send returns `disabled`
  without touching the log; dry runs still work. No data migration to undo.
- Stop only one feature: set its `MKA_*_ENABLED` flag to `false`.
- Keep sending but only to yourself: set `MKA_AUTOMATION_TEST_RECIPIENT`.
- Check state without sending anything: `GET /api/v1/mka/automation/status?org_slug=<slug>` (admin session or Read-only token).
- Test-mode sends use their own dedupe namespace (`test:` prefix), so they never block the real send of the same email.
  To re-run a review send, delete the org's test-mode rows (`automation_gdpr.purge_test_rows`).
- Schema rollback (rarely needed): `alembic downgrade mka_20261004_compliance` drops the two tables.

## Test-send procedure (TODO: fill in as seams B/C land)
Placeholder. Intended flow: set `MKA_AUTOMATION_TEST_RECIPIENT` to your address, run the relevant endpoint with
`dry_run=true` first (returns what WOULD be sent, touches nothing), then `dry_run=false` with the flags on for the
feature under test; every email arrives at the test address with the intended recipient in the subject prefix.
Open question for seams B/C: a "send me a test" path while the feature flag is still off (the central sender
refuses real sends when the flag is off; only dry runs bypass the flag).

## Safety envelope (what the foundation guarantees)
- Dry-run is the default of the send function; a real send needs an explicit `dry_run=False`.
- Claim before send: a `queued` row (unique per org, kind, dedupe key) is committed before the transport is called;
  retries and concurrent runs get `already_handled`. A crash between claim and send leaves `queued` (at most once);
  a `failed` row is retried by the next run.
- Reminders: at most `MKA_AUTOMATION_WEEKLY_REMINDER_CAP` per person per ISO week; per-run send cap, pacing, and a
  stop after consecutive failures (`SendBudget`).
- Anonymised (`anonymized.example.com`, `anonymized.invalid`) and demo addresses are never mailed.

## Data retention and GDPR
- Export (`profile_status(include_attributes=True)`) and anonymise (`delete_profile`) cover automation events and
  send-log rows by `user_id` ONLY, plus expected-roster rows for the user's PROVEN address (fresh attributes row with
  Workspace proof of that exact address, `attributes.is_address_proven`). No proof = nothing email-keyed is exported
  or touched (a user can change their email to a mailbox they do not own).
- Roster rows on anonymise: a personal address is DELETED; an org ROLE mailbox (identity parser matches a role) is an
  office, so the row is KEPT and only `person_name` / `appointed_on` are nulled (the next holder inherits the seat).
- Send-log rows keyed only by email (reminders to a never-signed-in role mailbox) describe the office and are left
  alone; the retention purge removes them.
- Retention: `automation_gdpr.purge_older_than(db, months=18)` deletes older send-log rows and events. TODO: wire a
  scheduled/CLI invocation (not scheduled yet).

## Local verification
`cd apps/api && uv run --with greenlet python -m pytest src/tests/services/mka src/tests/routers -q -k mka`
and `uvx ruff@0.15.9 check ./apps/api` (CI pins 0.15.9).
