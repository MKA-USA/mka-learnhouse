# MKA Compliance Automation — Design / Build Contract

- **Date:** 2026-10-05 · **Status:** approved by the product owner in conversation ("automation design looks good"; defaults accepted)
- **Parents:** `2026-10-04-mka-compliance-system-design.md` (umbrella), `2026-10-04-mka-native-compliance-analytics-design.md` (compliance API, scope rules), `…conditional-visibility…` Feature A (attributes). Integration facts (cited from code): `/Users/mamjed/Documents/mka-thinkific-migration/analysis/AUTOMATION_INTEGRATION_MAP.md` — **read it fully; every upstream symbol below is cited there.**
- **Fork policy:** all logic in fork-only files (`apps/api/src/services/mka/automation*.py`, `routers/mka_automation.py`, `db/mka_automation.py`, migration `mka_2026100x_automation.py`); the ONLY required upstream hook is `apps/api/src/router.py` (import + `include_router`, one-line style, logged in `.codebase-memory/upstream-modifications.md`). The login hook (`mka_refresh_on_login`, already a fork-owned function) gets one call added inside fork code. Optional second hook (`core/events/events.py startup_app`) is **NOT used** — scheduling is external.
- **Environment:** staging (ilm-dev) only. **Production untouched.**

## 0. Job to be done
> **When** ~1,400 officeholders are appointed on Nov 1, **I want** them enrolled automatically on first sign-in, handed an acknowledgement record when they sign off, and nudged until they finish, **so** Mohtamims spend their time on the people who need help, not on emailing everyone.

## 1. Safety envelope (non-negotiable — real officeholders' mailboxes are in the roster)
1. **Master kill switch** `MKA_AUTOMATION_ENABLED` (default **false**) plus per-feature flags `MKA_AUTOENROLL_ENABLED`, `MKA_RECEIPTS_ENABLED`, `MKA_REMINDERS_ENABLED` (default false). Everything is a no-op when off.
2. **Test recipient redirect** `MKA_AUTOMATION_TEST_RECIPIENT`: when set, EVERY outgoing email goes only to that address, subject prefixed `[TEST → <intended recipient>]`, `test_mode=true` in the send log. Staging runs with this set until the product owner removes it. A run in test mode must never email anyone else (test it).
3. **Dry-run by default** on every run/endpoint that sends; real send requires explicit `dry_run=false`.
4. **Send log with claim-before-send**: a unique `dedupe_key` row is inserted (status `queued`) BEFORE the email is sent; a conflict means "already handled" (idempotent under retries, replays, concurrent runs).
5. **Caps**: ≤1 reminder per person per ISO week; ≤1 manual "remind my department" per course per 24 h; per-run send cap (default 400) with a small delay between sends; hard stop on N consecutive send failures.
6. Everything org-scoped (`org_id` on every table and query); fail closed; no secrets/PII in logs.

## 2. Components

### A. Auto-enrol on first sign-in (no webhook — in-process, in the existing login hook)
- `services/mka/automation_enroll.py::autoenroll_user(db_factory, user)`; called from `mka_refresh_on_login` AFTER the attribute refresh, only when `MKA_AUTOMATION_ENABLED && MKA_AUTOENROLL_ENABLED`, Google sign-in, and the account's address is **proven** (`attributes.is_address_proven`) — never enrol on an unproven identity.
- Match the user to expected-roster rows (`mka_compliance_expected`) by `lower(email)` for the active cycle (default-cycle logic from the compliance service); enrol into the cycle's **General** course and the **department course for each of the person's roles** (a person may hold several; dedupe courses; roles with no department course, e.g. national Muqami → General only).
- Enrol = ensure the learner's `Trail` and a `TrailRun` for the course (see map §2: `INSERT … ON CONFLICT DO NOTHING` in a NEW session; advisory lock around the `Trail` get-or-create since `Trail` has no unique constraint). **Skip courses that are not published** (enrolment does not grant access to a draft and would show as enrolled-but-unopenable); record a `skipped_unpublished` event so a later `reconcile` or the next login picks it up. `org_id` may be None at login — derive it from the roster/cycle.
- **Never raises into the login path** (own session, broad try/except, fail-open for login, fail-closed for enrolment); fast path = one indexed query; target < 25 ms added to login when there is no match.
- Safety net: the provisioner's `reconcile` command keeps working for bulk catch-up.

