# MKA Annual Officeholder Compliance Training — System Design (umbrella)

- **Date:** 2026-10-04 · **Status:** approved to build by the user in conversation (Option B, all phases, Nov 1 target)
- **Companion spec (Feature A attributes + Feature B audience block):** `docs/superpowers/specs/2026-10-04-mka-conditional-visibility-design.md` (D1–D4 approved at recommended defaults)
- **Source material:** `/Users/mamjed/Documents/mka-thinkific-migration/` (`HANDOFF.md`, `analysis/DIFF_REPORT.md`, `data/`)
- **Environment rule:** staging only (`https://ilm-dev.mkausa.org`, API `…/api/v1`). Nothing is published; everything created is a draft. Never touch production.

## 0. Job to be done

> **When** the MKA year turns on Nov 1 and ~1,200 officeholders (national, 10 regional, 52 Majlis × ~22 roles) are appointed or re-appointed, **I want** each of them to complete a short, current, role-appropriate training and sign off, **so that** MKA has an auditable annual compliance record, and **each department head can see which Majalis/regions are behind and chase them**.

Today: 21 near-identical Thinkific courses, ~1,250 hand-typed contacts, "quizzes" that are one "I confirm…" question, no completion reporting. Findings in `analysis/DIFF_REPORT.md`.

