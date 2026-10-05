# Runbook: compliance reminders, weekly digest, "Remind" button (seam C)

Spec: `docs/superpowers/specs/2026-10-05-mka-compliance-automation-design.md` section 2C.
Everything here ships OFF and in dry-run. Nothing reaches an officeholder until the product owner says so.

## What it does

| Piece | Who triggers it | What it sends |
|---|---|---|
| Reminder run | GitHub Actions, daily 14:00 UTC (`.github/workflows/mka-automation-cron.yaml`) | One email per person listing the courses still outstanding, on reminder days only |
| Weekly digest | same run, Mondays only | To each Mohtamim (their department) and regional Qaid (their region): counts + role titles still to follow up. No personal names |
| "Remind" button | A course author / org admin on the course Compliance tab | Same reminder email, for that one course |

Recipients: people whose status on a required course of the active cycle is not signed in, not started, in progress,
overdue, or completed-but-not-signed-off. Deduplicated by email (a person with two roles gets one email). Never
`attested`. Departments in `MKA_REMINDER_EXCLUDED_DEPARTMENTS` (default `atfal`) are skipped.

Schedule: `MKA_REMINDER_SCHEDULE` in the cycle timezone `MKA_COMPLIANCE_TZ` (default `America/New_York`). Default for
2026-27: Nov 8, 15, 22, 28 (final), then every 7 days after the cycle deadline while someone is overdue. The deadline day
itself is not overdue. On any other day the run does nothing and says why (`not_a_reminder_day`).

## Environment variables (API)

| Variable | Default | Meaning |
|---|---|---|
| `MKA_AUTOMATION_ENABLED` | false | Master kill switch |
| `MKA_REMINDERS_ENABLED` | false | Reminders + digest + Remind button (needs the master switch too) |
| `MKA_AUTOMATION_TEST_RECIPIENT` | unset | When set, EVERY email goes only to this address, subject `[TEST -> intended]` |
| `MKA_AUTOMATION_CRON_SECRET` | unset | Shared secret for the cron endpoint. Unset means the endpoint answers 503 |
| `MKA_AUTOMATION_CONTACT_EMAIL` | unset | "Questions? Write to ..." line in the emails |
| `MKA_REMINDER_SCHEDULE` | `11-08,11-15,11-22,11-28,weekly` | `MM-DD` (every year), `YYYY-MM-DD`, `weekly` |
| `MKA_REMINDER_EXCLUDED_DEPARTMENTS` | `atfal` | Comma-separated department slugs never reminded |
| `MKA_AUTOMATION_WEEKLY_REMINDER_CAP` | 1 | Reminders per person per ISO week |
| `MKA_AUTOMATION_RUN_SEND_CAP` | 400 | Max sends per run |
| `MKA_AUTOMATION_SEND_DELAY_SECONDS` | 0.25 | Pause between sends |
| `MKA_AUTOMATION_MAX_CONSECUTIVE_FAILURES` | 5 | Hard stop of a run after N failed sends in a row |
| `LEARNHOUSE_PLATFORM_URL` (or the configured frontend domain) | - | Base of the link in the emails. Without one nothing is sent (`no_frontend_url`) |

Web (build time): `NEXT_PUBLIC_MKA_COMPLIANCE_REMIND=1` shows the "Remind" button. Off, the button does not render.

## GitHub setup (once)

1. Pick a long random value for the secret and set it in Coolify as `MKA_AUTOMATION_CRON_SECRET` for the dev API.
2. Repo Settings > Environments > `development` > add secret `MKA_AUTOMATION_CRON_SECRET` with the same value.
3. Optional: repo variable `MKA_AUTOMATION_CRON_DRY_RUN`. The scheduled run is a dry run unless this is exactly `false`.

The workflow never prints the secret (masked, passed to curl on stdin, no `set -x`).

## Run a dry run from the Actions tab

