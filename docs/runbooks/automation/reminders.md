# Reminders, digest, Remind button (seam C): technical notes

> Operational steps, env vars, kill switches and rollout live in the single runbook `docs/runbooks/mka-compliance-automation.md`. This file keeps only seam-specific technical detail.

Dedupe: reminder `reminder:<ISO week>:<email>` (unique in the send log, claimed before the email leaves), digest `digest:<ISO week>:<email>`; ISO weeks in the cycle timezone.

## Troubleshooting

| Report says | Meaning |
|---|---|
| HTTP 503 | `MKA_AUTOMATION_CRON_SECRET` is not set on the API |
| HTTP 401 | The GitHub secret differs from the API value |
| `feature_off` | Master switch or `MKA_REMINDERS_ENABLED` is off (real runs only; dry runs still preview) |
| `no_frontend_url` | Set `LEARNHOUSE_PLATFORM_URL` |
| `disabled_reason: invalid_test_recipient` | `MKA_AUTOMATION_TEST_RECIPIENT` is not a single plain address |
| `stopped: send_cap_reached` / `too_many_consecutive_failures` | Per-run safety stop; check the mail transport, then re-run (already-sent people are skipped) |