## 1. Requirements (from Raza's 2024-25 brief + user, 2026-10-04)
1. SSO (Google, mkausa.org) — already in the fork.
2. Per cycle: **General course** (everyone) + **Department course** (one per department, 21).
3. Each topic ends in a confirmation or quiz; final sign-off per course. Attestation stored per learner (audit).
4. Contacts: each learner must find/confirm their national, regional and local counterparts.
5. **Analytics:** authors/Mohtamims see per-learner progress ("how far they got") and groupings by Majlis, region, department; the system must make **"which departments need special attention"** obvious. National/Aitmad see everything.
6. One yearly-updated data source drives course content (contacts, department plans, OKRs, Huzoor's message link). Nov 1 starts a new cycle; learners complete within 30 days of appointment (cycle deadline Dec 1).
7. New LearnHouse role **Mohtamim** (instructor/admin-like) scoped to their own department's course.
8. Officeholders are normal learners and receive normal learner nudges. (UNVERIFIED that LearnHouse sends learner-facing nudges; W3 verifies. If none exist, escalate — do not silently build a scheduler.)
9. Compliance tooling sits **on top of** LearnHouse; fork edits only via the one-line hooks listed in the companion spec.

## 2. Architecture

```
Google Sheet / CSV (yearly data, owned by Aitmad + Mohtamims)
        │ import (idempotent)
        ▼
┌────────────────────── custom/compliance (NEW, fork-isolated, own deploy + Postgres) ──────────────┐
│ packages/core   schema, LH admin-API client, templates, rules loader                              │
│ apps/provisioner  CLI: import → validate → render → create/update DRAFT courses → enroll          │
│ apps/dashboard    Next.js + HeroUI v3: analytics, Mohtamim/Aitmad views, CSV, Google SSO           │
└───────────────┬───────────────────────────────────────────────┬───────────────────────────────────┘
                │ lh_ admin token (Bearer)                      │ GET /mka/attributes/* (admin token)
                ▼                                               ▼
         LearnHouse (upstream behaviour: courses, trails, assignments, certs, SSO, nudges)  +  fork: mka_user_attributes, mkaAudience block
```

Fork-side (companion spec): hidden identity attributes derived from the verified Google email (parser + overrides), `mkaAudience` block, inline fields, "My counterparts" card. The companion is the **only** consumer of attributes for analytics; the parser rules file `identity_rules/2026.1.json` is the shared contract.

## 3. Course model (per cycle, e.g. `2026-27`)

- **22 courses per cycle**: `MKA 2026-27 · General` + 21 × `MKA 2026-27 · <Department>`. A new cloned/generated set each cycle (reset-in-place is rejected: it deletes history and the unique trail-run constraint allows one run per user per course). Role mailboxes pass to the next holder, so a new course set also cleanly resets the clock.
- **General** (source: Thinkific *Foundation Course*, plus Raza's 2024-25 list): intro video · Jama'at & Khuddam structure (quiz) · Nizam-e-Jama'at (quiz) · Resources (email, Info Center, Tajneed, reporting, calendar — each "log in and confirm") · Housekeeping rules · Huzoor's latest message (read & confirm, yearly link) · sign-off.
- **Department** (generated from templates + yearly data): Goals & responsibilities (by level) · Annual department plan/OKRs · Responsibilities of a Nazim · Important contacts (directory lesson **plus**, after the audience block ships, the "My counterparts" card) · Contact self-check form · Attestation.
- **Attestation** = LearnHouse **assignments** (they persist per-user submissions with audit events): a QUIZ task for knowledge checks, a FORM task for the contact self-check (select Majlis, name regional Qaid and department head — the companion later compares answers to the roster and surfaces mismatches), and a final FORM sign-off ("I have read and understood…" + typed full name). No new block.
- Every course stays **draft**; a human publishes. Course/lesson names and order are deterministic so re-running the provisioner updates in place.
- Content rules (Thinkific skill): Islamic content only from the approved sources (Philosophy of the Teachings of Islam, alislam.org with URLs, Holy Quran English); no images of the Holy Prophet (sa) or companions; keep original wording when only restructuring; flag anything citing other sources.

## 4. Yearly data model (companion Postgres; Drizzle)

`cycle(id, label, starts_on, deadline_on)` · `department(slug, name, translation, mailbox_prefix, level_scope)` (canonical, versioned; mirrors fork rules) · `person_role(cycle_id, department, level, majlis, region, role_title, learner_email, person_name?, source)` — **generated from the email formula for all 52 Majlis × all roles** (every Majlis has every role; a missing name or bad row is a *data gap*, never an absent role) with overrides · `dept_plan(cycle_id, department, level, responsibilities_md, okrs_md, resources_md, updated_by)` · `directory_override` · `course_map(cycle_id, kind, department, lh_course_uuid, chapters/activities map)` · `idmap` (Thinkific ids → new LH uuids, for traceability) · `enrollment_log` · `progress_snapshot(...)` (W3).
Import is **idempotent and validating** (bad rows reported, not fatal): duplicate/shifted rows, `#REF!`, slug aliases (Syracuse), the swapped Atfal/Amoor-e-Tuluba columns, `rishtanata` reuse for Nau Mubaeen.

## 5. Analytics ("which departments need special attention")

Definitions (all per **cycle**, per learner = per roster `learner_email`):
- **Status:** `not_started` · `in_progress (lessons_done/total)` · `completed` · `attested` (final sign-off submitted) · `overdue` (past deadline_on, not attested). Mid-year appointees: due = appointed_on + 30d if present.
- **Aggregates** by department, by region, by Majlis, by level, and cross-tabs department × region: expected (roster), started %, completed %, attested %, overdue count, median days to complete, last activity.
- **Attention score** per department (and per department×region cell): shortfall of attested % vs. an **expected curve** (linear from Nov 1 to the deadline, parameterised), plus overdue count, plus contact-self-check mismatch count. Display as RAG (green/amber/red) with the *reason* ("23 of 52 Majalis haven't started; 9 overdue"), never a bare score. Thresholds in config.
- **Views:** Aitmad/National overview heatmap (department × region) with drill-down → Majlis → individual role (name/email, last activity, lessons done, quiz scores, sign-off); Mohtamim view = their department only; "chase list" CSV (who, role, Majlis, mailbox, status); trend vs. yesterday/last week from daily **snapshots** so progress over time is visible.
- **Scoping (defaults, flag to user):** Mohtamim → own department, all levels · Regional Qaid → own region, all departments · Majlis Qaid → own Majlis · Sadr/Motamid/admin → all. Derived from fork attributes; override table.
- **Source:** LearnHouse admin API (enrollments, trail runs/steps, assignment submissions) synced into snapshots on a schedule (webhooks `course_completed`/`course_enrolled` as optimisation only — UNVERIFIED in OSS mode; polling is the baseline). Attributes via fork API; no scraping of the DB.
- **Auth:** Google SSO restricted to mkausa.org; authorization from attributes + override table.

## 6. Mohtamim role
LearnHouse **custom role** (permission matrix) giving instructor-level rights over their own department course. W3 first verifies what the role matrix and course-level author/contributor model can express (UNVERIFIED) and reports; if a Mohtamim cannot be scoped to one course, fall back to: role gives dashboard access in the companion only, with LearnHouse authoring done by Aitmad until resolved. Role assignment is by the companion (roster-driven) via admin API.

## 7. Phases and the Nov 1 cut line

| Phase | When | Content | Workstream |
|---|---|---|---|
| **P1 — must ship for Nov 1** | now → Oct 28 | attributes API + parser (M1, M2) · provisioner + General + 21 Dept courses (drafts) + attestation + enrollment · analytics + Mohtamim role · counterparts card/inline fields (M3 minimal, M6) | W1a, W2, W3, W1b |
| **P2 — after Nov 1** | Nov | full audience-block authoring UX (M4), Preview-as (M5), Playwright persona e2e (M7) | W1b |
| **P3** | Dec+ | coverage/overlap hints, server-side strip, mid-year appointee flow, reminders if W3 finds no learner nudges | later |

**Human dependencies (cannot be built away):** (1) each Mohtamim's **2026-27 department plans/OKRs** — if absent, the course ships with last year's text *flagged stale*; (2) Huzoor's latest-message link/PDF; (3) the roster names still being finalised; (4) D5 answers (`newyorkmetro-region`, `muqami@`, `atfalusa.org` SSO).

## 8. Workstreams, worktrees, delivery

Base for all worktrees: `origin/dev` (the local `dev` is 2 commits behind, missing PRs #3/#4). Path `../mka-learnhouse-<name>`, branch `feature/<name>`. Executors commit on their branch only; coordinator reviews diffs; push/PR to `dev` and any merge/deploy happen with the user's confirmation; **never production**.

| ID | Worktree / branch | Owns | Depends on |
|---|---|---|---|
| W1a | `mka-attrs-api` / `feature/mka-attributes-api` | companion spec M1+M2 (rules file, parser + 150-row matrix, migration, store, audit, login hook A2, router A1, admin/me/list endpoints, backfill) | — |
| W2 | `mka-compliance-core` / `feature/mka-compliance-core` | `custom/compliance` scaffold (`packages/core`, `apps/provisioner`), schema, importer, templates, course generator, enrollment, idmap | scaffold first (milestone 0) |
| W3 | `mka-compliance-dash` / `feature/mka-compliance-dash` | `apps/dashboard`, snapshots/sync, attention scoring, Mohtamim role research+setup, auth/scoping | W2 milestone 0; W1a API contract (fixtures until live) |
| W1b | `mka-audience-web` / `feature/mka-audience-web` | companion spec M3, M6 (P1) then M4, M5, M7 (P2) | W1a `/mka/attributes/me` contract |

Concurrency cap: 3 executors; start W1a + W2; start W3 when W2 milestone 0 lands; W1b takes the next free slot. Executors are Sonnet, pinned; each prompt carries the `learnhouse-docs` MCP rule, the repo CLAUDE.md fork policy, and (dashboard) the HeroUI v3 docs rule.

## 9. Acceptance (P1)
- `bun test`/pytest green on new code; lint passes; no upstream file changed except the hooks listed in the companion spec, each logged in `.codebase-memory/upstream-modifications.md`.
- On ilm-dev: General + 21 Dept draft courses exist for cycle 2026-27, lessons render, attestation tasks work end-to-end for a test learner, enrollments created for the generated roster (dry-run report first).
- Dashboard shows department × region heatmap, drill-down, chase-list CSV, scoped per role, with seeded/test data and then real staging data.
- A written **data-gap report** (missing names/emails, shifted rows, stale plans) is delivered for the user to fix upstream in the sheet.

## 10. Risks
Four-week schedule (22 days for the fork feature alone — hence the P1/P2 split) · stale department plans · token scope on ilm-dev (unverified until W2's first call) · webhook availability in OSS mode · TipTap unknown-node blank-lesson failure (hook-guard test in companion spec) · PII in the companion DB (same access control as LearnHouse; no copies of the directory into logs).
