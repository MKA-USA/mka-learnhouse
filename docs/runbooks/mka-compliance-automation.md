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
| `MKA_REMINDER_WINDOW_DAYS` | `4` | A scheduled reminder date opens a window of this many days (1-7, the date itself counts). A run on any day inside it keeps reminding the people not yet reminded; outside every window a run does nothing (`not_a_reminder_day`). `1` = the scheduled date only. |
| `MKA_AUTOMATION_WEEKLY_REMINDER_CAP` | `1` | Reminders per person per ISO week. Values above 1 have no effect: the weekly dedupe key allows exactly one scheduled reminder per person per week. Leave it at 1. |
| `MKA_AUTOMATION_RUN_SEND_CAP` | `400` | Max sends per run (0 = none). Safety stop, not the batch size: a run that hits it reports `remaining` and the next run (same or next day, inside the window) continues. |
| `MKA_AUTOMATION_RUN_TIME_BUDGET_SECONDS` | `90` | A run stops sending after this many seconds and returns `{remaining, time_budget_hit}`; the workflow calls again. Keeps every HTTP call well inside the 150 s curl limit. |
| `MKA_AUTOMATION_CLAIM_LEASE_SECONDS` | `900` | A send-log row left `queued` longer than this (crash between claim and send) is taken over once and re-sent. A younger `queued` row is another run's send in flight. |
| `MKA_AUTOMATION_SEND_DELAY_SECONDS` | `0.25` | Pause between sends (0-30). |
| `MKA_AUTOMATION_MAX_CONSECUTIVE_FAILURES` | `5` | Hard-stop a run after N failures in a row. |
| `MKA_COMPLIANCE_TZ` | `America/New_York` | Cycle timezone (week boundaries, schedule days). |
| `LEARNHOUSE_PLATFORM_URL` (or the configured frontend domain) | n/a | Base of the links in emails. Without one reminders do not send (`no_frontend_url`). |
| `NEXT_PUBLIC_MKA_COMPLIANCE_REMIND` (web, build time) | off | `1` shows the "Remind" button. |