### B. Attestation receipts via LearnHouse webhooks
- Endpoint `POST /api/v1/mka/automation/webhooks/learnhouse` (router mounted with NO session dependency; auth is the signature). Verify `X-Webhook-Signature: sha256=<HMAC-SHA256(secret, RAW body)>` with **`MKA_AUTOMATION_WEBHOOK_SECRET`** (dedicated env secret, not the Fernet-decrypted per-endpoint secret), constant-time compare on the raw bytes (read the body before JSON parsing). Reject bad/missing signature with 401 and no body detail. Replay protection: the signed body contains `timestamp` and `delivery_id` — reject timestamps older than 10 minutes, and dedupe on `delivery_id` (unique insert into `mka_automation_event`; a duplicate returns 200 without side effects).
- Handle `assignment_submitted` for assignments that are a cycle course's **sign-off** or **contact-check** assignment (ids in `mka_compliance_cycle_course`), and `course_completed` for cycle courses. **Do not trust payload email**: resolve the user from `user_uuid`/id in the DB and send to the ACCOUNT's email. Payload carries no answers; never store answers.
- Receipt email (to the learner only): "We've recorded your sign-off for `<course>` on `<date/time in cycle tz>`", what is left (e.g. "you still need the Department course" / "you're all set for 2026-27"), link to the course, who to contact. Dedupe key `receipt:{assignment_uuid}:{user_id}`; a final "all set" message when both required sign-offs exist (`attested_requires=both`), key `allset:{cycle_id}:{user_id}`.
- Webhook delivery is best-effort (3 attempts, then dropped): add `POST /api/v1/mka/automation/receipts/sweep` (cron-secret protected, see C) that finds sign-off submissions in the last N days without a receipt send-log row and sends them (idempotent via the same dedupe keys).
- Respond fast (LearnHouse timeout is 10 s): record the event, process, return 200; heavy work in a background task if needed.

