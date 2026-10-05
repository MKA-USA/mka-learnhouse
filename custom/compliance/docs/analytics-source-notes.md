# Analytics source notes (W3, order 1)

Status labels: VERIFIED-SRC = read in `apps/api/src`; VERIFIED-LIVE = shape confirmed by a read-only GET on staging
(keys only, no values kept); UNVERIFIED = not confirmed. Staging org slug `default`.

## (a) Which admin-API fields feed which metric

| Metric | Endpoint (token, `/admin/{org}`) | Field | Status |
|---|---|---|---|
| Lessons completed / total (per learner, per course) | `GET /progress/{user_id}/{course_uuid}` or `GET /trails/{user_id}/courses/{course_uuid}` | `completed_activities`, `total_activities`, `completion_percentage`, `completed_activity_ids` | VERIFIED-LIVE |
| Same, all courses in one call | `GET /progress/{user_id}` | list of `{course_uuid, status, total_activities, completed_activities, completion_percentage, enrolled_at}` | VERIFIED-LIVE |
| Per-lesson completion timestamp | `GET /trails/{user_id}/courses/{course_uuid}` | `chapters[].activities[].completed`, `.completed_at` (= `TrailStep.update_date`, only when complete), `.teacher_verified`, `.grade` | VERIFIED-LIVE (keys), SRC (semantics) |
| Course completion state | enrollments list / trail | `status` in `STATUS_IN_PROGRESS`, `STATUS_COMPLETED`, `STATUS_PAUSED`, `STATUS_CANCELLED`; `enrolled_at` = `TrailRun.creation_date` | VERIFIED-LIVE |
| Course completion timestamp | none direct | derive as max `completed_at` of the last completed lesson (the analytics package does this) | SRC |
| Roster of enrolled learners | `GET /courses/{course_uuid}/enrollments?page&limit<=100` | `[{user{id,email,first_name,last_name,last_login_at,...}, enrolled_at, status}]` | VERIFIED-LIVE |
| Last activity | no dedicated field | use max(`completed_at`) across lessons, falling back to `user.last_login_at` from the enrollment row (present on staging) | PARTIAL |
| Assignment submission status, grade, attempt | `GET /assignments/{assignment_uuid}/submissions?limit<=500&offset` (token `assignments.read`) | `submission_status` in `PENDING, SUBMITTED, GRADED, LATE, NOT_SUBMITTED`, `grade` (int), `attempt_number`, `user_id`, `update_date`, `grade_display` (when GRADED) | SRC only; staging has 0 assignments |
| Per-task answers (FORM, QUIZ) | `GET /assignments/{uuid}/tasks/{task_uuid}/submissions` | `task_submission` JSON, `grade` | SRC only |
| Certificate awarded | `GET /certifications/{user_id}` | `[{certificate_user{created_at,...}, certification, course}]` | VERIFIED-LIVE (empty list) |
| Course aggregates | `GET /courses/{course_uuid}/analytics` | `enrollment_count, completed_count, in_progress_count, total_activities, average_completion_percentage, certificate_count` | VERIFIED-LIVE |

Findings that shape the design:
- The enrollment list is the only way to enumerate learners (no org user list for tokens). Sync = for each cycle course, page enrollments, then one `trails/{user}/courses/{course}` per enrolled user. At ~1,200 users x 22 courses this is the expensive path, so the sync reads `/progress/{user_id}` once per user (one call covers every course) and fetches the detailed trail only for the general and own-department course.
- "Attested" (final sign-off) is an assignment submission, not a lesson: use the sign-off assignment's `submission_status` in `SUBMITTED|GRADED` (ungraded FORM tasks stay SUBMITTED). `LATE` also counts as submitted-late. Assignment submissions were unsampled, so the sync adapter treats the shape as a contract and is covered only by mocked tests until a staging assignment exists.
- Contact self-check: FORM task answers (`task_submission`) compared with the roster in the analytics package; field names inside `task_submission` are UNVERIFIED (the course generator, W2, defines them; the package accepts a configurable key map).
- Timestamps are naive local-time strings written by whichever pod handled the request (`str(datetime.now())`), accurate to about a day. The package parses them leniently and never relies on sub-day precision.
- Rate: the core client already enforces 1 request/second by default; a full 1,200-learner sweep is roughly 25 minutes at that rate, so the daily job runs overnight and is resumable per learner.

## (b) Learner nudges: the truth

LearnHouse does NOT send learner-facing reminder or nudge emails. Evidence:
- `services/nudges/` (catalog, runner, eligibility, scheduler) is an **organization-admin lifecycle** system. The recipient list is `snapshot.mailable_admins` (`runner.py` line ~485: `admins = snapshot.mailable_admins`, built from org admins with a verified email in `eligibility.py`, which imports `ADMIN_ROLE_ID`). Every one of the ~35 specs (`activation.*`, `content.*`, `audience.*`, `monetization.*`, `dormancy.*`, `reactivation.*`, `milestone.*`) targets an org admin about their own organization, e.g. `audience.stalled_learners_d14` emails the **admin** that learners stalled.
- It is also off by default: the scheduler idles unless `LEARNHOUSE_NUDGES_ENABLED` is set (`scheduler.py` ~l.128, `runner.py::nudges_enabled`).
- Other email senders in `services/users/emails.py` are transactional only: account creation, password reset, invitation, org join, role changed, email verification. No "you have unfinished courses" mail anywhere (grep of `services/trail`, `services/courses` for remind/stalled/inactive found nothing).

Conclusion: the umbrella assumption (req 8, "officeholders get the normal nudges") is FALSE. Escalation per spec: do not silently build a scheduler. Options, for the coordinator: (1) P3 reminders sent by the companion via the existing chase-list (humans email via mailto/CSV, zero new infra), (2) a companion reminder job emailing learners through Resend, gated by a dry-run, (3) a fork-side learner nudge track. Recommended: ship (1) now (the CSV is already in this deliverable), decide (2) after seeing real completion data.

## (c) Webhooks in OSS mode

Available, with caveats.
- Events (`services/webhooks/events.py`): `course_completed`, `course_enrolled`, `activity_completed`, `assignment_submitted` (payload has `attempt_number`), `assignment_graded` (`user_id, assignment_uuid, course_uuid, grade`), `certificate_claimed`, `certificate_revoked`, plus user/course/usergroup events. Dispatch is real (`services/trail/trail.py` lines 322/377/530; `services/admin/admin.py`).
- Plan gate: `webhooks` is `pro`, but in OSS mode `is_feature_enabled_for_plan` allows everything except `{sso, audit_logs, payments, analytics_advanced, scorm}`, so webhooks are allowed in OSS. VERIFIED-SRC. The deployed edition on staging is UNVERIFIED (the admin API, Pro-gated, works there).
- Management routes (`/orgs/{org_id}/webhooks`) reject API tokens and need an org admin session (`require_org_admin`), so a human creates the endpoint. Targets resolving to private/loopback IPs are refused (`_validate_webhook_url`), so the companion needs a public HTTPS URL.
- Decision: polling stays the baseline (spec); webhooks are an optimisation. Not built in this order.

## (d) Not built / needs

- Admin-attributes endpoint: coded against the contract with a configurable path and fixture fallback. The umbrella brief names `GET /mka/attributes/admin/list`; the companion spec section A7 names `GET /mka/attributes/users` (org admin, paginated). Both are accepted via `ATTRIBUTES_LIST_PATH`.
- Sync write path is the companion's own Postgres only; no staging writes.
