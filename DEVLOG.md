# DEVLOG — MKA Learnhouse

MKA USA's learning platform, a fork of the open-source LearnHouse (Next.js web, FastAPI API, Postgres), deployed with Coolify (staging `ilm-dev.mkausa.org`).
Stack: Next.js + Turbopack, Bun, FastAPI/SQLModel, Postgres, GitHub Actions, Coolify.
Started: 2026-10 (fork customisation)

## 2026-10-06 — Overnight consolidation: dev fully merged, prod release PR prepared

**Goal:** The user went to sleep with eight parallel Claude sessions open and asked one session to pull every branch of work into a single thread, finish the remaining items, and deploy the final state.

**Did:**
- Polled all eight sessions. Two answered (Audience block, Quran citation checker); six were stuck on prompts waiting for the user, so their state was reconstructed from git and GitHub instead.
- Merged the three remaining dev PRs: #22 (compliance hook-guard test fix), #19 (backend Turnstile enforcement + signup rate limiter, after an independent Opus review returned MERGE with pytest green), and #23 (follow-ups to #19: `Retry-After` passthrough, fork-log correction, local-dev note). Final `dev` HEAD `4bbd5cbf`.
- Verified at the content level that all 34 sibling worktrees hold nothing unmerged. Every pushed branch maps to a merged PR (#1–#23); the only dirty files are e2e screenshots, a lockfile and untracked symlinks.
- Opened draft release PR #24 (dev → prod, 34 commits) with a readiness checklist. Not merged.
- Recovered ilm-dev after the final deploy left the stack down, then smoke-tested: direct API signup without a Turnstile token → 403, signup route with a bad token → 403 (not 502), fork routes → 401 unauthenticated.

**Decisions (why):**
- Did NOT promote prod. Project rules require an explicit OK and a fresh DB backup, and the prod Coolify service has empty Google OAuth credentials while dev now forces Google sign-in for `mkausa.org` accounts. Merging #24 as-is would lock members out. The checklist leads with that.
- Merged #19 and #22 without the owning sessions' sign-off because the user's instruction covered it, the owners were unreachable, #19 had been untouched for four hours, and the fresh-context review found no blockers. The non-blocking review notes became #23 instead of being dropped.
- Did NOT remove leftover worktrees or stop the local e2e stack: the blocked sessions may have their working directory in them, and deleting under a live session is destructive. Listed them for the user.
- Left PR #15 (Quran citation checker) with its owner: its session is holding uncommitted follow-ups pending the user's own confirmation, and the tool is not wired into any deploy.

**Challenges:**
- Three merges in four minutes triggered three Coolify restarts. The second workflow run was cancelled by the concurrency group as designed, but the stack was taken down at 03:52Z and never came back; the final run timed out after 30 minutes. VPS disk, RAM and CPU were fine. A manual restart via the Coolify API brought it back healthy in 3.5 minutes. Lesson: batch merges, or leave several minutes between them, so restarts never overlap.
- The Coolify API exposes no build log for compose services, and Hostinger's Docker Manager is unsupported on this image, so the root cause of the failed restart could not be read. Watch for it on the next deploy.
- A shell sweep for unmerged content silently returned zero for every worktree; a Python rewrite exposed the quoting bug. Cross-session messages cannot wake a session that is blocked on a permission prompt.

**Morning follow-through (2026-10-06, user awake):** user chose to promote prod with the same env as dev. Copied Google OAuth, SMTP, Fireworks AI, Jev and the Audience flag to the prod Coolify service with prod-specific `LEARNHOUSE_FRONTEND_DOMAIN`/`MEDIA_URL`; merged #24 with a merge commit (`7e18ea2d`, prod tree identical to dev) and dispatched the prod deploy by hand. Prod is healthy; smoke matches dev (direct API signup 403, signup route 403, fork routes 401, Google on the login page). The user accepted merging without a DB backup because the Coolify API has no backup endpoint for compose-service databases and the 4 migrations are additive and idempotent.

**Status / Next:** dev and prod are both at the same tree, deployed and healthy. For the user: answer or close the six blocked sessions, then prune worktrees; confirm PR #15 in its session; complete the #24 checklist (prod DB backup, Google OAuth + SMTP creds on prod, optional AI/Jev/audience pass-throughs) and merge when ready. Open from earlier: upstream #1111/#1112, Gemini-embedded course re-index, Coolify token rotation, compliance automation manual setup.

## 2026-10-05 — Majlis/Region profile fields, admin editor, signup Turnstile (work done 2026-10-04)

**Goal:** Capture Majlis (required, 52 options) with a server-derived Region (11 regions), plus optional US mobile, AMC ID (unique) and Tanzeem, for every new user including Google sign-ins, so MKA can report by Majlis and Region. Later asks: admins must be able to set and change AMC IDs, and signup needed bot protection.

**Did:**
- Fork-only side table `mka_user_profile`, a validation/mapping module, and a `/mka/profile` router with self and admin endpoints. Signup (email, invite, org-less) requires a Majlis, checked before the user row is created.
- A non-dismissible "Complete your profile" gate for Google and existing users, built from LearnHouse's own shadcn/Radix primitives and theme tokens, with a Majlis combobox from the official shadcn `command` component.
- AMC ID is admin-managed once stored. An admin "Edit profile" dialog opens from the Users table, and GDPR anonymize and export now cover the profile.
- Turnstile now runs on signup when its keys are set, without SaaS mode. Created the Cloudflare widget and set the keys on the dev Coolify service.
- Merged to `dev` as PR #3 (feature) and PR #4 (idempotent migration), deployed, and smoke-tested the live dev site.

**Decisions (why):**
- Side table instead of columns on `User`: no upstream model or table is touched, so upstream pulls stay clean. The cost is one join in reports.
- Region is derived from Majlis on the server and never accepted from the browser. The 52-to-11 mapping lives in one fork-only file shared by validation and the options endpoint.
- No custom UI primitive. I used the official shadcn Combobox pattern (Popover + `command`). Rejected the Base UI combobox (extra dependency) and coss ui (AGPL core, a licence risk for a fork).
- Did NOT turn on LearnHouse's SaaS mode to get the existing Turnstile. It would have put the org on free-plan limits, required email verification and hidden Google SSO. Instead the fork rule gates on the keys, and SaaS behaviour stays exactly upstream. The server enforces only when both keys are set, so a half-configured setup can't lock out signups.
- AMC ID: members can enter it at signup, then only admins can change it (Salesforce will supply official details later). This also limits squatting.
- Admin profile edits are admin-role only (not maintainers), enforce the org MFA/session policy like peer routes, and require admin of every org the target belongs to. An independent audit found the first two gaps.
- The gate and dialogs copy ui/dialog's inline style rather than editing it, because it hardcodes a white surface. The coupling is commented.
- Process: subagent-driven, one implementer per task, a spec-and-quality review after each, a whole-branch review on Opus. Squash-merged to match the repo's convention.

**Challenges:**
- The plan said the profile is written in the same transaction as the user. The real code commits twice, and a post-commit AMC race expired the user object (MissingGreenlet). Fixed by validating before creation, writing right after, and refreshing in the swallow branch.
- Existing code that creates users without a Majlis would now 422: the e2e client and 14 tests. Found by review and a repo sweep.
- The dialog's Tanzeem select opened behind the gate (z-index 220 vs 240), and ui/dialog hid its own close button only via a selector.
- The shared venv lacked `greenlet`, so async tests only ran with a scratch workaround. A safety hook also blocked git in shared worktrees, so work moved to a fresh worktree.
- The API creates tables at startup with `create_all`; nothing runs Alembic. My migration would have failed on an existing table, so it was made idempotent in PR #4.
- CI's API test job fails only at the Codecov upload (no token). Dev-deploy web tests show pre-existing billing failures. Both predate this work.

**Status / Next:** Merged and deployed to dev, healthy, Turnstile enforced (403 without a token). Prod untouched: it needs the two Turnstile env vars on the prod Coolify service and a dev-to-prod merge, after a fresh DB backup. Browser checks are still pending on dev (gate, admin dialog, Turnstile widget, dark mode, dropdown layering, saving a profile, the partial index on Postgres). Next sub-project: reporting (CSV columns, Region/Majlis analytics). Open gaps: direct API signup bypasses Turnstile, Google SSO is not challenged, the unused signup rate limiter could be switched on, and the docs example for `POST /users/{org}` needs `mka_profile`.

## 2026-10-05 — Fireworks AI provider + embeddings, upstream PRs, dev Coolify AI env

**Goal:** Review the Fireworks integration, contribute it back to upstream LearnHouse, and get AI working on the dev Coolify service with Fireworks only (no Gemini key).

**Did:**
- Reviewed the chat provider commit: it matched the DeepSeek/Moonshot pattern, 27 provider tests passed, and the pinned pydantic-ai 2.44.0 has `FireworksProvider`. The gap was every list that names providers (config.yaml, config.py, embeddings docstring, self-hosting docs, logo).
- Squashed the chat provider into one commit and opened upstream PR #1111.
- Built an explicit-opt-in Fireworks embeddings path (`qwen3-embedding-8b`, `dimensions=768`) with a vector length check, 9 tests and a re-index warning. Merged to the fork's dev (#1) and opened upstream draft #1112, stacked on #1111. Landed the missing logo and env-var row as #2.
- Dev Coolify: set AI enable/provider/key/3 model IDs/embedding provider+model, plus `LEARNHOUSE_SSL`, `LEARNHOUSE_FRONTEND_DOMAIN` and `LEARNHOUSE_MEDIA_URL`, and patched the compose so each reaches the container. Several restarts, health verified.

**Decisions (why):**
- Fireworks embeddings are used only when `LEARNHOUSE_AI_EMBEDDING_PROVIDER=fireworks` is set explicitly, so Fireworks-for-chat users keep the Gemini fallback. Rejected: gating on the main provider (silently changes embedding provider).
- Skipped per-vector model tagging, bulk re-index and a vector index: schema change needs its own design. Mixed-model vectors give silent bad retrieval, so the docs warn to re-index.
- Kept 768 dims via the `dimensions` param (default is 4096) rather than migrating the pgvector column. Verified live before building.
- Used the Coolify API (token in keychain) over a UI walkthrough, after flagging the token travels over plain HTTP on :8000. Rejected: guessing a TLS host.
- Merged fork PR #1 despite a red check once I verified it was only the Codecov upload (missing token), pytest passed (5870), and the deploy gate already treats the full suite as non-blocking.
- Ignored Perplexity's model/embedding recommendations until verified; its FAST model ID was wrong in one version.

**Challenges:**
- The Fireworks vars existed in Coolify but the compose never passed them to the container, so they were invisible. Fixed by patching `docker_compose_raw`.
- A worktree-guard hook blocks git in the shared checkout; used new worktrees and `gh`. A second Claude session shared Coolify and dev; coordinated by message and held pushes.
- `6a1a9529` was never pushed, so the squash dropped the logo and an env-var row; found by diffing, fixed in #2.
- Coolify showed `exited` for ~5 minutes after a compose change while health was 200.
- Executors sometimes skipped the required MCPs and used plain grep; I re-checked their claims.

**Status / Next:** Dev is running:healthy with Fireworks chat + embeddings; not tested end to end by a user. Open: #1111 review, then mark #1112 ready; re-index Gemini-embedded courses; decide on the CSRF `LEARNHOUSE_ALLOWED_REGEXP`; rotate the Coolify token; prod still lacks the AI pass-throughs; another session's Jev work is pending its own push; local `dev` still carries redundant `6a1a9529`.

## 2026-10-05 — Officeholder compliance program: build complete, staged rollout pending

**Goal:** Replace the Thinkific annual officeholder training with LearnHouse courses that every national, regional, and local officeholder completes within the first month of the MKA year (Nov 1 to Dec 1). Each Mohtamim (department head) needs to see completion by Majlis, region, and department.

**Did:**
- Native compliance analytics: an org Compliance page and a per-course tab, backed by a fork-only API at `/mka/compliance/*` (#5).
- Hidden identity attributes, derived from Google SSO role-mailbox syntax (`{role}.{majlis}@`, `qaid.{region}@`, `muqami@`, `newyorkmetro.region@`), now at rules 2026.3 (#5, #9, #11).
- `custom/compliance` provisioner: it clones a new course set for each cycle and handles roster, cycle, authors, reconcile, and publish. Everything is a dry-run unless `--apply` is passed. Lookups are paced to stay under the 60/min API limit. Atfal is excluded by one config switch (#6–#8, #10, #12).
- Audience block: lesson sections that show only to certain roles, plus "Preview as" and "My counterparts" (#13).
- Automation: auto-enrol on first sign-in, attestation receipts through signed LearnHouse webhooks, and scheduled reminders, a digest, and a "Remind my department" button. All of it ships off by default, with dry-run mode, a kill switch, a send log, quarantine, and a test-recipient redirect (#14).
- Staging rollout: cycle 2026-27 is set up with 3 pilot draft courses and a 126-row pilot roster.

**Decisions (why):**
- I chose a thin compliance layer over LearnHouse instead of a separate app. It reuses LearnHouse's courses, assignments for sign-off, and webhooks. New logic stays in fork-only files, and upstream files only get one-line tagged hooks, so upstream releases can still be pulled.
- Each cycle gets a new cloned course set instead of a progress reset, because role mailboxes pass to the next officeholder every Nov 1.
- We built our own automation on LearnHouse's webhooks instead of using n8n or Make (the user's call). It stays inert until it is switched on in stages and the test emails have been reviewed by a person.
- "Attested" means signing off on both the General course and the department course.

**Challenges:**
- Every one of the 11 independent review rounds found real defects. Examples: a manual reminder could cost someone that window's scheduled reminder, and a partial send failure could end green in CI.
- A brief typo of mine created a bogus `newyorkmetro-region` slug, which was later corrected.
- `gh` defaults to the upstream repo. A safety hook blocks git in shared worktrees, so I switched to fresh worktrees for each change.

**Status / Next:** Everything is merged and deployed to staging but inactive. Production has not been touched. Next steps:
- Staged enabling of the automation (secrets, then the webhook, then receipts, then reminders in dry-run).
- Load the 2026-27 department plans when they arrive, plus the Huzoor message link.
- Set up roles for the Mohtamims.
- A human spot-check of the pilot content.
- Publishing the General course first, ahead of Nov 1.
