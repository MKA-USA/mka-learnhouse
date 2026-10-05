# MKA compliance automation: runbook

Design record (the build contract): `docs/superpowers/specs/2026-10-05-mka-compliance-automation-design.md`.
Environment: ilm-dev (staging) only. Production is untouched. Everything ships OFF; nothing reaches an officeholder
until the product owner turns it on. This is the single runbook; `docs/runbooks/automation/*.md` only point here.

## What it does

| Seam | Trigger | Effect |
|---|---|---|
| A. Auto-enrol | A Google sign-in (login hook `attributes.mka_refresh_on_login`) | Enrols a **proven** roster person into the cycle's General course and their department course(s) |
| B. Receipts | LearnHouse webhook `assignment_submitted` (+ a daily sweep as the safety net) | One receipt per sign-off, plus one "all set" email when every required sign-off exists |
| C. Reminders | GitHub Actions cron daily 14:00 UTC (`.github/workflows/mka-automation-cron.yaml`); the course "Remind" button | Weekly reminders listing what is outstanding; Monday digest to Mohtamims / regional Qaids (role titles, no personal names) |

All mail goes through ONE function (`services/mka/automation_send.py::send_automation_email`). Dry-run is its default.
"Proven" = `attributes.is_address_proven`: fresh attributes row, `verified_hd` equals the domain of `email_seen`, and
`email_seen` equals the account's current email. An account whose email was changed to someone else's mailbox is not
proven and is never enrolled, never receipted, never treated as that role.

## Environment variables (API, read at call time: a restart is enough)

| Variable | Default | Meaning |
|---|---|---|
| `MKA_AUTOMATION_ENABLED` | `false` | Master kill switch. Feature flags count only while this is `true`. |
| `MKA_AUTOENROLL_ENABLED` | `false` | Seam A. |
| `MKA_RECEIPTS_ENABLED` | `false` | Seam B. |
| `MKA_REMINDERS_ENABLED` | `false` | Seam C: reminders, digest, Remind button. |
| `MKA_AUTOMATION_TEST_RECIPIENT` | unset | While set, EVERY email goes only to this address, subject `[TEST -> <intended>]`, logged `test_mode=true`. A malformed value refuses all sends (never falls back to real recipients). |
| `MKA_AUTOMATION_WEBHOOK_SECRET` | unset | HMAC secret of the LearnHouse webhook. Unset = every delivery rejected (401). |
| `MKA_AUTOMATION_CRON_SECRET` | unset | Value of `X-MKA-Cron-Secret` for the sweep and `reminders/run`. Unset = 503, never open. |
| `MKA_AUTOMATION_CONTACT_EMAIL` | unset | "Who to contact" line in every email and Reply-To (not in test mode). Malformed = ignored with a warning. |
| `MKA_REMINDER_SCHEDULE` | `11-08,11-15,11-22,11-28,weekly` | Reminder days: `MM-DD` (every year), `YYYY-MM-DD`, `weekly` (every 7 days after the deadline). Invalid = default + warning. |
| `MKA_REMINDER_EXCLUDED_DEPARTMENTS` | `atfal` | Department slugs never reminded. |
| `MKA_AUTOMATION_WEEKLY_REMINDER_CAP` | `1` | Reminders per person per ISO week. |
| `MKA_AUTOMATION_RUN_SEND_CAP` | `400` | Max sends per run (0 = none). |
| `MKA_AUTOMATION_SEND_DELAY_SECONDS` | `0.25` | Pause between sends (0-30). |
| `MKA_AUTOMATION_MAX_CONSECUTIVE_FAILURES` | `5` | Hard-stop a run after N failures in a row. |
| `MKA_COMPLIANCE_TZ` | `America/New_York` | Cycle timezone (week boundaries, schedule days). |
| `LEARNHOUSE_PLATFORM_URL` (or the configured frontend domain) | n/a | Base of the links in emails. Without one reminders do not send (`no_frontend_url`). |
| `NEXT_PUBLIC_MKA_COMPLIANCE_REMIND` (web, build time) | off | `1` shows the "Remind" button. |

Repository side: secret `MKA_AUTOMATION_CRON_SECRET` (environment `development`), variable
`MKA_AUTOMATION_CRON_DRY_RUN` (see below).

## Kill switches and rollback

- Stop everything: `MKA_AUTOMATION_ENABLED=false` (or unset) + restart. No send happens, auto-enrol is a no-op, the
  webhook still verifies the signature and answers `200 {"status":"disabled"}` recording nothing, the real sweep and
  real reminder runs refuse (`feature_off`). Dry runs still work. No data to undo.
