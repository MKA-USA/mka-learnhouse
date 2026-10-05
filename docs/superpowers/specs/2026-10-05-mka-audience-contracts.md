# MKA Audience block — frozen contracts (M3–M7)

Status: FROZEN 2026-10-05 by the coordinator. Executors implement against this; any deviation must be reported back, not improvised.
Parent spec (source of truth for UX/intent): `docs/superpowers/specs/2026-10-04-mka-conditional-visibility-design.md` §B1–B9.
Integration branch: `feature/mka-audience` (from `origin/dev` 8ff4d144). Seam branches fork from it.

## 0. Ground facts (verified on origin/dev 8ff4d144)

- `/mka/attributes/me` exists (`apps/api/src/routers/mka_attributes.py:154`), returns `{attributes, stale, can_view_all, rules_version}`; `attributes` keys = `PUBLIC_FIELDS`: `status, is_officeholder, level, department, role, role_title, majlis, region`. Missing row → `status:"unrecognized", is_officeholder:null`; stale row → `status:"unrecognized", is_officeholder:false`. `can_view_all` today = superadmin OR admin/maintainer in ANY org (not org-scoped).
- Role keys emitted by the parser: `sadr, naib_sadr, mohtamim, nazim_dept, qaid, naib_qaid, regional_qaid, motamid, regional_nazim_dept, regional_motamid, nazim_atfal, murabbi_atfal, national_staff`. Titles in rules file `role_titles` (`motamid:national` is a title-lookup key only, never a `role` value).
- Department keys: 21 underscore keys in `identity_rules/2026.1.json` `departments[]`. Regions: canonical names (`"Northeast"`), slugs in `regions`. Majlis: canonical names from `MAJLIS_TO_REGION` (`services/users/mka_profile.py:22`).
- Web stack: TanStack Query + `fetch(getAPIUrl()+..., RequestBodyWithAuthHeader(...))`, token from `useLHSession()`; mock switch pattern `NEXT_PUBLIC_MKA_COMPLIANCE_MOCK==='1' && NODE_ENV!=='production'`. Node views read editability from `useEditorProvider()` (`components/Contexts/Editor/EditorContext.tsx`), which may be null → treat as not editable.
- TipTap 3.31.3, `enableContentCheck:false`: unknown node ⇒ whole doc blank. Hook sites: W1 `Editor.tsx` extensions useMemo (~162), W2 `DynamicCanva.tsx` useEditor extensions (~100; note `isEditable=true` there but provider says false), W3 `EditorPreview.tsx` (~50). Other useEditor sites (DiscussionEditor, DiscussionContent, BoardCanvas) do not load activity content; board `ActivityBlockComponent` renders activity via DynamicCanva (covered by W2). No `generateHTML/generateJSON/new Editor(` in apps/web.

## 1. Rule schema v1 (node attr `rule`)

```jsonc
{
  "v": 1,
  "mode": "show" | "hide",
  "groups": [ Group, ... ],        // length >= 1; OR across groups; UI v1 edits exactly groups[0]
  "label": "string"                // optional cache, NEVER used for evaluation
}
Group = {
  "officeholder"?: boolean,        // default true
  "level"?:      ("national"|"regional"|"local")[],
  "department"?: DeptKey[],        // underscore keys
  "role"?:       RoleKey[],
  "region"?:     string[],         // canonical region NAMES
  "majlis"?:     string[]          // canonical Majlis NAMES
}
```

### 1.1 Validation — `validateRule(raw) -> {ok:true, rule:NormalizedRule} | {ok:false, error:string}` (TS and Py identical)
Invalid (→ `ok:false`) when: not an object; `v` not an integer ≥1; `mode` not `show|hide`; `groups` not a non-empty array or > 20 groups; a group not an object; `officeholder` present and not boolean; a known list key present and not an array of strings; any string empty or > 200 chars; any list > 500 entries; `label` present and not a string ≤ 500 chars.
Normalisation on success: drop known list keys whose array is empty (`{"majlis":[]}` ⇒ key absent, means "any"); de-duplicate list entries preserving order. Unknown group keys are KEPT (they make the group non-matching, §1.2). Unknown top-level keys are ignored. `v > 1` is VALID structurally (evaluation returns false).
Invalid rules: evaluate → `false` for learners (fail-safe hide); author sees an error chip "This section's audience is damaged — choose who should see it".

