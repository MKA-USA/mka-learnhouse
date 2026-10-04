# MKA Profile Fields (Majlis / Region) — Sub-project 1: Capture & Store

Status: IMPLEMENTED on branch `worktree-mka-profile-fields` (spec synced to what shipped; see §11 for limitations). Date: 2026-10-04. Branch context: `dev`.
Sub-project 2 (reporting: CSV, admin filters, analytics breakdowns) is a separate spec built on this one.

## 1. Goal (JTBD)

When someone registers (email, invite, or Google), I want us to know their **Majlis**
and therefore their **Region**, plus optional Mobile / AMC ID / Tanzeem, so MKA admins can
report on learners by Region and Majlis.

Success criteria
- Every new user has a Majlis; Region is always derived server-side from it.
- Google users and existing users cannot use the platform until Majlis is set (hard gate).
- AMC ID is unique when present; blank AMC IDs never collide.
- Zero edits to upstream data models/tables; upstream merges stay clean; all upstream-file
  edits are 1–3 line `# MKA fork` hooks logged in `.codebase-memory/upstream-modifications.md`.
- New UI uses LearnHouse's own primitives and theme tokens (inherits dark mode / branding).

## 2. Fields and data

| Field | Required | Notes |
|---|---|---|
| Name | yes | existing `first_name` / `last_name` on `User` — no change |
| Email | yes | existing |
| Majlis | yes (app-enforced) | one of 52, see §3 |
| Region | derived | server-set from Majlis; client value ignored |
| Mobile | no | US-only. Accept common formats (spaces, dashes, parentheses, optional `+1`/`1` prefix); must resolve to 10 digits with a valid NANP area code (first digit 2–9). Stored normalized as `+1XXXXXXXXXX` |
| AMC ID | no, unique | digits only. Trimmed; any non-digit input is rejected (not silently stripped). Stored as a string so leading zeros survive. No length rule was given, so none is enforced beyond 1–15 digits as a sanity cap |
| Tanzeem | no | enum `khadim` \| `tifl` \| null (mutually exclusive) |

### Storage: fork-only side table (CHANGE from the approved design)
The approved design put 5 columns on `User`. Refined to a one-to-one side table so no upstream
model/table is modified (the `User` model is among the likeliest files to conflict on merge):

`mka_user_profile`
- `user_id` int PK, FK → `user.id` ON DELETE CASCADE
- `majlis` varchar NOT NULL, `region` varchar NOT NULL
- `mobile` varchar NULL, `amc_id` varchar NULL, `tanzeem` varchar NULL
- `created_at`, `updated_at`
- Unique index on `amc_id` WHERE `amc_id IS NOT NULL` (partial; Postgres). Tests run SQLite, where
  NULLs are already distinct under a plain unique index, so the model declares a plain unique
  index and the Postgres migration makes it partial.
- Write order: validation (incl. the AMC pre-check) runs BEFORE the user row is created; the profile row is written right AFTER the user commit (the real `create_user` commits the user and the org link separately, so it is not one transaction). See §7.
- A user with no row = "profile incomplete" (this is what triggers the gate). Rows are only
  written complete (majlis + region always present).

Cost: reporting needs a LEFT JOIN on `user_id` (trivial; sub-project 2 will use it).
If the user prefers columns on `User`, that is a contained swap (OPEN Q2).

PII: mobile and AMC ID are PII. Returned only to the owner and org admins; never added to
`UserReadPublic` / `UserReadAuthor`.

## 3. Single source of truth (fork-only)

`apps/api/src/services/users/mka_profile.py` (new)
- `MAJLIS_TO_REGION: dict[str, str]` — the 52 pairs supplied by the user (11 Regions:
  East, Great Lakes, Gulf, Midwest, Muqami, New York Metro, Northeast, Northwest, Southeast,
  Southwest, Virginia).
- `Tanzeem` enum; `normalize_amc_id`, `normalize_mobile`, `validate_profile(payload)`.
- `region_for(majlis)`; unknown Majlis → validation error.
- `apply_profile(session, user, payload)` / `upsert_profile(...)` used by all create paths and
  the gate endpoint; translates the unique-index violation into a 409 "AMC ID already registered".
