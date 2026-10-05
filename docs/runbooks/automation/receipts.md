# Sign-off receipts (seam B): webhook + sweep

What it does: when an officeholder submits a cycle course's **sign-off** assignment, LearnHouse calls our webhook and the
learner gets one receipt email (plus a single "all set" email once every required sign-off exists). A daily sweep sends
any receipt the webhook missed. Nothing is sent unless the flags are on, and while `MKA_AUTOMATION_TEST_RECIPIENT` is set
every message goes only to that address.

## Environment (ilm-dev)

| Variable | Purpose |
|---|---|
| `MKA_AUTOMATION_ENABLED=true` | master switch (default off) |
| `MKA_RECEIPTS_ENABLED=true` | receipts switch (default off) |
| `MKA_AUTOMATION_WEBHOOK_SECRET` | the shared signing secret (same value as in the webhook below) |
| `MKA_AUTOMATION_CRON_SECRET` | secret for `X-MKA-Cron-Secret` on the sweep |
| `MKA_AUTOMATION_TEST_RECIPIENT` | review mode: ALL mail goes here, subject `[TEST -> <intended>]` |
| `MKA_AUTOMATION_CONTACT_EMAIL` | "who to contact" line and Reply-To (outside test mode) |

With the flags off the webhook still verifies the signature, then answers `200 {"status":"disabled"}` and records nothing.

## Create the webhook in LearnHouse

1. Sign in as an org admin: `/dash/developers/automations` -> add endpoint.
2. URL: `https://ilm-dev.mkausa.org/api/v1/mka/automation/webhooks/learnhouse`
3. Events: `assignment_submitted` and `course_completed` (nothing else is needed).
4. The signing secret (`whsec_...`) is shown ONCE. Put exactly that value in `MKA_AUTOMATION_WEBHOOK_SECRET` on the API.
5. Use the endpoint's test/ping action: a ping is not a handled event, so you should see `200` and an `ignored` row
   (or `401` if the secret does not match, `400` for a stale body).

Behaviour to know: LearnHouse retries 3 times (10 s timeout) with the same `delivery_id`/timestamp, then drops the event.
The receiver rejects bodies whose `timestamp` is older than 10 minutes (or more than 60 s in the future) and dedupes on
`delivery_id`. The recipient is always the account email looked up from `user_uuid`; payload email and names are never read.

## Test with a signed curl (local secret)

```bash
SECRET=local-secret            # same value as MKA_AUTOMATION_WEBHOOK_SECRET in the local API
BODY=$(printf '{"event":"assignment_submitted","delivery_id":"dlv_%s","timestamp":"%s","org_id":1,"data":{"user":{"user_uuid":"user_..."},"assignment":{"assignment_uuid":"assignment_..."},"course":{"course_uuid":"course_...","name":"x"},"attempt_number":1}}' \
  "$(openssl rand -hex 8)" "$(date -u +%Y-%m-%dT%H:%M:%SZ)")
SIG="sha256=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$SECRET" | awk '{print $NF}')"
curl -i -X POST http://localhost:1338/api/v1/mka/automation/webhooks/learnhouse \
  -H "Content-Type: application/json" -H "X-Webhook-Signature: $SIG" --data-binary "$BODY"
```

Sign the exact bytes you send (`--data-binary`, no re-formatting). Expected: `200 {"status":"processed"}` for a real
sign-off by a roster member; `{"status":"duplicate"}` if you re-send the same `delivery_id`; `401` with an empty body for
a wrong secret. Keep `MKA_AUTOMATION_TEST_RECIPIENT` set while testing; mail is mocked/captured, never sent to officeholders.

## Sweep (covers dropped events)

`POST /api/v1/mka/automation/receipts/sweep?dry_run=true&days=7` with header `X-MKA-Cron-Secret: <MKA_AUTOMATION_CRON_SECRET>`.

- `dry_run` defaults to **true**: it only counts what would be sent. Real sends need `dry_run=false` AND the flags on.
- `days` (1-60, default 7) is the look-back window on sign-off submissions.
- Uses the same dedupe keys as the webhook (`receipt:{assignment_uuid}:{user_id}`, `allset:{cycle_id}:{user_id}`), so a
  receipt is never sent twice; a previously `failed` send is retried.
- Per-run cap `MKA_AUTOMATION_RUN_SEND_CAP` (default 400), pause `MKA_AUTOMATION_SEND_DELAY_SECONDS`, hard stop after
  `MKA_AUTOMATION_MAX_CONSECUTIVE_FAILURES` failures. Re-run to continue after a cap.
- Optional `org_id` limits the run to one org. The response holds counts only, no addresses.

## Rollback

Set `MKA_RECEIPTS_ENABLED=false` (or the master switch): the webhook returns `disabled` and the real sweep refuses.
