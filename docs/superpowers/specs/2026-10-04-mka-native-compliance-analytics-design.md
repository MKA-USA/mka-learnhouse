# MKA Native Compliance Analytics (in-LearnHouse) — Design Spec

- **Date:** 2026-10-04 · **Status:** approved to build by the user (requirement: *"If you are a Mohtamim or a course creator you should be able to see the analytics dashboard natively couched in LearnHouse like all the other pages or settings a course creator may have access to"*)
- **Supersedes** the standalone dashboard UI of workstream W3 (`custom/compliance/apps/dashboard`). W3's `packages/analytics` logic, tests, fixtures and notes remain the **reference implementation** to port.
- **Parents:** `…-mka-compliance-system-design.md` (umbrella), `…-mka-conditional-visibility-design.md` (attributes), integration map `/Users/mamjed/Documents/mka-thinkific-migration/analysis/NATIVE_INTEGRATION_MAP.md` (**read it fully; every hook below is cited there**).
- **Fork policy:** all logic in fork-only files; upstream files get ONLY the one-line hooks listed in §7, each logged in `.codebase-memory/upstream-modifications.md`. Base: the attributes work (`feature/mka-attributes-api`) because it provides `mka_user_attributes` (`eff_*` columns).

## 1. Who sees what
| Viewer | Where | Sees |
|---|---|---|
| Course creator (ACTIVE author/contributor of a course; incl. a Mohtamim authoring their department course) | **Course page → "Compliance" tab** (course permission `update`) and the org-level **Compliance** page | Only the courses they author (scope `own`) |
| Org admin / Maintainer / role with `organizations.action_update` / national-or-Aitmad attributes | Org-level **Compliance** page | All cycle courses (scope `all`): department × region heatmap, ranked attention list, drill-downs |
| Everyone else | no nav item; endpoints return 403 | — |
- API tokens get scope `all` only (no own-scope for tokens). Enforcement is **server-side on every endpoint**; the UI only hides things. Org match enforced (cross-tenant lesson from review).
- **Platform gate (documented, not coded):** `AdminAuthorization` blocks all of `/dash` unless the user has `dashboard.action_access` (Admin, Maintainer, Instructor). Mohtamims and national/Aitmad viewers therefore need a role carrying it (Instructor or a custom "Mohtamim" role). Deliver `docs/runbooks/mka-compliance-roles.md` (steps for an org admin; roles endpoints reject API tokens so this is a manual admin-UI step for ~22 people).