- Stop one seam: its `MKA_*_ENABLED` flag to `false`.
- Keep going but only to yourself: set `MKA_AUTOMATION_TEST_RECIPIENT`.
- Stop the scheduler without a restart: set repo variable `MKA_AUTOMATION_CRON_DRY_RUN` back to `true` or disable the
  workflow. A run also stops by itself at the per-run cap or after N consecutive failures.
- Inspect without sending: `GET /api/v1/mka/automation/status?org_slug=<slug>` (admin session or read-only token):
  flags, masked test address, send-log and event counts. No secrets, no recipients.
- Schema rollback (rarely needed): `alembic downgrade mka_20261004_compliance` drops the two tables.

## Manual setup for the product owner (nothing here is automated)

1. **Coolify, project ilm-dev, API app** set: `MKA_AUTOMATION_WEBHOOK_SECRET` (the `whsec_...` from step 3; you may
   need to create the webhook first), `MKA_AUTOMATION_CRON_SECRET` (long random), `MKA_AUTOMATION_TEST_RECIPIENT` (your
   own address), `MKA_AUTOMATION_CONTACT_EMAIL`, and `LEARNHOUSE_PLATFORM_URL` if not already derived. Leave every
   `*_ENABLED` flag unset/false for now. Redeploy/restart the API. Optional web build arg
   `NEXT_PUBLIC_MKA_COMPLIANCE_REMIND=1` for the Remind button.
2. **GitHub**: Settings > Environments > `development` > secret `MKA_AUTOMATION_CRON_SECRET` (same value as Coolify).
   Optional repo variable `MKA_AUTOMATION_CRON_DRY_RUN`: the scheduled run is a dry run unless it is exactly `false`.
   The workflow also works with the secret unset: it logs `::notice::` and exits 0 without calling anything.
3. **Webhook in LearnHouse**: as org admin open `/dash/developers/automations` > add endpoint.
   URL `https://ilm-dev.mkausa.org/api/v1/mka/automation/webhooks/learnhouse`, events `assignment_submitted` and
   `course_completed`, and put the signing secret (shown once) into `MKA_AUTOMATION_WEBHOOK_SECRET`. The endpoint's
   ping/test action should give `200` (ignored event); `401` = secret mismatch; `400` = stale body.
4. **Courses published**: auto-enrol skips draft courses (see below). Publish the cycle's courses before roster people
   sign in, or accept that they are enrolled on their next login after publishing.

## Dry run from the Actions tab

