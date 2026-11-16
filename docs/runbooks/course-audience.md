# Course audience runbook

Spec: `docs/superpowers/specs/2026-10-08-mka-course-audience-design.md`. API: `/api/v1/mka/courses/{course_uuid}/audience`.

## What it does
A course can carry one **Audience** and a **Mode**.
- Audience `everyone`: every signed-in member of the org (not anonymous visitors). `officeholders`: every proven office holder. `custom`: proven office holders filtered by departments, levels (local/regional/national) and roles. Values are OR within a field, AND across fields. "Departments" always means office holders of those departments.
- Mode `required`: matching people are enrolled (Trail + TrailRun) right away on save, and on later sign-in, profile save, org join, identity backfill, or when the course is published. `optin`: matching people can see and start the course; nobody is enrolled.
- Only PROVEN, non-stale identities match (same trust rule as identity sync). Unproven or stale people never match `officeholders`/`custom`.

## How access is wired
For `officeholders`/`custom` a managed usergroup `course:<course_uuid>` ("Course: <name>") holds the matching people and is linked to the course; the course is set `public=false`. For `everyone` the managed group is removed and `public=false` with no group means any org member. A course with no audience row behaves as upstream.
- **Hand-linked usergroups are never touched and still grant access (OR).** They can widen access beyond the audience. `GET .../audience` returns `manual_group_count`; the panel should warn when it is above 0.
- Majlis/Region groups are self-selected, so they are not offered as audiences.
- If someone sets `public=true` again, the next sign-in sync or backfill restores `public=false`.

## Never unenrol
If a person stops matching they lose access through the group (unless the course is `everyone`), but their trail and progress stay. Switching or deleting an audience never unenrols.

## Large enrolments
Up to 300 new enrolments run inside the PUT (`enrolled` = count). Above that they run in a background task: the PUT returns `enrolled: 0, enroll_queued: N`, and `enroll_failed` counts accounts that could not be enrolled. Enrolment commits in chunks of 200 and is idempotent; re-saving the audience finishes anything that was missed.

## Webhooks
Audience writes go straight to the tables (like identity sync). Upstream `usergroup_*` webhooks and the usergroups usage counter are NOT fired for managed course groups.

## Flags
- `MKA_COURSE_AUDIENCE_ENABLED` (API, default off): off means GET/preview still work, PUT/DELETE return 404, all hooks do nothing.
- `NEXT_PUBLIC_MKA_COURSE_AUDIENCE_ENABLED=1` (web): shows the panel on the course Access tab.
- Sign-in, profile-save and backfill hooks also need `MKA_IDENTITY_SYNC_ENABLED` and the org in `MKA_IDENTITY_SYNC_ORG_IDS`. The repo has no compose/env template for the other MKA flags; set these in Coolify.

## Rollback
Set `MKA_COURSE_AUDIENCE_ENABLED=false` (hooks stop; existing groups, links and enrolments stay). To remove one course's audience, `DELETE .../audience` (deletes the managed group, keeps enrolments, leaves `public=false`; re-open the course in the Access tab if it should be public again).
