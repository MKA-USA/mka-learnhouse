# LearnHouse API notes (for the compliance companion)

Base: `https://ilm-dev.mkausa.org/api/v1` (staging). Auth: `Authorization: Bearer lh_...` (API token).
Sources are paths under `apps/api/src/`. Status: **VERIFIED-SRC** = read in router/model source;
**VERIFIED-LIVE** = also returned 200 in the milestone-0 read-only probe (docs/probe-report.md);
**UNVERIFIED** = not confirmed. Org slug on staging is `default`, org_id 1 (live).

## Cross-cutting rules (VERIFIED-SRC, docs MCP agrees)
- Admin API (`/admin/{org_slug}/...`): token only (`_require_api_token`), token org must match slug, **Pro plan required** (`services/admin/admin.py::_resolve_org_slug`). Rights come from the token's `rights` object (`db/api_tokens.py`, `security/rbac/rbac.py::authorization_verify_api_token_permissions`).
- Token-allowed resource buckets: courses, activities, coursechapters, folders, media, certifications, usergroups, payments, search, assignments. Each action (`action_create/read/update/delete`) is checked separately; no "own" semantics.
- Routers that **reject** tokens (403): `/users/*`, `/orgs/*`, `/roles/*`, `/orgs/{id}/api-tokens`, webhooks (`router.py`). Consequences: **no org user list**, no org lookup by slug, no token self-introspection. Users are reached by `GET /admin/{org}/users/by-email/{email}` or from enrollment listings. org_id is read from `course.org_id`.
- Errors are `{"detail": "..."}`. Writes to courses are multipart; chapters/activities/assignments are JSON.
- Admin routes mint user JWTs only for non-privileged users; role grants never allow Admin/Maintainer.

## Reads
| Method + path | Auth/rights | Response | Status | Source |
|---|---|---|---|---|
| GET `/courses/org_slug/{slug}/count` | token courses.read | int | VERIFIED-LIVE | routers/courses/courses.py |
| GET `/courses/org_slug/{slug}/page/{p}/limit/{n}?include_unpublished` | courses.read | `CourseRead[]` (id, org_id, course_uuid, name, published, ...) | VERIFIED-LIVE | same |
| GET `/courses/{course_uuid}` , `/meta?with_unpublished_activities&slim` | courses.read | `CourseRead` / `FullCourseRead` (chapters+activities) | meta VERIFIED-LIVE | same |
| GET `/chapters/course/{course_uuid}/meta` | coursechapters.read | chapters tree | **HTTP 500 on staging probe** (server-side; use course `/meta` instead) | routers/courses/chapters.py |
| GET `/assignments/course/{course_uuid}` | assignments.read | list | VERIFIED-LIVE (0 items) | routers/courses/assignments.py |
| GET `/assignments/{uuid}/submissions?limit<=500&offset` | assignments.read | submissions | VERIFIED-SRC (no assignment on staging to sample) | assignments.py |
| GET `/assignments/{uuid}/tasks/{task_uuid}/submissions`, `/submissions/{user_id}`, `/submissions/{user_id}/grade` | assignments.read | per-user submissions | VERIFIED-SRC | assignments.py |
| GET `/certifications/course/{course_uuid}` | certifications.read; Pro plan | list | VERIFIED-LIVE | routers/courses/certifications.py |
| GET `/usergroups/org/{org_id}` | usergroups.read; standard plan | `UserGroupRead[]` | VERIFIED-LIVE | routers/usergroups.py |
| GET `/admin/{org}/courses/{course}/enrollments?page&limit<=100` | admin | `[{user, enrolled_at, status}]` | VERIFIED-LIVE | routers/admin.py |
| GET `/admin/{org}/courses/{course}/analytics` | admin | enrollment/completed/in_progress counts, avg %, certificates | VERIFIED-LIVE | admin.py |
| GET `/admin/{org}/progress/{user_id}` | admin | `ProgressSummaryItem[]` per course | VERIFIED-LIVE | admin.py |
| GET `/admin/{org}/progress/{user_id}/{course}` | admin | totals + `completed_activity_ids` | VERIFIED-LIVE | admin.py |
| GET `/admin/{org}/trails/{user_id}` , `/trails/{user_id}/courses/{course}` | admin | chapters/activities with `completed`, `completed_at`, `teacher_verified`, `grade` | VERIFIED-LIVE | admin.py |
| GET `/admin/{org}/enrollments/{user_id}` | admin | `TrailRead` | VERIFIED-LIVE | admin.py |
| GET `/admin/{org}/certifications/{user_id}` | admin | `CertificateItem[]` | VERIFIED-LIVE | admin.py |
| GET `/admin/{org}/users/by-email/{email}` | admin | `UserRead` | VERIFIED-SRC (not probed: needs a PII email) | admin.py |
| GET `/admin/{org}/usergroups/{uuid}/members`, `/users/{id}/groups` | admin | members | VERIFIED-SRC | admin.py |
| GET `/admin/{org}/courses/{course}/access/{user_id}` | admin | has_access/is_enrolled/... | VERIFIED-SRC | admin.py |