Actions > "MKA Automation Cron" > Run workflow. Leave `dry_run` ticked (default), pick `kind`
(`all` / `reminder` / `digest`). The log shows a JSON report per org: `ran` / `reason`, `candidates`, `would_send`,
`skipped_recent`, `skipped_attested`, `skipped_excluded`. Counts only (no addresses, names). A dry run sends and writes
nothing. Reasons you may see: `cycle_not_started`, `not_a_reminder_day`, `not_a_monday` (for a preview anyway,
temporarily add today's `MM-DD` to `MKA_REMINDER_SCHEDULE`). The same run then calls `receipts/sweep` (also dry).
HTTP 503 = cron secret unset on the API; 401 = GitHub secret differs from the API value.

## Review the test emails

1. `MKA_AUTOMATION_TEST_RECIPIENT=<your address>`, `MKA_AUTOMATION_ENABLED=true`, and the flag(s) under test; restart.
2. Trigger: reminders = run the workflow with `dry_run` unticked on a reminder day; receipts = submit a sign-off as a
   proven roster user (or POST a signed delivery locally, see Local verification); auto-enrol = sign in with Google.
3. Mail arrives only in your inbox with a "TEST MODE" banner and subject `[TEST -> person@...]`. Check the greeting
   (role title + Majlis for role mailboxes), the course list, link, contact line, and that no other person's name leaks.
4. Test sends obey the same weekly dedupe: a second test run in the same ISO week sends nothing. To repeat a review
   send, delete the org's test rows: `delete from mka_automation_send_log where org_id=<id> and test_mode;`
   (`automation_gdpr.purge_test_rows` does the same).

## Turn real sending on (product owner present)

1. A test run looked right and `/status` shows the expected flags.
2. Unset `MKA_AUTOMATION_TEST_RECIPIENT`. From now on email goes to officeholders.
3. Set repo variable `MKA_AUTOMATION_CRON_DRY_RUN=false` so the daily schedule sends. Watch the first report
   (`sent`, `failed`, `stopped`). Each person gets at most one reminder per ISO week.

## Rollout order

1. Deploy with everything off. Confirm `/status` (flags false) and a dry run from the Actions tab.
2. Webhook + secrets (above), test recipient set. Enable `MKA_AUTOMATION_ENABLED` + `MKA_RECEIPTS_ENABLED`; review a
   receipt, replay a delivery, run the sweep dry then real: all quiet. Then `MKA_AUTOENROLL_ENABLED`; sign in as a
   test roster user. Then `MKA_REMINDERS_ENABLED`; review reminder + digest mail.
3. Real sending last (previous section). Seams can be enabled one at a time; any one can be turned off alone.

## Behaviour to know

- **Unpublished courses (auto-enrol)**: skipped and recorded (`skipped_unpublished`, once per user+course); the next
  login after publishing enrols them.
- **Stale or malformed webhook**: body timestamp older than 10 minutes (or >60 s in the future) or malformed JSON
  gives `400`; bad/missing signature gives `401` with an empty body. LearnHouse retries 3 times with the same
  `delivery_id`, then drops the event. The **daily sweep is the safety net**: it delivers any receipt the webhook
  missed (look-back `days`, default 7) with the same dedupe keys, so nothing is sent twice. `delivery_id` replays
  answer `duplicate` and send nothing.
- **Recipient of a receipt** is the account email looked up from `user_uuid`; email/name in the payload are never read.
- **Reminder recipients**: people whose status on a required course is not signed in, not started, in progress,
  overdue, or completed-but-not-signed-off; deduplicated by email; never `attested`; role mailboxes are addressed by
  role title and Majlis.
- **Remind button**: org admins and active authors of that course only (in scope, else 404; learners 403; API tokens
  403); preview first, one real remind per course per 24 h (429); shares the weekly per-person cap.
- **Claim before send**: a `queued` row (unique per org, kind, dedupe key) is committed before the transport is called.
  Crash between claim and send leaves `queued` (at most once); a `failed` row is retried by the next run.
- Anonymised and demo addresses are never mailed.

## What the log tables hold

- `mka_automation_event`: one row per webhook delivery / auto-enrol decision (`delivery_id`, `event`, `status`
  `processed|ignored|skipped_unpublished|error|...`, `user_id`/`user_uuid`, `course_uuid`, `note`). No payload bodies,
  no email addresses.
- `mka_automation_send_log`: one row per attempted email (`kind` receipt|allset|reminder|digest, `dedupe_key`,
  `to_email` (actual), `intended_email`, `status` queued|sent|failed|..., `test_mode`, `user_id` when known).
  Reminder key `reminder:<ISO week>:<email>`, digest `digest:<ISO week>:<email>`, receipt
  `receipt:<assignment_uuid>:<user_id>`, all-set `allset:<cycle_id>:<user_id>`.

## GDPR and the 18-month purge

- Export and anonymise cover event and send-log rows by `user_id` ONLY, and expected-roster rows for the user's PROVEN
  address. No proof = nothing email-keyed is exported or touched.
- Roster rows on anonymise: a personal address is deleted; an org role mailbox (identity parser matches a role) is an
  office, so the row is kept and only `person_name` / `appointed_on` are nulled.
- Send-log rows keyed only by email (an office mailbox that never signed in) describe the office and are left to the
  retention purge.
- Retention: `automation_gdpr.purge_older_than(db, months=18)` deletes send-log rows and events older than 18 months.
  **It is not scheduled yet**: run it by hand (or wire a CLI/cron) at least quarterly until that is done.

## Local verification

- `uvx ruff@0.15.9 check ./apps/api`
- `cd apps/api && uv run --with greenlet python -m pytest src/tests/services/mka src/tests/routers -q -k mka`
  (includes `tests/routers/test_mka_automation_integration.py`: enrol -> signed webhook -> receipt -> replay/sweep ->
  all-set, reminders dry/real/weekly cap, unproven and role-address accounts, kill switches, GDPR).
- Web: `cd apps/web && bun test tests`, `bunx tsc --noEmit`, `bun run build` (mock layer off).
- Local signed delivery (local secret, mocked/sunk mail): sign the exact raw body with HMAC-SHA256 and send header
  `X-Webhook-Signature: sha256=<hex>`; example in `docs/runbooks/automation/receipts.md`.
