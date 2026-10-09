# MKA course audience and enrollment — design / build contract

Date: 2026-10-08. Status: approved by the user (decisions below). Fork-only unless stated. Base: `origin/dev`.

## 0. Job to be done

When a department head or admin publishes a course, they want to say once who it is for (everyone, office holders, or specific departments / levels / roles) and whether it is assigned (Required) or optional (Opt-in), so the right people are enrolled or can find it, without picking users by hand.

## 1. Decisions (user, 2026-10-08)

- D1 One per-course **Audience** setting, edited on the course's Access tab:
  - `everyone`: all signed-in members of the org (NOT anonymous visitors).
  - `officeholders`: every proven office holder.
  - `custom`: office holders filtered by any of departments[], levels[] (local|regional|national), roles[] (e.g. secretary/nazim/qaid values the attribute parser emits). Within a field values are OR; across fields AND (e.g. department=maal AND level=local).
- D2 **Mode** per course: `required` (matching people are enrolled automatically) or `optin` (only matching people can see and start it).
- D3 Required enrollment is **immediate**: saving the audience (or publishing a course whose audience is required) enrolls everyone who matches right away, after a preview count in the UI. New matches are enrolled on sign-in, profile save and identity backfill.
- D4 Never auto-unenroll: if someone stops matching, their trail/progress stays; access follows the audience (they lose access unless the course is `everyone`).
- D5 Members (non-office-holders) have no department. "Departments" in `custom` always means office holders of those departments.
- D6 A course with no audience row behaves exactly as upstream today (no change).

## 2. Facts the build relies on (origin/dev, 2026-10-08)

- Upstream access: `security/rbac/resource_access.py` — course read needs `published` and either `public=true`, or `public=false` with no linked usergroup (= any org member), or membership in any linked usergroup (OR) via `_check_usergroup_membership` (~l.832). Listing in `services/courses/courses.py` (~l.345) mirrors it. Self-enroll `services/trail/trail.py:add_course_to_trail` uses the same read check.
- Upstream bulk enroll: `POST /admin/{org}/enrollments/bulk` (routers/admin.py ~l.1039, user_ids, ≤500). Fork auto-enroll already creates Trail+TrailRun in `services/mka/automation_enroll.py` — reuse its enroll helper, do not call HTTP.
- Attributes: `MkaUserAttributes` (`is_officeholder, level, department, role, region, majlis`), proof via `is_address_proven`. Rule evaluator `services/mka/audience_eval.py` (rule shape `{v:1, mode, groups:[{officeholder, level[], department[], role[], region[], majlis[]}]}`, OR across groups) — REUSE it for matching; options endpoint `/mka/attributes/audience/options`, count `POST /mka/attributes/audience/count`; authz helper `audience_svc.course_author_or_admin`.
- Identity sync: `services/mka/identity_sync.py` — managed groups (`mka_managed_group`), per-user `_run`/`_sync_one` on Google login, profile save, org join, backfill `POST /mka/identity/sync`. Flags `MKA_IDENTITY_SYNC_ENABLED`, `MKA_IDENTITY_SYNC_ORG_IDS`.
- Web: course access UI `apps/web/components/Dashboard/Pages/Course/EditCourseAccess/EditCourseAccess.tsx` (~l.230, usergroup section only when not public; `LinkToUserGroup` modal). Fork UI lives in `apps/web/components/mka/**`; profile/audience pickers in `components/mka/audience/`.
- Fork policy (CLAUDE.md): new files under `services/mka/`, `routers/mka_*.py`, `db/mka_*.py`, `apps/web/components/mka/**`, `apps/web/services/mka/**`. Any upstream touch = one `# MKA fork` / `// MKA fork` tagged line + verbatim diff in `.codebase-memory/upstream-modifications.md`. Use the codebase-memory MCP (search_graph / trace_path) before changing any symbol and the learnhouse-docs MCP for upstream behaviour.

## 3. Components

### A. API (seam A)

- Table `mka_course_audience(course_id PK FK course.id ON DELETE CASCADE, org_id, audience TEXT check in (everyone, officeholders, custom), mode TEXT check in (required, optin), rule JSON (custom filter: {departments[], levels[], roles[]}), usergroup_id NULL, updated_by, updated_at)`. Migration `mka_20261008_course_audience.py`, idempotent, plus the `create_all` guard other fork tables use.
- Managed usergroup per non-`everyone` course: key `course:<course_uuid>` in `mka_managed_group`, name `Course: <course name>`, description "Managed by MKA course audience". Membership = proven office holders matching the audience (officeholders → all; custom → rule). Link it to the course (upstream usergroup-resource link, via service function, no HTTP) and set `course.public=false`. For `everyone`: unlink the managed course group if any, set `public=false` (= all org members), delete nothing else. Never touch usergroups the course admin linked by hand; never delete groups not in `mka_managed_group`.
  - Convert rule to `audience_eval` shape internally: officeholders → `{officeholder:true}`; custom → `{officeholder:true, department, level, role}`; evaluate with the existing evaluator against effective attributes; only proven, non-stale rows match.
