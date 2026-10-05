# Sign-off receipts (seam B): technical notes

> Operational steps, env vars, kill switches and rollout live in the single runbook `docs/runbooks/mka-compliance-automation.md`. This file keeps only seam-specific technical detail.

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

Sweep: `POST /api/v1/mka/automation/receipts/sweep?dry_run=true&days=7` with header `X-MKA-Cron-Secret`; `dry_run` defaults to true; `days` 1-60; optional `org_id`; counts only.