Repository side: secret `MKA_AUTOMATION_CRON_SECRET` (environment `development`), variable
`MKA_AUTOMATION_CRON_DRY_RUN` (see below). Generate the cron secret **alphanumeric only**: the workflow passes it to
curl inside a quoted config line, where `"` and `\` are escapes.

## Kill switches and rollback

- Stop everything: `MKA_AUTOMATION_ENABLED=false` (or unset) + restart. No send happens, auto-enrol is a no-op, the
  webhook still verifies the signature and answers `200 {"status":"disabled"}` recording nothing, the real sweep and
  real reminder runs refuse (`feature_off`). Dry runs still work. No data to undo.
- Stop one seam: its `MKA_*_ENABLED` flag to `false`.
- Keep going but only to yourself: set `MKA_AUTOMATION_TEST_RECIPIENT`.
- Stop the scheduler without a restart: set repo variable `MKA_AUTOMATION_CRON_DRY_RUN` back to `true` or disable the
  workflow. A run also stops by itself at the per-run cap or after N consecutive failures.
- Inspect without sending: `GET /api/v1/mka/automation/status?org_slug=<slug>` (admin session or read-only token):
  flags, masked test address, send-log and event counts, `autoenroll.errors_recent` (failed auto-enrolments in the last
  7 days: must be 0) and `send_log.stale_queued` (claims stuck in `queued` past the lease: should be 0 after a run).
  No secrets, no recipients.
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
   (`sent`, `failed`, `remaining`, `time_budget_hit`). Each person gets at most one scheduled reminder per ISO week.
4. **The first real receipt sweep after the test address is removed sends real receipts / all-set mails for every
   sign-off of the previous 7 days**, including ones you already reviewed in test mode (test sends live in their own
   dedupe namespace and never count as done). If that is not wanted, run the sweep once by hand first with a short
   look-back: `POST .../receipts/sweep?dry_run=false&days=1` (header `X-MKA-Cron-Secret`), then enable the schedule.
5. Going live is one variable: deleting or blanking `MKA_AUTOMATION_TEST_RECIPIENT` turns real sending on for ~1,400
   mailboxes (once the flags and the cron variable are on). Treat that variable like a production switch.

## Deploy checklist (before and right after enabling anything)

1. **Auto-enrol, post-deploy check**: sign in once with a Google account that is on the roster, then
   `GET /status`: `autoenroll.errors_recent` must be `0`. Any other number means enrolment is failing (login still
   works); look for `error` events with note `enrol_failed:<ExceptionName>`. (An optional `\d trailrun` on ilm-dev
   showing `uq_trailrun_trail_course_user` is a nice-to-have, no longer a precondition.)
2. **Reminder sizing**: `MKA_AUTOMATION_RUN_SEND_CAP` x `MKA_REMINDER_WINDOW_DAYS` must cover the expected outstanding
   count (default 400 x 4 = 1,600 for ~1,400 people), or raise the cap. Alert on a non-zero `remaining` that is still
   there when the window closes. The workflow's `curl --max-time` is 150 s and each call is bounded by the 90 s time
   budget; a proxy in front of the API must allow at least that.
3. Keep `NEXT_PUBLIC_MKA_COMPLIANCE_REMIND` off until the cycle and test-recipient checks above are done. (The button
   now only works for the current started cycle and is tied to its preview.)
4. Cron secret alphanumeric only (see the repository-side note above).
5. At go-live expect the first real sweep to send receipts for the past 7 days; run it once with `days=1` if that is
   not wanted ("Turn real sending on", step 4).
6. After each run check `/status`: `send_log.stale_queued` must be 0 (a stuck claim is taken over automatically once
   past the lease, so a persistent number means the same row keeps failing).
7. Schedule `automation_gdpr.purge_older_than(db, months=18)` (not wired yet) and `purge_test_rows` after review.
8. Confirm the webhook ping from `/dash/developers/automations` returns 200 (the container-to-public-URL hairpin is
   unverified). The workflow now fails on any non-2xx from `reminders/run` or `receipts/sweep`, a 404 included.

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
  403). It only acts on the **current, already-started cycle** (the server resolves it; any other cycle is 409, preview
  included, and the web disables the button with an explanation). Preview first: the preview returns a `preview_digest`
  of exactly who would be mailed and the real send must present it; if the list changed in between (more, fewer or
  different people) the send is refused with 409 and the dialog asks to review again. One COMPLETE real remind per
  course per 24 h (429); a run that stops early (time budget / send cap) reports `remaining`, does not hold the slot and
  can simply be run again (nobody is mailed twice). Manual reminders have their own allowance (`manual:<course_id>:
  <ISO week>:<email>`: one per person per course per week) and do not use up the person's weekly scheduled reminder.
- **Reminder runs are fair and resumable**: people already reminded in the current window / ISO week are dropped before
  the per-run cap applies; the rest go least-recently-reminded first. A run stops at the time budget or the cap and
  says how many are left. The cron workflow calls `reminders/run` again (at most 10 calls, `curl --max-time 150`) while
  the server reports `time_budget_hit` and `remaining > 0`; leftovers after a send-cap stop wait for the next daily
  run inside the window. With ~1,400 outstanding people and the default cap of 400, a window needs 4 daily runs
  (`MKA_REMINDER_WINDOW_DAYS=4`); raise the cap, not the window, if you want it done in one day.
- **Claim before send**: a `queued` row (unique per org, kind, dedupe key) is committed before the transport is called.
  A crash between claim and send leaves `queued`; once it is older than the lease (default 15 min) the next attempt
  (webhook retry or the daily sweep) takes it over atomically and sends once more (the row is marked
  `reclaimed_stale_queued`, so a second crash is not retried forever). A younger `queued` row is another run's send in
  flight and counts as handled. A `failed` row is retried by the next run.
- **Auto-enrol does not need the `uq_trailrun_trail_course_user` constraint**: it checks for an existing run under a
  per-user lock and inserts only if there is none. A failure never breaks login; it is recorded as an `error` event
  (`enrol_failed:<ExceptionName>`) and counted in `/status` as `autoenroll.errors_recent`.
- Anonymised and demo addresses are never mailed.

## What the log tables hold

- `mka_automation_event`: one row per webhook delivery / auto-enrol decision (`delivery_id`, `event`, `status`
  `processed|ignored|skipped_unpublished|error|...`, `user_id`/`user_uuid`, `course_uuid`, `note`). No payload bodies,
  no email addresses.
- `mka_automation_send_log`: one row per attempted email (`kind` receipt|allset|reminder|digest, `dedupe_key`,
  `to_email` (actual), `intended_email`, `status` queued|sent|failed|..., `test_mode`, `user_id` when known).
  Scheduled reminder key `reminder:<ISO week of the window start>:<email>`, manual remind
  `manual:<course_id>:<ISO week>:<email>`, digest `digest:<ISO week>:<email>`, receipt
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