- Majlis options are served to the frontend by API (§5) so dropdown and backend cannot drift.

## 4. Upstream-merge safety (hard rules)

1. New logic lives in new files only (`mka_*`, `components/mka/`, one new migration, one router).
2. Upstream files get minimal hooks marked `# MKA fork` (TS: `// MKA fork`), each logged in
   `.codebase-memory/upstream-modifications.md` with file, reason, and exact diff (existing policy).
3. Do not modify existing files in `components/ui/*` (the one allowed change there is adding the new shadcn `command.tsx`, see §6), `db/users.py`, `CompleteSignupFields.tsx`, or the org
   signup-fields service/endpoints (all upstream-owned; confirmed present on `upstream/main`).
4. Guard against silent hook loss after merges: tests exercise behavior (a created user gets a
   profile row; the gate mounts), not just file contents, so a lost hook fails CI.
5. Alembic: fork migration id prefixed `mka_`, `down_revision` = the head at implementation time
   (currently `b1c2d3e4f5a6`; **re-run `alembic heads` in the API venv first** — `alembic` was not
   on PATH in the exploration shell). After each upstream merge run `alembic heads`; if >1, add a
   fork merge migration. Never edit upstream migrations.
6. Sync routine (documented in this spec, run by humans): `git fetch upstream && git merge upstream/main`
   → resolve conflicts preferring upstream, re-apply hooks from the log → `alembic heads` → run the
   fork tests.

### Upstream files that received hooks (complete list, as shipped)
| File | Hook |
|---|---|
| `apps/api/src/services/users/users.py` | only `create_user` and `create_user_without_org` (not `create_user_with_invite`, which calls `create_user`): `validate_signup_profile(...)` before `User.model_validate`, `save_signup_profile(...)` after the user commit/refresh; plus one import |
| `apps/api/src/db/users.py` | `UserCreate`: one optional field `mka_profile: Optional[dict] = None` |
| `apps/api/src/router.py` | one import + one `include_router` (prefix `/mka/profile`) for the fork router |
| `apps/web/app/api/signup/route.ts` | coerces and forwards only four string/null keys (`majlis`, `mobile`, `amc_id`, `tanzeem`); never spreads client input |
| `apps/web/app/auth/signup/OpenSignup.tsx`, `InviteOnlySignUp.tsx` | Formik value + validation, `<MkaProfileFields/>`, API-shaped body via `mkaValuesToBody`, server errors mapped by the fork helper `applyMkaServerErrors` |
| `apps/web/app/orgs/[orgslug]/layout.tsx` | mounts `<MkaProfileGate />` immediately before `<CompleteSignupFields />`. This is the ONLY gate mount point: the `app/(hub)/layout.tsx` is SaaS-only org management (404s on oss/ee) and is deliberately not hooked |
| `apps/e2e/core/client.ts` | `createStudent` sends `mka_profile: { majlis: 'Zion' }` so e2e user creation passes the new required-Majlis rule |

Edited upstream tests: `test_signup_custom_fields_flow.py` and `test_users_service.py` pass `mka_profile={"majlis": "Zion"}` on non-OAuth `UserCreate`. Added upstream-directory file: `apps/web/components/ui/command.tsx` (shadcn, hand-created from `shadcn view command`). Everything is logged with exact diffs in `.codebase-memory/upstream-modifications.md`.

### Upstream sync checklist
After `git fetch upstream && git merge upstream/main`:
1. `grep -rn "MKA fork" apps` and confirm every logged hook is still present (counts are listed in the log).
2. `alembic heads` (apps/api venv): exactly one head (`mka_20261004_user_profile` today). If two, add a fork merge migration chained after upstream's; never edit upstream migrations.
3. Run `python -m pytest src/tests -q` in `apps/api` (long-running; at minimum the MKA profile tests, `test_signup_custom_fields_flow.py`, `test_users_service.py`), then `bunx tsc --noEmit`, `bun run lint:strict`, `bun test tests` in `apps/web`.
4. If upstream adds its own `components/ui/command.tsx`: take upstream's, run `bunx shadcn@latest diff command`, re-check `MajlisCombobox.tsx`.
5. Re-check `apps/web/components/ui/dialog.tsx` (inline `style` block in `DialogContent`): the gate repeats those properties on purpose (§6).
6. Any new upstream test creating a non-OAuth `UserCreate` needs `mka_profile={"majlis": "Zion"}`.