## Writes (VERIFIED-SRC only; NOT exercised in milestone 0; token write rights UNVERIFIED)
| Method + path | Body | Notes |
|---|---|---|
| POST `/courses/?org_id=` | multipart: `name`, `description`, `about`, `public` (required), `learnings`, `tags`, `thumbnail_type`, `extra_metadata` (JSON string), `thumbnail` | created unpublished (`published` default false) |
| PUT `/courses/{uuid}` | JSON `CourseUpdate` (`published`, `name`, ...) | `POST /courses/{uuid}/clone` also exists |
| POST `/chapters/` | JSON `{name, description?, org_id, course_id}` | returns `ChapterRead` with `id`, `chapter_uuid` |
| POST `/activities/` | JSON `{chapter_id, name, activity_type=TYPE_DYNAMIC, activity_sub_type=SUBTYPE_DYNAMIC_PAGE, content?, published?}` | `content` is the ProseMirror doc; PUT `/activities/{uuid}` to set it |
| POST `/assignments/` | JSON `{title, description, grading_type, org_id, course_id, chapter_id, activity_id, due_date?, published?, auto_grading?, ungraded?, pass_threshold_percentage?}` | needs an activity of `TYPE_ASSIGNMENT` / `SUBTYPE_ASSIGNMENT_ANY` first; `grading_type` enum values: UNVERIFIED (read `GradingTypeEnum`) |
| POST `/assignments/{uuid}/tasks` | JSON `{title, description, hint, assignment_type (QUIZ/FORM/SHORT_ANSWER/...), contents, max_grade_value=100}` | |
| PUT `/chapters/course/{course}/order` | `ChapterUpdateOrder` | ordering |
| POST `/admin/{org}/users` | `{email, username, first_name, last_name, password?, role_id=4}` | provisions SSO-style user |
| POST `/admin/{org}/enrollments/{user_id}/{course}` ; POST `/admin/{org}/enrollments/bulk` `{course_uuid, user_ids<=500}` -> `{enrolled, already_enrolled, skipped}` | | non-members are `skipped` |
| POST `/admin/{org}/usergroups` `{name, description}`; POST/DELETE `/admin/{org}/usergroups/{uuid}/members/{user_id}` | | |
| POST `/admin/{org}/progress/{user_id}/activities/{activity}/complete`, `/certifications/{user_id}/{course}/award` | | not needed by compliance flow |

## UNVERIFIED / open
- Whether the staging token holds create/update rights (no read path to token rights with a token). First write attempt (next work order, on a draft course) will tell.
- `GET /chapters/course/{uuid}/meta` 500 on staging (probe).
- Learner nudges and webhook availability (W3 scope).
- `GradingTypeEnum` values; `blockQuiz`/ProseMirror node constraints (see `.claude/skills/learnhouse-course-builder/SKILL.md`).
- Docs MCP confirms: tokens are Pro, work on resource routes, reject `/users/*` `/orgs/*` `/roles/*`; course create multipart; chapter create JSON.