## 2. Data model (fork-only, idempotent migration + create_all guard, all org-scoped)
- `mka_compliance_cycle(id, org_id, label UNIQUE per org, starts_on, deadline_on)`
- `mka_compliance_cycle_course(cycle_id, course_id FK course.id, course_uuid, kind 'general'|'department', department NULL, signoff_assignment_id NULL, contact_check_assignment_id NULL)`; UNIQUE(cycle_id, course_id)
- `mka_compliance_expected(cycle_id, email, department, level 'national'|'regional'|'local', majlis NULL, region NULL, role_title, person_name NULL, appointed_on NULL, source, formula_unconfirmed bool)`; UNIQUE(cycle_id, email, department, level, role_title). **This is the expected roster**: it makes "never signed in" learners visible (they have no user row / no enrolment) — the most important cohort to chase. Rows join to `user` by lower(email); a person may hold several roles.
- Import API (org admin session OR org API token; org-scoped; idempotent; ≤2000 rows per batch; one bad row never aborts the batch; returns per-row errors): `POST /mka/compliance/cycles` (upsert cycle + its courses from the provisioner's `out/cycle-courses.json` shape), `POST /mka/compliance/expected/import`, `DELETE /mka/compliance/cycles/{id}/expected` (clear for re-import). The provisioner (W2) will call these.

## 3. Definitions (port W3's `custom/compliance/packages/analytics` — read it in worktree `/Users/mamjed/Documents/GitHub/mka-learnhouse-mka-compliance-dash`; copy its test vectors into shared JSON vectors used by BOTH Python tests and the web unit tests)
Per expected person × cycle course:
- `lessons_done / lessons_total` — count completed `TrailStep`s on **published** activities of the course (set-based SQL; **no per-user calls to `is_course_fully_completed`**). Course `completed` ⇔ lessons_done == lessons_total (published activities); also expose `TrailRun.status` raw for debugging. Document any disagreement between the two (map risk 4).
- `attested` ⇔ a submission exists for the cycle course's `signoff_assignment_id`. A person is **fully attested** for the cycle ⇔ attested on the General course AND on their department course (configurable `attested_requires = both|any`, default both).
- `status`: `not_signed_in` (no user row) · `not_started` · `in_progress` · `completed` · `attested` · `overdue` (past due date and not attested). Due date = `deadline_on`, or `appointed_on + 30d` when present.
- **Attention score + RAG with human-readable reasons** per department and per department×region cell: shortfall of attested % vs a linear expected curve (cycle start → deadline) + overdue count + not_signed_in count + contact-check mismatches; thresholds in a config dict. Output includes `reasons: string[]` such as "23 of 52 Majalis haven't started; 9 overdue".
- **Contact self-check:** compare the FORM answers (`assignmenttasksubmission.task_submission`) for `contact_check_assignment_id` to the expected roster (regional Qaid / department head for the learner's Majlis). The FORM answer JSON shape is UNVERIFIED — inspect the code that stores it and the staging draft assignments created by the pilot (`out/cycle-courses.json` has the task ids); if the shape can't be established, ship raw answers + `mismatch: null` and report.
- **Trend:** derive "attested/completed by date" from step/submission timestamps if they exist (verify); otherwise add a tiny daily snapshot table + an admin-triggered snapshot endpoint (no scheduler in v1).

## 4. API contract (fork router `apps/api/src/routers/mka_compliance.py`, mounted `/mka/compliance`; services in `services/mka/compliance*.py`)
All GET responses: `{ "cycle": {id,label,starts_on,deadline_on}, … }`; every endpoint accepts `?cycle_id=` (default = newest cycle). Pagination `page`,`page_size` (≤200) on list endpoints.
- `GET /scope` → `{ scope: "all"|"own"|"none", courses: [{course_uuid, name, kind, department}], departments: [..] }` (what the viewer may see; drives nav visibility).
- `GET /overview` (scope all) → `{ totals:{expected,not_signed_in,not_started,in_progress,completed,attested,overdue}, departments:[{department, counts…, attested_pct, rag, score, reasons[]}], cells:[{department, region, counts…, rag, reasons[]}] , attention:[ranked departments/cells with reasons] }`
- `GET /courses/{course_uuid}/summary` → `{ course:{…}, totals{…}, by_region:[…], by_majlis:[…], by_level:[…], rag, reasons[] }` (own or all)
- `GET /courses/{course_uuid}/learners?status=&region=&majlis=&level=&q=&sort=&page=` → `{ items:[{email, role_title, person_name|null, department, level, majlis, region, signed_in:bool, status, lessons_done, lessons_total, last_activity_at, attested_at, contact_check:{answers?, mismatch:true|false|null}}], total }`
- `GET /courses/{course_uuid}/learners.csv` (same filters; the **chase list**: who, role, Majlis, mailbox, status) — scope-checked; never leaks other courses' rows.
- Errors: 401/403/404 standard; a course outside the viewer's scope returns **404** (don't confirm existence).
- Pure scoring functions are **separate from SQL and fully unit-tested**; SQL aggregations are set-based with indexes noted in the PR.

## 5. Web (fork-only files; Tailwind v4 + Radix `components/ui`, phosphor/lucide icons, recharts, TanStack Query; English-only like other fork components; **match upstream dash look exactly — imitate `dash/analytics/page.tsx`, `CourseAnalyticsTab`, `CourseWidgetCard`, `CourseLearnerProgress`, `OrgUsers.tsx`, `dash/courses/client.tsx`**)
- **Org page** `apps/web/app/orgs/[orgslug]/dash/compliance/page.tsx`: scope `all` → department × region **heatmap** (accessible: RAG with icon + label, never colour alone), ranked "Needs attention" list with reasons, drill-down to department → region/Majlis; scope `own` → list of the viewer's courses with their RAG/summary; cycle picker; empty states ("No cycle imported yet", "0 expected"), loading/error states, responsive.
- **Course tab "Compliance"** (hook H3): summary cards, by-region/by-Majlis breakdown, learners table with filters/search/status chips, **Download chase list (CSV)**; the "Remind" action is a feature-flagged placeholder (reminders pending a user decision) — render nothing unless the flag is on.
- Never show other courses' data; handle `scope: "none"` by not rendering nav/tab.
- Quality bar: a department head must see "who do I chase" within seconds; keyboard and screen-reader friendly; no layout shift.

## 6. Tests
API (pytest; follow existing fork test style): scope matrix (admin, maintainer, role with org update, national attribute holder, ACTIVE author, INACTIVE author, plain user, token); **cross-tenant** (org A can't see org B cycles/learners/CSV; import org-scoped); a course outside scope → 404; import idempotency and bad-row handling; aggregation correctness on a seeded dataset incl. `not_signed_in`; scoring vectors; CSV scoping. Web: unit tests for pure helpers/components, `tsc`, lint, and a Playwright screenshot of the org page and course tab on seeded data if Playwright is available in the repo.

## 7. Upstream hooks (verified in the integration map; each one logged)
H1 `DashLeftMenu.tsx` (3 lines after the Analytics HoverMenu ~L830 + scope hook beside `useAdminStatus()` ~L197; `ShieldCheck` import on its own fork line) · H2 `DashMobileMenu.tsx` (one `PanelItem`) · H3 `dash/courses/course/[courseuuid]/[subpage]/page.tsx` (tabs push after the array close + render line + import; `requiredPermission: 'update'`) · H4 `router.py` (`include_router`). Fork-only: `dash/compliance/page.tsx`, `components/mka/compliance/*`, `services/mka/compliance.ts`, API router/services/db/migration/tests, runbook. If any hook turns out wrong, STOP and report.

## 8. Out of scope here
Reminders (user decision pending; leave a flag), server-side filtering of content, the audience block (W1b), provisioner changes (W2 will push cycle/roster via §2 import endpoints and set course authors).