### 1.2 Evaluation — `evaluateRule(raw, viewer) -> boolean` (pure; TS + Py identical)
1. `validateRule(raw)`; invalid ⇒ `false`. `rule.v > 1` ⇒ `false`.
2. Viewer normalisation `effectiveViewer(viewer)`:
   - `viewer === null` (anonymous / not loaded / fetch error) ⇒ `NULL_VIEWER` with `signedIn:false`, all attributes null.
   - `viewer.status ∉ {"matched","partial"}` (i.e. `unrecognized`, `ambiguous`, `not_applicable`, or anything unknown) ⇒ all attributes null **except** `is_officeholder` which is kept only if it is exactly `false` (not_applicable/stale), else null; `signedIn:true`.
   - `matched`/`partial` ⇒ attributes as given; `signedIn:true`.
3. `groupMatches(g, v)`:
   - any unknown key in `g` ⇒ `false`.
   - `officeholder` (default true): `true` ⇒ requires `v.is_officeholder === true`; `false` ⇒ requires `v.signedIn` (anyone signed in).
   - each present list key `k`: requires `v[k] != null && g[k].includes(v[k])` (exact, case-sensitive string compare).
4. `any = groups.some(groupMatches)`; `show` ⇒ `any`; `hide` ⇒ `!any`.
   Consequence (intended, spec B2): unknown/unrecognized viewers never match a positive condition, so they see untargeted content and "Hide from …" sections, never "Show to …" sections.

### 1.3 Shared vectors
`apps/api/src/tests/services/mka/vectors/audience_vectors.json`:
```jsonc
{ "_comment": "...", "viewers": { "<name>": Viewer|null, ... },
  "evaluate": [ {"name": "...", "rule": <raw>, "viewer": "<viewer name>", "expect": true|false } ],
  "validate": [ {"name": "...", "rule": <raw>, "ok": true|false, "normalized"?: <rule> } ] }
```
Python test: `apps/api/src/tests/services/mka/test_audience_eval.py`. Web test: `apps/web/tests/mka-audience-eval.test.mjs` reading `../../api/src/tests/services/mka/vectors/audience_vectors.json`. Seed file committed by the coordinator; seam (a) may ADD cases (never change an existing expectation without coordinator sign-off); seam (b) must pass all.

### 1.4 Plain-English label — `describeRule(rule, options) -> string` (TS only, pure)
Examples (exact strings are tested): `{mode:show, groups:[{level:[local], department:[tabligh]}]}` ⇒ `"Local officeholders in Tabligh"`; `level:[local,regional]` ⇒ `"Local or Regional officeholders"`; `role:[regional_qaid]` ⇒ `"Regional Qaids"`; `{}` group ⇒ `"All officeholders"`; `officeholder:false` empty ⇒ `"Everyone signed in"`; hide mode ⇒ `"Everyone except " + <show phrase lower-first>`; region ⇒ `"… in the Northeast region"`; majlis ⇒ `"… in Albany"` / `"… in Albany or Boston"`; >3 values in one key ⇒ `"A, B and 3 more"`. Unknown values render as given with `(unknown)` suffix. Full grammar is owned by seam (c); its test file fixes the strings.

## 2. API (all routes added to the EXISTING fork router `routers/mka_attributes.py`; NO `router.py` edit)

Authz helper `_course_author_or_admin(request, user, org_id, course_uuid, db)` = superadmin OR org admin/maintainer in `org_id` OR (course belongs to `org_id` AND `ResourceAuthor` ACTIVE CREATOR/MAINTAINER/CONTRIBUTOR on course_uuid AND `authorization_verify_based_on_roles_and_authorship(request, uid, "update", course_uuid, db)` passes) — same approach as `compliance_scope._own_course_ids`. API tokens: rejected on all new routes except where noted.
All new tables: none planned. All queries org-scoped by `UserOrganization.org_id`.