- Enrollment for `required`: enroll every matching user (everyone → all org members) who has no trail run for the course, via the existing fork enroll helper; skip unpublished courses (enroll when published). Batch, idempotent, returns counts.
- Hooks: (1) on audience save; (2) per-user in identity sync `_run` after group sync (same flags, fail-open): recompute that user's `course:*` memberships and required enrollments for all courses with an audience row in the allowed orgs; (3) publish: if a course with a required audience becomes published — find the fork-safe hook (prefer reacting in the audience/sync path; if an upstream publish hook is unavoidable, one tagged line).
- Router `routers/mka_course_audience.py`:
  - `GET /mka/courses/{course_uuid}/audience` → `{audience, mode, rule, usergroup_id, matched_count}` or `{audience:null}`.
  - `POST /mka/courses/{course_uuid}/audience/preview` body `{audience, mode, rule}` → `{matched_count, sample:[≤10 {user_id, name, email}], would_enroll}` (no writes).
  - `PUT /mka/courses/{course_uuid}/audience` body `{audience, mode, rule}` → applies; returns `{memberships_added, memberships_removed, enrolled, matched_count}`.
  - `DELETE /mka/courses/{course_uuid}/audience` → removes row, unlinks + deletes the managed course group, leaves enrollments; course falls back to its previous upstream access (set public=false, no groups).
  - `GET /mka/courses/audience/options` → departments, levels, roles (reuse audience options source).
  - Authz: `course_author_or_admin` for the course's org; API tokens allowed with `courses.action_update` in the same org only (org boundary test).
  - Flag `MKA_COURSE_AUDIENCE_ENABLED` (default false): off → GET works, writes 404/403, hooks no-op.
- Tests (`src/tests/services/mka/test_course_audience.py`, router tests): each audience type matches the right people; custom AND/OR semantics; unproven/stale never match; required enrolls immediately and idempotently; optin never enrolls; switching audience moves group membership, never unenrolls; manual usergroups untouched; everyone = no group, public=false; unpublished not enrolled until published; flag off = zero writes; cross-org denied; login sync adds new matches.

### B. Web (seam B, against A's contract)

- `apps/web/components/mka/course-audience/CourseAudiencePanel.tsx`: on the course Access tab, above upstream controls, when `NEXT_PUBLIC_MKA_COURSE_AUDIENCE_ENABLED=1` (runtime config like `services/mka/flags.ts`).
  - Radio group (shadcn RadioGroup, as MkaProfileFields uses): Everyone / Office holders / Specific departments, levels or roles. Custom shows multi-selects for departments, levels, roles from the options endpoint.
  - Mode: Required (auto-enroll) / Opt-in.
  - Live preview: "N people match · M will be enrolled now", sample names.
  - Save → confirm dialog when required ("Enroll M people now?") → PUT; toast with counts. Remove audience button.
  - When an audience is set, show a note that upstream public/usergroup controls are managed by the audience.
- Mount: one `// MKA fork` line in `EditCourseAccess.tsx` rendering the panel (document in upstream-modifications.md).
- `apps/web/services/mka/courseAudience.ts` fetchers. Tests per repo convention (`bun test tests`).

### C. Rollout

- Env `MKA_COURSE_AUDIENCE_ENABLED` + `NEXT_PUBLIC_MKA_COURSE_AUDIENCE_ENABLED` with compose pass-through lines; dev on after merge; prod via `custom/ops/promote.py`.
- Runbook: `docs/runbooks/course-audience.md` (how to set, semantics, Majlis/Region groups are self-selected so not offered here, never-unenroll rule).

## 4. Out of scope

Approval workflow for opt-in; member (non-officeholder) department membership; Majlis/region-scoped audiences (self-selected — later, if wanted); compliance-cycle course changes.

## 5. Acceptance

1. Course with audience custom{department:maal}, required, published → every proven Maal office holder (local/regional/national) enrolled immediately; non-Maal users cannot see it.
2. Course officeholders/optin → visible and startable for any proven office holder, hidden for plain members, nobody auto-enrolled.
3. Course everyone/required → every org member enrolled; new signup enrolled on profile save.
4. All API tests green (`uv run --no-sync --with greenlet pytest src/tests/services/mka src/tests/routers -q`), web tests + lint green, upstream touches limited to documented tagged lines.