### C. Reminders, digests and the "Remind my department" button
- Endpoint `POST /api/v1/mka/automation/reminders/run` — auth header `X-MKA-Cron-Secret` == `MKA_AUTOMATION_CRON_SECRET` (constant-time; dedicated secret, **not** an org API token); params `dry_run` (default true), `kind=reminder|digest|all`. The external scheduler calls it daily; the endpoint decides whether today is a reminder day from config `MKA_REMINDER_SCHEDULE` (default for 2026-27: Nov 8, Nov 15, Nov 22, final Nov 28; after the cycle deadline weekly while overdue) in the cycle timezone (`MKA_COMPLIANCE_TZ`).
- Recipients = people whose status in the active cycle is not_signed_in / not_started / in_progress / overdue for a required course (reuse the compliance service aggregates; **dedupe by email**; one email per person per week listing what is outstanding; role-mailbox accounts are addressed by role title and Majlis, e.g. "Nazim Tabligh, Albany"). Exclude `attested`. Skip departments excluded by config (Atfal).
- **Weekly digest** (Mondays) to Mohtamim / regional Qaid role mailboxes: counts + the list of who in THEIR scope still needs a nudge (scope rules from `compliance_scope.py`; role mailboxes/titles only, no extra PII).
- **Manual button** `POST /api/v1/mka/compliance/courses/{course_uuid}/remind?dry_run=` (session auth; course must be in the viewer's compliance scope — out of scope → 404; respects the weekly per-person cap; ≤1/24 h per course; returns counts). Web: wire the existing feature-flagged placeholder (`NEXT_PUBLIC_MKA_COMPLIANCE_REMIND`) in `apps/web/components/mka/compliance/` to a confirm dialog that first shows a **dry-run preview** ("12 people will be reminded, 5 skipped: reminded this week"), then sends; toast result; 403/404/429 handled.
- Scheduler: fork-owned workflow `.github/workflows/mka-automation-cron.yaml` — `schedule` (daily ~14:00 UTC) + `workflow_dispatch` (input `dry_run` default **true**, `kind`); calls the staging URL with repository secret `MKA_AUTOMATION_CRON_SECRET`; environment `development`. (`schedule` only fires from the default branch `dev` — OK.) Also calls `receipts/sweep` daily.
- Email wording: short, conversational, plain; role-appropriate greeting; one link; who to contact (`MKA_AUTOMATION_CONTACT_EMAIL`); never include other people's names; Islamic-content rules apply to any quoted text (none planned). Templates in one fork file, fully unit-tested (golden snapshots), and a **"send me a test"** admin path (`dry_run` + `MKA_AUTOMATION_TEST_RECIPIENT`) the product owner uses to review real emails before anything goes to officeholders.
- Email transport: upstream `send_email(to, subject, body, headers, sender_name)` (sync/blocking → wrap in `asyncio.to_thread`); footer/unsubscribe helpers in `services/users/emails.py` (compliance reminders are an organisational duty — keep the standard footer but no marketing unsubscribe semantics; follow the map).

## 3. Data model (fork-only, org-scoped, idempotent migration + create_all guard)
- `mka_automation_event(id, org_id, delivery_id, event, user_id NULL, user_uuid NULL, course_uuid NULL, assignment_uuid NULL, status 'received|processed|ignored|skipped_unpublished|error', note NULL, received_at)` UNIQUE(org_id, delivery_id) where delivery_id not null; internal events (autoenroll) use a generated id. **No answers, no payload bodies.**
- `mka_automation_send_log(id, org_id, kind 'receipt|allset|reminder|digest', dedupe_key, user_id NULL, to_email, intended_email, subject, status 'queued|sent|failed|suppressed', test_mode bool, cycle_id NULL, course_id NULL, error NULL, created_at, sent_at NULL)` UNIQUE(org_id, kind, dedupe_key).
- Indexes for the sweep and weekly-cap queries. Retention: a purge command for rows older than 18 months.

## 4. GDPR and data hygiene
Extend the fork's existing hooks (`mka_profile.profile_status(include_attributes=True)` for export, `delete_profile` for anonymise; **delete before `delete_attributes`**): export and scrub the user's event/send-log rows (by `user_id` and stored email). **Fix the existing gap: `MkaComplianceExpected` rows (email, names) are not scrubbed on anonymise** — do it, with tests. Rows keyed only by email get the retention purge.

## 5. Security requirements (pre-empt the reviewers)
Raw-body HMAC with constant-time compare; no JSON parse before verification; replay/dup protection; cron endpoint secret not logged and not an org token; test-mode redirect enforced centrally in ONE send function (no code path emails around it); org scoping everywhere; no learner-reachable route that sends or reveals recipients; manual-remind scope-checked server-side; per-run caps; CSV/HTML escaping in emails (role titles come from data); no PII in logs; fail-open for login, fail-closed for sends; tests for each. Past review lessons (shared response builders, org-less tables, stale/unproven identity, token rights, TOCTOU, partial payload validation) apply.

## 6. Milestones (seams; ≤3 executors concurrently)
| Seam | Owns | Depends on |
|---|---|---|
| **S1 foundation** | models + migration, flags/config, central `send_automation_email()` (test-mode redirect, claim-before-send, caps), email templates skeleton + golden tests, GDPR export/delete + the `MkaComplianceExpected` scrub, router skeleton + the `router.py` hook, runbook skeleton | — |
| **A auto-enrol** | `automation_enroll.py`, login-hook call, tests (incl. unpublished skip, multi-role, proof gating, fail-open, perf) | S1 |
| **B receipts** | webhook endpoint, signature/replay, event table logic, receipt/all-set emails, `receipts/sweep` | S1 |
| **C reminders** | reminders/run + digest + manual endpoint, schedule logic, templates, web Remind dialog, GitHub workflow | S1 |
Then: integration worktree, contract tests, e2e on a local stack (webhook signed with a local secret, test-mode email capture), independent Opus security review + re-review, runbook `docs/runbooks/mka-compliance-automation.md` (env vars, GitHub secret, how to create the webhook in `/dash/developers/automations`, test-send procedure, how to turn on for real, rollback/kill switch).

## 7. Manual steps for the product owner (documented, not coded)
1. On ilm-dev set env vars: `MKA_AUTOMATION_WEBHOOK_SECRET`, `MKA_AUTOMATION_CRON_SECRET`, `MKA_AUTOMATION_TEST_RECIPIENT` (own address), flags off until tested, `MKA_AUTOMATION_CONTACT_EMAIL`. 2. Add GitHub repo secret `MKA_AUTOMATION_CRON_SECRET`. 3. In `/dash/developers/automations` create the webhook: URL `https://ilm-dev.mkausa.org/api/v1/mka/automation/webhooks/learnhouse`, the same secret, events `assignment_submitted` + `course_completed`. 4. Review test emails; then remove the test recipient and enable flags (with the product owner present).

## 8. Out of scope here
The audience/conditional-visibility block (another session); a UI to configure the automation (**later phase: evaluate a lightweight open-source rules/workflow builder to view and configure it from the admin dashboard**); mid-year appointee flows; SMS or other channels; production.