| Route | Who | Request | Response |
|---|---|---|---|
| `GET /me?course_uuid=` (extend) | any signed-in | optional `course_uuid` | unchanged shape. `can_view_all` = existing rule OR (course_uuid given AND course exists AND user passes the author branch of `_course_author_or_admin` for that course's org). Unknown course_uuid ⇒ ignore (no 404, no leak). |
| `GET /options?org_id=` | any signed-in member of org_id (or superadmin) | — | `AudienceOptions` §2.1 |
| `POST /audience/count` | `_course_author_or_admin` | `{org_id:int, course_uuid?:str, rule:<raw>}` | `AudienceCount` §2.2; invalid rule ⇒ 422 `{detail}` |
| `GET /me/counterparts` | any signed-in | — | `Counterparts` §2.3, `Cache-Control: private, no-store` |
| `GET /preview-people?org_id=&q=` | org admin/maintainer or superadmin ONLY | q ≥ 2 chars | `{people:[{user_id, display_name, email}]}` max 20 (no attributes in list) |
| `POST /preview-people/{user_id}?org_id=` | same | — | `{attributes: PUBLIC_FIELDS dict}` via fail-closed reader; writes audit row `action='preview_as'`, actor=admin, reason="Preview as (audience block)". 404 if user not in org. |

### 2.1 `AudienceOptions`
```jsonc
{ "rules_version": "2026.1",
  "levels": [{"key":"national","label":"National"},{"key":"regional","label":"Regional"},{"key":"local","label":"Local"}],
  "departments": [{"key":"tabligh","name":"Tabligh","aka":[]}],          // from rules file, rules order
  "roles": [{"key":"qaid","title":"Qaid","plural":"Qaids"}],             // from role_titles; {department} titles rendered as e.g. "Nazim (department)"; plural from audience_config
  "regions": [{"name":"Northeast"}],                                     // canonical names
  "majlis": [{"name":"Albany","region":"Northeast"}],                     // from MAJLIS_TO_REGION
  "presets": [{"id":"local","label":"Local officeholders","rule":<Rule>,"needs_author_department"?:true}],
  "personas": [{"id":"local-nazim-tabligh-albany","label":"Local Nazim Tabligh · Albany","attributes":<PUBLIC_FIELDS>}],
  "copy": {"not_secret": "...", "unrecognized_note": "...", "empty_lesson": "...", "count_tooltip": "..."} }
```
Presets/personas/copy live in a new fork data file `apps/api/src/services/mka/audience_config.json` (versioned, reviewed). Presets (v1): Local officeholders `{level:[local]}`; Regional Qaids `{level:[regional], role:[regional_qaid]}`; National team `{level:[national]}`; Qaids & Naib Qaids `{role:[qaid,naib_qaid]}`; Motamids `{role:[motamid,regional_motamid]}`; My department `{department:[<author dept>]}` with `needs_author_department:true` (client fills from author's `/me`; hidden if author has no department). Personas (synthetic, no real people): Local Nazim Tabligh · Albany; Local Qaid · Houston; Regional Qaid · Northeast; Mohtamim Tabligh (National); Atfal Nazim · Syracuse-Binghamton; Unrecognized account (`status:"unrecognized"`, all null); Not an officeholder (`status:"not_applicable", is_officeholder:false`). Persona attributes MUST validate against the rules (test).
Server validates every preset rule with `validate_rule` at load (test).

### 2.2 `AudienceCount`
```jsonc
{ "count": 62,                         // org members whose EFFECTIVE (fail-closed reader) attributes match
  "total_officeholders": 640,          // members with is_officeholder === true
  "unrecognized": 3,                   // members whose status ∉ {matched,partial,not_applicable}
  "by_level": {"national": 0, "regional": 0, "local": 62},
  "expected": {"matching": 62, "total": 64, "cycle_id": 7} | null   // rule evaluated over mka_compliance_expected rows of the org's most recent cycle, using row fields as viewer {status:"matched", is_officeholder:true, level, department (''→null), majlis, region, role:null}; null if no cycle
}
```
Population = users with a `UserOrganization` row for `org_id`. Aggregates only, never names. Python evaluator (`services/mka/audience_eval.py`) is the only evaluator used.
Note: expected-roster rows have no `role` key; rules with a `role` key never match them ⇒ `expected.matching` undercounts role rules; acceptable, UI hides `expected` when the rule has a `role` key.

### 2.3 `Counterparts` (MailboxProvider v1, `services/mka/counterparts.py`, provider interface `CounterpartsProvider.for_viewer(attrs, rules) -> list`)
```jsonc
{ "counterparts": [ {"level":"national","role_title":"Mohtamim Tabligh","email":"tabligh@mkausa.org","name":null,"department":"tabligh"},
                    {"level":"regional","role_title":"Regional Qaid","email":"qaid.northeast@mkausa.org","name":null,"department":null},
                    {"level":"local","role_title":"Nazim Tabligh","email":"tabligh.albany@mkausa.org","name":null,"department":"tabligh"} ],
  "reason": null | "unrecognized" | "no_department" }
```
Rules: viewer via fail-closed reader; status ∉ {matched,partial} ⇒ `[]`, `reason:"unrecognized"`. Department null and role ∉ {qaid, naib_qaid, motamid} ⇒ `[]`, `reason:"no_department"`. National row = department's national mailbox on mkausa.org (Atfal: `atfal@mkausa.org`). Regional row = `qaid.{region slug}@mkausa.org` when region known. Local row = department local mailbox at viewer's Majlis (`{prefix}.{majlis slug}@domain`, Atfal on atfalusa.org `nazim.{slug}`) when majlis known and viewer level ≠ local-same-role. Omit any row whose email equals the viewer's own address. Mailbox/slug construction must reuse the parser's rules data (no hard-coded lists). Local executive (qaid/naib_qaid/motamid): regional qaid row only. Regional-department mailbox pattern is UNDECIDED by the org ⇒ not emitted.

## 3. Web

### 3.1 Files (all fork-only)
- `apps/web/components/mka/audience/evaluate.ts` — `validateRule`, `evaluateRule`, `effectiveViewer`, types re-exported. Pure, no React.
- `apps/web/components/mka/audience/types.ts` — `Rule, Group, MkaViewerAttributes, AudienceOptions, AudienceCount, Counterparts, Persona, Preset`.
- `apps/web/components/mka/audience/describe.ts` — `describeRule` (seam c).
- `apps/web/services/mka/attributes.ts` (+ `attributes.mock.ts`) — `useMkaViewer(courseUuid?)`, `useAudienceOptions(orgId)`, `fetchAudienceCount(auth, body)`, `useCounterparts()`, `searchPreviewPeople`, `fetchPreviewPerson`. Mock flag `NEXT_PUBLIC_MKA_AUDIENCE_MOCK==='1' && NODE_ENV!=='production'`. Query keys `['mka-attributes', ...]`. `useMkaViewer`: `staleTime: 5*60_000, refetchOnWindowFocus:false, retry:1`; returns `{state:'loading'|'ready'|'error', viewer: MkaViewerAttributes|null, canViewAll:boolean}`; on error `viewer:null, canViewAll:false`.
- `apps/web/components/mka/editor/index.ts` — `export function mkaEditorExtensions(opts:{editable:boolean, activity?:any}): AnyExtension[]` returning `[MkaAudience, MkaViewerField, MkaCounterparts, ...]`; importing it registers slash items (side effect, guarded so it registers once; hidden unless `NEXT_PUBLIC_MKA_AUDIENCE_ENABLED==='1'`… see §3.4).
- `apps/web/components/mka/editor/{AudienceNode.ts, AudienceView.tsx, ViewerField.ts(x), Counterparts.tsx, slash.tsx, store.ts}` (seam b) and `{AudiencePicker.tsx, AudienceBar.tsx, PreviewMenu.tsx}` (seam c).

### 3.2 Nodes
- `mkaAudience`: `group:'block'`, `content:'block+'`, `defining:true`, `isolating:true`, attrs `id` (string uuid, default null → assigned), `rule` (object; default `{"v":1,"mode":"show","groups":[{}]}`). renderHTML `['div', {'data-mka-audience':'', 'data-id':id, 'data-rule':JSON.stringify(rule)}, 0]`; parseHTML `div[data-mka-audience]` (JSON.parse in try/catch → invalid rule object kept as-is so it fails safe). Invariant: no nesting — an `appendTransaction` unwraps any `mkaAudience` inside another (keeps inner content). Invariant: unique ids — `appendTransaction` regenerates duplicates/nulls (B1.6). Commands: `setMkaAudience()` (wrap selection or insert empty with cursor inside), `updateMkaAudienceRule(id, rule)`, `unsetMkaAudience(id)` (unwrap). Shortcut `Mod-Alt-a` (editable only).
- `mkaViewerField`: inline atom, attrs `field: 'majlis'|'region'|'department'|'role_title'|'level'`, `fallback: string`. Input rule `{{my_majlis}}` etc. Learner sees value (department rendered by name via options) or fallback; author sees chip `‹Majlis›`; under Preview-as shows persona value.
- `mkaCounterparts`: block atom, no attrs beyond `id`. Learner: card from `useCounterparts()`; author: static sample card "Counterparts (filled per viewer)"; under Preview-as: computed client-side is NOT possible without API → shows "Preview shows sample counterparts" placeholder.

### 3.3 Viewing modes (per editor instance) — `store.ts`
`getAudienceStore(editor)` → tiny external store `{get(), set(partial), subscribe(fn)}` held in `editor.storage.mkaAudience`. State: `{ view: {kind:'author'} | {kind:'self'} | {kind:'persona', label:string, attributes:MkaViewerAttributes|null}, collapsed: Record<id, true> }`.
Resolution of what an audience section does:
- Editable editor (authoring) or `canViewAll` viewer with `view.kind==='author'`: render everything, with header chrome "Visible to: <label>" (author header for editable; read-only badge for viewer).
- Otherwise evaluate with viewer = (`persona` ? persona.attributes : `/me` attributes). Match ⇒ content, no chrome for learners (thin label in preview mode). No match ⇒ learners: nothing (content NOT in document DOM; zero height); authors in preview: dashed placeholder "Hidden for this viewer · Visible to <label>".
- While `/me` loading (non-author view): sections render nothing (no flash).
Learner notes (once per activity, top of doc, via plugin view or widget): unrecognized note when viewer status ∉ {matched, partial, not_applicable} AND ≥1 section evaluated hidden; empty-lesson note when every top-level node is a hidden audience section (or empty paragraphs).

### 3.4 Feature flag
`NEXT_PUBLIC_MKA_AUDIENCE_ENABLED==='1'` gates ONLY authoring entry points (slash items, shortcut, bar). Nodes are always registered and always evaluated (content must never go blank / hidden content must never show because the flag is off).

### 3.5 Component props (seam c builds; seam b mounts)
```ts
<AudiencePicker
  value: Rule                       // normalized
  onChange(rule: Rule): void        // live
  onDone(): void; onCancel(): void; onRemove?(): void
  options: AudienceOptions | undefined   // loading state when undefined
  authorDepartment: string | null   // for "My department" preset
  count: {state:'idle'|'loading'|'error'|'ready', data?: AudienceCount}
  isNew: boolean                    // shows quick picks first
/>
<AudienceHeader  rule label count onEdit onPreview onToggleCollapse collapsed blockCount warnings /> // header chrome inside node view
<AudienceBar  sectionCount view onChangeView(view) personas canPickPerson searchPeople(q) pickPerson(id) options />
```
`useAudienceCount(orgId, courseUuid, rule)` lives in `services/mka/attributes.ts`: 400 ms debounce, cached by stable JSON hash, TanStack Query.

## 4. Fork footprint (only these upstream edits allowed)
W1/W2/W3: one import line + one spread line each, both suffixed `// MKA fork`. Log each exact diff in `.codebase-memory/upstream-modifications.md`. Nothing else upstream. `apps/web/tests/mka-editor-hooks.test.mjs` = hook guard (spec B6): scans `apps/web/components` and `apps/web/app` for `useEditor(` / `new Editor(` / `extensions: [`; every site not in the allow-list (`components/Objects/Communities/DiscussionEditor.tsx`, `DiscussionContent.tsx`, `components/Dashboard/Boards/BoardCanvas.tsx`, files under `components/mka/`) must contain `mkaEditorExtensions(`; also asserts W1–W3 contain it. Each hook call guarded so a throw inside fork code cannot blank the editor (mkaEditorExtensions wraps creation in try/catch returning the nodes with no plugins at worst — nodes MUST still be registered).

## 5. Tests & gates (per seam)
API: `cd apps/api && uv run --with greenlet python -m pytest src/tests/services/mka src/tests/routers -q -k mka`; `uvx ruff@0.15.9 check ./apps/api`. Contract fixtures: `test_mka_audience_contract_dump.py` → `apps/web/tests/fixtures/mka-audience/*.json` ({path,status,body}); web `mka-audience-contract.test.mjs` validates shapes (copy the mini shape checker from `mka-compliance-contract.test.mjs`). Authz matrix (learner/author-other-course/author/maintainer/admin/other-org admin/superadmin/API token) and cross-org tests for every new route.
Web: `cd apps/web && bun test tests`, `bunx tsc --noEmit` (baseline png/svg module errors only), eslint on fork files, `bun run build` with mocks off.
