# LearnHouse staging probe report

Target: https://ilm-dev.mkausa.org/api/v1 (read-only GET requests only). Generated: 2026-10-05T02:22:33.642Z
Org slug accepted: default | org_id: 1


No token values, user identities or response bodies are recorded; counts only.

| Endpoint | HTTP | Result | Note |
|---|---|---|---|
| `GET /courses/org_slug/{org_slug}/count` | 200 | OK | count=2 |
| `GET /courses/org_slug/{org}/page/1/limit/5?include_unpublished=true` | 200 | OK | 2 item(s) |
| `GET /courses/{course_uuid}/meta` | 200 | OK | object |
| `GET /chapters/course/{course_uuid}/meta` | 500 | error |  |
| `GET /assignments/course/{course_uuid}` | 200 | OK | 0 item(s) |
| `GET /assignments/{assignment_uuid}/submissions` | - | unknown | no assignment to sample |
| `GET /certifications/course/{course_uuid}` | 200 | OK | 0 item(s) |
| `GET /admin/{org}/courses/{course_uuid}/analytics` | 200 | OK | object |
| `GET /admin/{org}/courses/{course_uuid}/enrollments` | 200 | OK | 1 item(s) |
| `GET /admin/{org}/progress/{user_id}` | 200 | OK | 1 item(s) |
| `GET /admin/{org}/progress/{user_id}/{course_uuid}` | 200 | OK | object |
| `GET /admin/{org}/enrollments/{user_id}` | 200 | OK | object |
| `GET /admin/{org}/trails/{user_id}` | 200 | OK | object |
| `GET /admin/{org}/certifications/{user_id}` | 200 | OK | 0 item(s) |
| `GET /usergroups/org/{org_id}` | 200 | OK | 0 item(s) |
| `GET /orgs/{org_id}/users (list users)` | - | unknown | not probed: router rejects API tokens (source-verified); use by-email lookups |
| `write scopes (courses/chapters/activities/assignments create)` | - | unknown | write scopes unverified; token rights not readable with a token; no write attempted |

## Write probe (staging, test course only)

Generated: 2026-10-05T02:27:19.600Z. Created one draft course "ZZ-TEST provisioner write probe", exercised chapter/activity/assignment/tasks, read back, then deleted that course only.

| Step | HTTP | Result | Note |
|---|---|---|---|
| GET courses (find org_id) | 2xx | OK |  |
| POST /courses/ (draft) | 2xx | OK | published=false |
| POST /chapters/ | 2xx | OK |  |
| POST /activities/ (dynamic page) | 2xx | OK |  |
| PUT /activities/{uuid} (ProseMirror incl. table) | 2xx | OK |  |
| POST /activities/ (assignment) | 2xx | OK |  |
| POST /assignments/ (ungraded) | 2xx | OK |  |
| POST task QUIZ | 2xx | OK |  |
| POST task FORM (blank with empty correctAnswer) | 2xx | OK |  |
| GET /courses/{uuid}/meta (readback) | 2xx | OK | published=false |
| GET /activities/{uuid} (readback content) | 2xx | OK | content.type=doc, nodes=5 |
| GET /assignments/{uuid} (readback) | 2xx | OK |  |
| GET /assignments/{uuid}/tasks (readback) | 2xx | OK | 2 tasks |
| DELETE /courses/{uuid} (test course only) | 2xx | OK |  |
| GET courses (verify test course gone) | 2xx | OK | probe course still listed: false |