Actions > "MKA Automation Cron" > Run workflow. Leave `dry_run` ticked, pick `kind`. The log shows the JSON report:
per org, per kind: `ran` / `reason`, `candidates`, `would_send`, `skipped_recent`, `skipped_attested`,
`skipped_excluded`. Counts only: no addresses or names. A dry run sends nothing and writes nothing to the send log.
On a non-reminder day the report says `not_a_reminder_day`; to preview anyway, temporarily set
`MKA_REMINDER_SCHEDULE` to include today's `MM-DD`.

First dry run in practice: in the weeks before the cycle starts you get `cycle_not_started`. Once the cycle has started
and today is a reminder day you get one entry per org with `candidates` close to the number of roster people who have
not signed off yet (most of them `not_signed_in` on day one), `would_send` equal to that, and `skipped_recent` 0.

## Review the real emails safely (test recipient)

1. Set `MKA_AUTOMATION_TEST_RECIPIENT=<product owner's address>`, `MKA_AUTOMATION_ENABLED=true`,
   `MKA_REMINDERS_ENABLED=true`. Restart the API.
2. Run the workflow with `dry_run` unticked (reminder day, or temporarily adjust the schedule; the digest needs a Monday).
3. Every email lands in the test inbox with a red "TEST MODE" banner and subject `[TEST -> person@...]`. The send log
   marks them `test_mode=true`; test sends never count toward the weekly cap and never mark a real send as done.
   A malformed test address refuses all sending (fail closed).
4. Check: greeting (role title + Majlis for role mailboxes), course list, link, contact line, no other person's name.

## Turn real sending on (with the product owner present)

1. Confirm a test run looked right and `GET /api/v1/mka/automation/status` shows the flags you expect.
2. Remove `MKA_AUTOMATION_TEST_RECIPIENT` (leave it unset or empty). From this moment emails go to officeholders.
3. Set the repo variable `MKA_AUTOMATION_CRON_DRY_RUN=false` (so the daily schedule sends) and deploy.
4. Watch the first run's report: `sent`, `failed`, `stopped`. Each person gets at most one reminder per ISO week.

## Kill switch

Set `MKA_AUTOMATION_ENABLED=false` (or `MKA_REMINDERS_ENABLED=false`) and restart: runs report `feature_off`, the
button answers 409, nothing is sent. Faster, no restart: set the repo variable `MKA_AUTOMATION_CRON_DRY_RUN` back to
`true` or disable the workflow. A run also stops by itself at the per-run cap or after N consecutive failures.

## The "Remind" button

Course Compliance tab > Remind. The dialog first shows a preview ("12 people will be reminded, 5 skipped: already
reminded this week"), then sends on confirm. Rules enforced on the server:

- Only org admins and active authors of that course (the course must be in your compliance scope: otherwise 404). Learners
  get 403/404, API tokens always 403.
- At most one real remind per course per 24 hours (429). A preview does not use the slot. A failed-to-start send
  (switched off, bad test address) does not use it either.
- It shares the weekly per-person cap with the daily run, so nobody gets two in a week.
- In test mode the preview says so, and nothing goes to the people listed.

## Weekly caps and dedupe, in one place

- Reminder dedupe key: `reminder:<ISO week>:<email>` (unique in the send log). The row is claimed before the email
  leaves, so concurrent runs, retries and manual clicks cannot double-send. A failed send is retried by the next run.
- Digest key: `digest:<ISO week>:<email>`; once per recipient per week.
- ISO weeks are computed in the cycle timezone.

## Troubleshooting

| Report says | Meaning |
|---|---|
| HTTP 503 | `MKA_AUTOMATION_CRON_SECRET` is not set on the API |
| HTTP 401 | The GitHub secret differs from the API value |
| `feature_off` | Master switch or `MKA_REMINDERS_ENABLED` is off (real runs only; dry runs still preview) |
| `no_frontend_url` | Set `LEARNHOUSE_PLATFORM_URL` |
| `disabled_reason: invalid_test_recipient` | `MKA_AUTOMATION_TEST_RECIPIENT` is not a single plain address |
| `stopped: send_cap_reached` / `too_many_consecutive_failures` | Per-run safety stop; check the mail transport, then re-run (already-sent people are skipped) |
