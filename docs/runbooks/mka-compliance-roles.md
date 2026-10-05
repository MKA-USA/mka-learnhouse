# MKA compliance dashboard: giving people access

Audience: an organization **admin** (role Admin). Steps in the LearnHouse admin UI; there is no API shortcut
(the `/roles` router requires a user session, API tokens are rejected, so this is manual for roughly 22 people).
Items marked UNVERIFIED were not exercised against a running instance; UI labels come from the code, not screenshots.

## Why a role is needed
Everything under `/dash` is blocked by `AdminAuthorization` unless the user's role carries `dashboard.action_access`
(seeded: Admin, Maintainer, Instructor). A Mohtamim or national viewer who is only a "User" gets a 403 on every
dashboard page, including Compliance. The compliance API itself does not look at `dashboard.action_access`; it
decides scope server-side (below).

## A. Give Mohtamims / national viewers dashboard access
1. Settings, Users, **Roles** tab (component `OrgRoles`; UNVERIFIED label). Create a role "Mohtamim" (or reuse Instructor).
2. Rights for a view-only person: `dashboard: access` ON; everything else OFF (or read-only). Do NOT grant
   `organizations: update`; that role right makes the holder scope **all** (see matrix).
   Instructor also exposes course creation and the Users list; a custom role is the tighter choice.
3. Users tab: open the person, assign the role. Org membership is required first (they must have signed in or been added).
4. UNVERIFIED: whether a custom role needs a paid plan in the deployed mode (the Roles tab shows a plan badge in SaaS).

## B. Make someone a course author (sees only their courses)
1. Open the cycle course in the dashboard, **Contributors** tab (`EditCourseContributors`), add the user as a contributor
   and make sure the status is **ACTIVE** (PENDING / INACTIVE and REPORTER do not count).
2. The person also needs dashboard access (section A) to reach the page.
3. Provisioning note: the pilot provisioner should set CREATOR/CONTRIBUTOR ACTIVE rows itself; verify for imported courses.

## C. Who sees what (server-enforced)
| Viewer | Scope | Sees |
|---|---|---|
| Superadmin, org Admin or Maintainer, org API token | all | every cycle course, overview, learners, CSV |
| Role with `organizations: update` | all | same |
| National-level holder: attributes `level=national` AND (`department=aitmad` OR role `sadr` / `motamid`) | all | same. **UNCONFIRMED rule** (config `SCOPE_ALL_ATTRIBUTE_RULES` in `services/mka/compliance_scope.py`); pinned to national on purpose so a Majlis Sadr never sees all regions; fails closed when attributes are stale/unmatched |
| ACTIVE CREATOR / MAINTAINER / CONTRIBUTOR of a cycle course | own | only those courses (summary, learners, CSV, trend); overview is 403 |
| Everyone else (plain user, INACTIVE/PENDING author, REPORTER, other org) | none | `/scope` says `none` (no nav item); every other endpoint 403; a course outside scope is 404 |

## D. Verify
Sign in as the person (or ask them): the left menu shows **Compliance** only when scope is not `none`.
Check `GET /api/v1/mka/compliance/scope?org_id=<id>` returns the expected `scope`.
