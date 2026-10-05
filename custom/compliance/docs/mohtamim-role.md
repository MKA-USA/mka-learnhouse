# Mohtamim role: feasibility (W3, order 1, read-only research)

No role or write was created on staging. Evidence is from `apps/api/src`; anything not read is labelled UNVERIFIED.

## What the permission model can express

1. **Roles are org-wide buckets.** `db/roles.py::Rights` has buckets `courses, users, usergroups, folders, media, organizations, coursechapters, activities, assignments, roles, dashboard, communities, discussions, podcasts, boards, playgrounds`. Each is create/read/update/delete booleans; `courses`, `discussions`, `podcasts`, `boards`, `playgrounds` additionally have `action_read_own / update_own / delete_own` ("own" = the user is a resource author). VERIFIED-SRC.
2. **There is no per-course role scope.** `authorization_verify_based_on_roles` scopes only to the org (`get_element_organization_id`), never to a course. So a role cannot say "instructor of course X only". A role granting `courses.action_update` (without `_own`) would reach EVERY course in the org. VERIFIED-SRC.
3. **Course-level scoping exists through authorship.** `db/resource_authors.py::ResourceAuthor(resource_uuid, user_id, authorship in CREATOR|CONTRIBUTOR|MAINTAINER|REPORTER, status ACTIVE|PENDING|INACTIVE)`. `authorization_verify_if_user_is_author` and `ResourceAccessChecker._check_ownership_access` treat an ACTIVE CREATOR/MAINTAINER/CONTRIBUTOR as the course's author; for UPDATE/DELETE/CREATE-on-child the checker requires ownership (resource_access.py ~l.412). Combined with `courses.action_update_own` etc. this gives edit rights on exactly the courses where the user is an author. VERIFIED-SRC.
4. **Instructor visibility of learner work follows the same check.** `read_assignment_submissions` calls `check_resource_access(..., READ)` then `_is_assignment_instructor` = `authorization_verify_based_on_roles(..., "update", course_uuid)`; an instructor sees all learners' submissions, a non-instructor only their own. A course author with the Mohtamim role (`courses.update_own`) therefore sees that course's submissions and can grade them (`/assignments/{uuid}/submissions/{user_id}/grade`). VERIFIED-SRC.
5. **Learner progress overview in LearnHouse is org-admin only.** The analytics router uses `_verify_org_admin`; `/admin/{org}/...` progress/trail/enrollment endpoints are token-only. A Mohtamim cannot see per-learner trail progress through LearnHouse, only submissions on their course. VERIFIED-SRC.
6. **Plumbing.** Role CRUD (`/roles/*`) and `/orgs/*` reject API tokens, so the role itself is created by a human org admin in the dashboard (feature `roles` is `pro`, not EE-only, so allowed in OSS). Assigning a role to a user IS available to a token: `PUT /admin/{org}/users/{user_id}/role` body `{role_id}` (`routers/admin.py` ~l.1274; refuses demoting the last admin; target role must be org or global). Course contributor management (`PUT/POST .../courses/{uuid}/contributors`, `add_bulk_course_contributors`) requires `check_resource_access(UPDATE)` on the course; whether an API token passes that route (`get_current_user`, typed `PublicUser`) is UNVERIFIED, so assume a human course owner/admin adds each Mohtamim as CONTRIBUTOR/MAINTAINER.

## Answer: can a Mohtamim be scoped to instructor rights over ONE department course?

**Yes, but through two cooperating pieces, not a single role:**
- A custom org role "Mohtamim" with: `courses`: read, read_own, update_own (no create unless desired, no delete), `coursechapters`/`activities`/`assignments`: create/read/update as needed for authoring, `dashboard.action_access: true`, everything else off (no `users`, `usergroups`, `organizations`, `roles`).
  Caveat: `coursechapters`, `activities`, `assignments` are plain (non-"own") buckets, so those rights apply org-wide at the role-fallback layer; however the unified checker still demands course ownership for UPDATE/DELETE/child CREATE (item 3), so the practical blast radius is the courses the person authors. UNVERIFIED end to end: needs one live test with a throwaway user on staging (not done in this order, no writes allowed).
- An ACTIVE `ResourceAuthor` row (CONTRIBUTOR or MAINTAINER) for that user on their department course only.

This yields: edit that course, see and grade its submissions. It does NOT yield learner progress overview or cross-department data (good for scoping, but the progress view must come from the companion dashboard).

## Recommendation and fallback (umbrella spec section 6)

1. **Ship P1 on the fallback**: Mohtamim = a roster/attribute-derived scope in the companion dashboard (own department, all levels), which is already how the dashboard authorizes. LearnHouse authoring stays with Aitmad/admins for Nov 1. Zero LearnHouse risk, fully testable, independent of the UNVERIFIED items.
2. **Pilot the LearnHouse role afterwards** with one Mohtamim on staging: create the "Mohtamim" role (human admin), assign with `PUT /admin/{org}/users/{id}/role`, add as CONTRIBUTOR on one draft department course, then verify: (a) can edit own course, (b) cannot edit another, (c) can read the course's submissions, (d) cannot see other courses' submissions. Only if (b) and (d) pass, roll out; otherwise keep the fallback.
3. **Do not grant `courses.action_update` or `action_read` org-wide** to the role. Risk if a rights bucket is mis-set: edit rights across all 22 courses.
4. Role changes are not driven from the dashboard; keep the dashboard read-only toward LearnHouse.