## 5. API (fork-only router `apps/api/src/routers/mka_profile.py`)

Prefix `/mka/profile` (NOT `/users/me/...`, to avoid colliding with `PUT /{user_id}` in `routers/users.py`).
- `GET /mka/profile/options` → `{majlis: [{name, region}], tanzeem: [...]}` (auth not required;
  needed on the signup page).
- `GET /mka/profile/me` → the caller's profile or `{complete: false}`. Dependency: `get_authenticated_user`.
- `PUT /mka/profile/me` → validate, derive Region, upsert; 409 on AMC conflict, 422 on bad input.
- Admin edit of another user's profile: `PUT /mka/profile/user/{user_id}?org_id=<org>`.
  - Allowed: ADMIN-role members of `org_id` (maintainers are NOT allowed); platform superadmins unrestricted.
  - A nonexistent target, or (for non-superadmins) a target who is not a member of `org_id`, returns 404. Non-admins get 403 BEFORE any target lookup (no existence oracle).
  - API-token callers get 403 (also excluded at router level by `get_non_api_token_user`).
  - Full-replace PUT semantics: omitted optional fields are cleared (an admin can clear a squatted AMC ID). Region re-derives; AMC conflict is 409.
- `GET /mka/profile/user/{user_id}?org_id=<org>` → the target's `profile_status` (full profile incl. mobile/AMC/Tanzeem, or `{complete: false}`). Identical authorization and 403/404 ordering as the PUT (one shared helper in the router). Because PUT is a full replace, an editor must GET first, change fields, then PUT the complete object; a PUT with only `majlis` wipes the rest.
- **GDPR**: `anonymize_user` (admin API) deletes the user's profile row in the same transaction as the scrub (mobile and Majlis are removed, the AMC ID is freed for reuse); `export_user_data` adds an `"mka_profile"` key (`profile_status` output; `{"complete": false}` when none). Hard user delete cascades in the DB.
- Signup 422 items are `{field, message, msg}` (`msg` mirrors `message` so upstream's generic error parser shows the real text). The AMC pre-check runs after the signup permission check, so a forbidden signup never answers 409.

Signup (email / invite / org-less): server requires a valid Majlis when `is_oauth` is false;
missing/invalid → 422 before the user row is created. Google (`is_oauth=True`) skips it; the gate
collects it.

Not in scope: blocking every backend route for incomplete profiles. The gate is a UI gate, and it **fails open**: it renders nothing when `GET /mka/profile/me` errors (the API is not blocked either way).

## 6. Frontend

Everything uses LearnHouse's existing stack: Radix-based primitives in `apps/web/components/ui/`
(`input`, `select`, `dialog`, `button`, `label`, `popover`, `alert`), Formik + Yup,
`useLHSession`, `apiFetch` / `RequestBodyWithAuthHeader`, react-query. **No HeroUI** — it is not a
dependency of `apps/web` (the global HeroUI note does not apply to this repo).

New fork-only files in `apps/web/components/mka/`:
- `MkaProfileFields.tsx` — Majlis combobox (required), Mobile, AMC ID, Tanzeem select. Used by
  the signup forms and the gate. Region is shown read-only after Majlis is picked.
- `MajlisCombobox.tsx` — searchable select (52 options, grouped by Region via `CommandGroup`)
  composed exactly as shadcn's documented **Combobox pattern**: existing `Popover` + the official
  shadcn `Command` component. **No custom primitive is written.** `Command` is not in the repo yet
  (neither in `apps/web/components/ui` nor on `upstream/main`), so it is added with the project's own
  shadcn config: `cd apps/web && bunx shadcn@latest add command` (`components.json`: `new-york`,
  Tailwind v4, CSS variables, lucide). It wraps `cmdk` ^1.1.1, already a dependency, and its
  `CommandDialog` reuses the existing `ui/dialog`. Inspect the generated file and run lint/type
  checks; it must use theme tokens only (it does by default).
  Fork note: this is a brand-new file in `components/ui/` (shadcn's convention, no edits to any
  existing upstream file). If upstream later adds its own `command.tsx`, the add/add conflict is
  resolved by taking upstream's version. Log it in `upstream-modifications.md` as "added file".
  Tanzeem (2 options) uses the existing Radix `ui/select`.
  Fallback if `Command` proves awkward: a plain `ui/select` with `SelectGroup` per Region (zero new
  files, keyboard type-ahead only, no touch search).
- `MkaProfileGate.tsx` — non-dismissible `Dialog`: `onInteractOutside` / `onEscapeKeyDown`
  `preventDefault`, close X hidden via `[&>button:last-child]:hidden` on `DialogContent` (`dialog.tsx` is not edited).
  Theming: token classes (`bg-background text-foreground border-border`) passed through `cn`, overriding `dialog.tsx`'s hardcoded white classes.
  Stacking: `dialog.tsx` sets `zIndex`, `translate`, `willChange`, `backfaceVisibility` as an inline `style` and spreads `{...props}` after it, so the gate's own `style` REPLACES it. The gate therefore sets z-index `calc(var(--z-popover) - 10)` (= 240, above the legacy dialog at `--z-modal` 210 and below popovers at 250 so the Majlis list stays visible) and REPEATS the other three properties. Coupling: re-check `ui/dialog.tsx` after upstream merges (§4 checklist).
  Renders only when session is authenticated and `GET /mka/profile/me` says incomplete. Includes a
  sign-out escape so a user is never trapped. Not rendered on `/auth/*` routes.
- `services/mka/profile.ts` — thin client for the three endpoints.

### Component sourcing policy (research, verified 2026-10-04)
- **Primary base: official shadcn/ui** (`new-york`, Radix) via the repo's own `components.json`.
  Same token names and file layout as `apps/web/components/ui`, so theming and dark mode apply
  automatically. MIT, actively maintained.
- **Supplementary, when a future feature needs it: ReUI** (MIT, active; Data Grid, Filters, Stepper).
  Take Radix variants only; review each item's `registryDependencies` before installing.
- **Base UI:** stay on Radix. shadcn's own `combobox` item is Base UI based and adds `@base-ui/react`;
  we do not need it because `Command` + `Popover` uses what is installed. If Base UI is ever
  introduced, confine it to that one component.
- **Avoid:** coss ui / Origin UI (`@coss/ui` core is AGPL-3.0-or-later, mixed-license repo — risk for a
  fork), Cult UI / Magic UI (decorative, not form/data work), Animate UI / shadcn-studio (licence
  unconfirmed).
- **Install rules:** never use `--overwrite` (it would replace our customized `button`, `input`, etc.);
  decline any proposed `globals.css` token patch (our tokens are bare HSL mapped via
  `hsl(var(--x))`; registries assuming `oklch` will not compose); take primitives only from
  registry form blocks, since many import `react-hook-form` + `zod` and this app uses Formik + Yup.
- **Mobile field:** US-only normalization is plain code in `mka_profile`/`MkaProfileFields` on the
  existing `ui/input`; no phone-input library is added.
- Unverified: ReUI's exact install URL pattern (check its docs at install time).

### Theming (native)
Use only tokens from `apps/web/styles/globals.css`: `bg-background`, `text-foreground`,
`bg-primary`/`text-primary-foreground`, `border-input`, `border-border`, `text-muted-foreground`,
`text-destructive`, `ring-ring`, `rounded-md`, brand font variables. **Do not copy** the hardcoded
`bg-neutral-50 text-black` / `text-red-500` classes in `CompleteSignupFields.tsx` — they bypass dark
mode and the MKA palette. How per-org branding overrides these variables was not traced during
exploration; the implementer must confirm that tokens (not literal colors) are sufficient for org
branding and dark mode via a visual check in both themes.

The existing `CompleteSignupFields` dialog is left untouched and keeps working for org-defined
fields. The Majlis gate must appear first (it blocks); ensure two dialogs do not stack (gate takes
precedence; the legacy dialog may mount after the profile is complete).

## 7. Flows

- Email/invite/org-less signup: form (with profile fields) → Next route → API `create_user*`
  → profile validated BEFORE the user row (incl. the AMC pre-check) and written right AFTER the user commit. A rare AMC race (409 after the user commit) is logged without PII and swallowed, the user object is refreshed, and the gate collects the profile on first load.
- Google signup: `/auth/callback/google` → `signWithGoogle` → user created (no profile) → first
  page load → gate → `PUT /mka/profile/me`.
- Existing users: no row → gate on next load.
- Re-mapping later: edit `MAJLIS_TO_REGION`, run a backfill script (`scripts/` or a one-off
  migration) that recomputes `region` from `majlis`. Not built now.

## 8. Testing

Backend (`apps/api/src/tests/services/test_mka_profile.py`, router tests alongside; in-memory
SQLite, existing `conftest.py`):
- Mapping: exactly 52 Majlis, each → exactly one of the 11 Regions; spot-check pairs.
- Normalization and validation (AMC digits-only, rejects letters, keeps leading zeros; US mobile formats normalize to `+1XXXXXXXXXX`, reject non-US/short numbers; Tanzeem enum; unknown Majlis rejected).
- Admin edit: org admin can edit a member of their org; cannot edit a user outside their orgs (403); Region re-derives; AMC conflict still 409.
- `create_user*` with valid profile writes the row; email signup without Majlis → 422, no user created.
- AMC uniqueness: duplicate → 409; two users with null AMC both succeed.
- Google-style creation (`is_oauth=True`) succeeds without profile; `GET /mka/profile/me` →
  incomplete; `PUT` completes it.
- Client-supplied `region` is ignored.

Frontend: gate renders when incomplete and not when complete; cannot be dismissed by Esc/overlay;
form validation messages; Majlis combobox filters. Manual visual check light + dark.

## 9. Out of scope
Reporting UI (sub-project 2); API-wide enforcement; bulk import of existing Majlis data; Region
backfill tooling; Tanzeem multi-select.

## 10. Decisions and open questions
Decided (user, 2026-10-04):
1. AMC ID is numeric only (see §2).
2. Org admins can edit a member's Majlis (and other profile fields). Scope: members of orgs they administer; platform superadmins can edit anyone. Region re-derives on every Majlis change.
3. Mobile is US-only (see §2).

Still open:
- Side table (§2) vs columns on `User`: proceeding with the side table unless the user objects.
- Minimum/maximum AMC ID length, if one exists. Until told, only the 1–15 digit sanity cap applies.

## 11. Known limitations & residual risks
- **AMC ID squatting**: IDs are unverified and first-come unique; someone can claim another member's ID. Mitigation: admins can edit/clear any profile (full-replace PUT).
- **AMC enumeration**: the 409 at public signup reveals whether an AMC ID is registered. Inherent to unique IDs; consider signup rate limiting.
- **Cross-org edit**: the profile is one global row per user, so an admin of ANY org the target belongs to can edit it. Fine for single-org MKA; hardening option: require admin of every org the target belongs to.
- **Maintainers cannot edit profiles** (ADMIN role only).
- **Admin UI deferred**: editing profiles from the admin UI is not built (API only: GET + PUT `/mka/profile/user/{id}`); it belongs to the reporting sub-project.
- **Popover `modal` not applied**: the Popover `modal` approach for wheel scrolling inside the gate was NOT applied; the list uses an `onWheel` stopPropagation workaround. Wheel scrolling in the Majlis list is on the manual-check list.
- **Two dialogs**: the legacy `CompleteSignupFields` and the gate can both open; the gate content sits above (z 240 vs 210).
- **Docs example**: `docs/content/guides/build-learning-platform/do-it-yourself.mdx:442` (`POST /users/{org.id}`) now needs `mka_profile` on this fork; upstream doc not edited.
- **Alembic**: single head `mka_20261004_user_profile` today; after upstream merges run `alembic heads` and add a fork merge migration if there are two.
- **Unverified at runtime** (no browser/Postgres run): dark-mode render of the gate and combobox, popover list above the gate, dialog centering with the overridden `style`, mouse-wheel scroll in the Majlis list, focus handoff gate -> legacy dialog, Postgres partial unique index behavior (tests run SQLite).
- **Test environment**: the shared API venv lacks `greenlet` (tests ran with a `PYTHONPATH` shim), and the full API suite is long-running; only focused suites were run. Some unrelated tests fail pre-existing (see task-8 report).
