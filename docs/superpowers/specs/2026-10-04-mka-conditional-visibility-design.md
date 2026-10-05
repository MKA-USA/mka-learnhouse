# MKA Identity Attributes + Conditional-Visibility Block — Design Spec

- **Date:** 2026-10-04
- **Status:** Draft for review (design only; nothing implemented)
- **Scope:** Feature A (server-derived "MKA identity attributes" on every user) and Feature B (audience-targeted content block for course authors), both fork-side.
- **Base:** `origin/dev` @ `38bf3c6e` (has the MKA profile-fields feature; the local `dev` checkout is behind it).
- **Evidence convention:** each code claim cites a file and symbol that was read for this spec. Claims marked **UNVERIFIED** were not confirmed in code.

---

## 0. Job to be done

> **When** I'm a Mohtamim writing this year's Tabligh compliance course for ~60 local Nazims, 10 Regional Qaids and the national team, **I want to** write the lesson once and mark which paragraphs apply to which level and Majlis, **so I can** give each officeholder exactly their instructions, contacts and deadlines without maintaining three copies of the course.

> **When** I'm a local officeholder doing my annual training in November, **I want to** see only what applies to me, with my own Majlis, Region and counterparts filled in, **so I can** finish quickly and know who to call.

Today the workaround is either one long generic lesson ("if you are a Regional Qaid, skip to…") or several copies of the course. Both cost time every year and the copies drift apart. The feature has to beat "one lesson with headings per role" in authoring effort. If it doesn't, authors will go back to headings.

---

## 1. Summary of the design

1. **Attributes (A).** A pure, table-driven parser maps a *Google-verified* email to `{is_officeholder, level, department, role, majlis, region, status}`. It runs at every Google sign-in and on admin bulk recompute. Results go in a new fork-only table `mka_user_attributes` with an admin override layer and an append-only audit table. One upstream hook sits in the session chokepoint.
2. **Audience block (B).** A TipTap node `mkaAudience` wraps any block content and carries a versioned JSON rule. Authors build the rule in a plain-language picker: "Show to **[Local ▾]** officeholders in **[Tabligh ▾]**". Within a field, choices are OR'd. Across fields they are AND'd. One "Show to / Hide from" switch adds NOT. The block shows a live "≈N people" count, a "Preview as…" bar, and inline viewer fields (`my_majlis`, …). A "My counterparts" card is included.
3. **Evaluation.** One pure evaluator, written in TypeScript (client) and Python (server-side audience counts) and kept identical by a shared JSON test-vector file. **v1 filters on the client, and this is a presentation feature, not access control.** The code shows that a server filter would need ≥4 upstream hooks and would still leak (§B4).
4. **Completion.** Targeting is block-level only. Upstream activity locks are *not* used for targeting, because locked activities still count toward course completion (§B5).
5. **Fork footprint.** 3 web files each get an import plus one spread line. 2 API files get one-line hooks (one of them already carries an MKA hook). Slash-menu registration is a side effect from fork code, so that config file is not touched.

---

## Feature A — MKA identity attributes

### A1. Why a new table (not `mka_user_profile`)

`apps/api/src/db/mka_user_profile.py::MkaUserProfile` (origin/dev) stores **self-reported** data: `majlis` and `region` are required, and the user can edit them via `PUT /mka/profile/me` (`apps/api/src/routers/mka_profile.py::api_put_me`). Identity attributes are **server-derived and not user-editable**. They differ from the profile in four ways:

| Concern | `mka_user_profile` | `mka_user_attributes` (new) |
|---|---|---|
| Source | User at signup / profile gate | Verified Google email + admin override |
| Writable by user | Yes | **Never** |
| Nullability | majlis/region NOT NULL | Most fields nullable (non-officeholders) |
| Lifecycle | Per person | Per **account**. Role mailboxes pass to the next officeholder (§Risks) |

Putting both in one table would mix trust levels in one row and break the NOT NULL invariants. A separate table also lets an admin report flag **mismatches**, for example a `tabligh.albany@` account whose self-reported Majlis is "Boston".

### A2. Schema (fork-only migration `apps/api/migrations/versions/mka_2026xxxx_user_attributes.py`, idempotent like `mka_20261004_user_profile.py`)

```text
mka_user_attributes
  user_id            int PK, FK user.id ON DELETE CASCADE
  email_seen         text       -- lower-cased email the derivation used
  derived            jsonb      -- parser output (see A3), never edited by hand
  rules_version      text       -- e.g. "2026.1"; recompute when it changes
  derived_at         timestamptz
  override           jsonb NULL -- partial: any subset of attribute fields
  override_reason    text NULL
  override_by        int NULL FK user.id
  override_at        timestamptz NULL
  -- effective = derived ⊕ override  (computed in service, not stored)
  INDEX on ((derived->>'status')), ((derived->>'level')), ((derived->>'department'))

mka_user_attributes_audit   (append-only)
  id, user_id, actor_user_id NULL (NULL = system), action
  ('derive'|'recompute'|'override_set'|'override_clear'|'roster_apply'),
  before jsonb, after jsonb, reason text, at timestamptz

mka_roster_override         (optional; pre-seedable before the user exists)
  email (lower, PK), attributes jsonb, source text ('admin'|'companion'),
  note text, updated_at, updated_by
```

Precedence: **admin override (per user) > roster override (per email) > parser**. A roster row covers people the parser cannot classify, such as personal-name national officers (`mahmood.kauser@`, `ibrahim.chaudhry@` as Naib Sadr) and personal-address exceptions.

### A3. Attribute model

```ts
type MkaAttributes = {
  status: 'matched' | 'partial' | 'ambiguous' | 'unrecognized' | 'not_applicable'
  is_officeholder: boolean | null      // null = unknown
  level: 'national' | 'regional' | 'local' | null
  department: DeptKey | null           // canonical key, e.g. 'tabligh'; null for executive roles
  role: RoleKey | null                 // e.g. 'nazim_dept','qaid','naib_qaid','motamid','regional_qaid','mohtamim','sadr','naib_sadr','nazim_atfal','murabbi_atfal'
  role_title: string | null            // display, e.g. "Nazim Tabligh", "Regional Qaid"
  majlis: string | null                // canonical name from MAJLIS_TO_REGION
  region: string | null                // canonical region name
  source: 'parser' | 'roster' | 'admin'
}
```

- `not_applicable`: the domain is not in the officeholder domain list (personal Gmail etc.). `is_officeholder = false`.
- `unrecognized`: the domain is an officeholder domain but the local part matches no rule. `is_officeholder = null`, and admins see it in the "Needs review" queue.
- `partial`: the role is known but the Majlis slug is unknown (for example a new Majlis). `department`/`role` are kept, `majlis`/`region` are null, and the account is flagged.
- `ambiguous`: the slug matches both a region and a Majlis (§A4). Level is null and the account is flagged. **The parser never guesses.**

**Role titles and the executive-vs-department split are UNVERIFIED org facts.** The titles above (Nazim {Dept} locally, Mohtamim {Dept} nationally, Regional Qaid) live in config, not code, so the organisation can correct them without a deploy.

### A4. Parser: pure, table-driven

`apps/api/src/services/mka/identity_parser.py` exposes `parse_identity(email: str, rules: IdentityRules) -> MkaAttributes`. It does no I/O and never raises: any exception becomes `status='unrecognized'`.

**Rules live in a versioned data file**, `apps/api/src/services/mka/identity_rules/2026.1.json`. It is fork-only, code-reviewed and loaded once. A file version is preferred over a DB-editable table for v1 because every change gets review and runs through the test matrix. A DB-editable layer can come later; see Decision D2. Contents:

```jsonc
{
  "version": "2026.1",
  "officeholder_domains": ["mkausa.org", "atfalusa.org"],
  "departments": [            // canonical list; NOT derived from mailbox names
    {"key":"aitmad","name":"Aitmad","aka":["General Secretary"],"national_mailbox":"motamid","local_prefix":"motamid","local_role":"motamid"},
    {"key":"tabligh","name":"Tabligh","national_mailbox":"tabligh","local_prefix":"tabligh"},
    {"key":"atfal","name":"Atfal","national_mailbox":"atfal","local":{"domain":"atfalusa.org","prefixes":{"nazim":"nazim_atfal","murabbi":"murabbi_atfal"}}},
    {"key":"nau_mubaeen","name":"Nau Mubaeen","national_mailbox":"nau-mubaeen","local_prefix":"nau-mubaeen","legacy_local_prefixes":[]},
    {"key":"rishta_nata","name":"Rishta Nata","national_mailbox":"rishtanata","local_prefix":"rishtanata"},
    {"key":"new_immigrants","name":"New Immigrants","national_mailbox":"immigrants","local_prefix":"immigrants"}
    /* … Amoomi, Amoor-e-Tuluba, Ishaat, Khidmat-e-Khalq, Maal, Mohasib, Sanat-o-Tijarat,
         Sehat-e-Jismani, Tahrik-e-Jadid, Tajneed, Taleem, Tarbiyyat, Waqar-e-Amal, Waqf-e-Nau, Wasiyyat */
  ],
  "executive_local_prefixes": {"qaid":"qaid","naibqaid":"naib_qaid"},
  "national_exact": {"sadr":"sadr","muqami":"…","legal":null,"events":null,"it":null,"media":null,"expense":null},
  "regions": {"east":"East","greatlakes":"Great Lakes","gulf":"Gulf","midwest":"Midwest","newyorkmetro":"New York Metro",
              "northeast":"Northeast","northwest":"Northwest","southeast":"Southeast","southwest":"Southwest","virginia":"Virginia"},
  "majlis_slug_aliases": {"syracuse":"Syracuse-Binghamton","newyorkmetro-region":"?? (ERROR, removed 2026-10-05)","rtp":"RTP"},
  "slug_overrides_by_domain": {"atfalusa.org": {"syracuse": "Syracuse-Binghamton"}}
}
```

Majlis slugs are generated from `MAJLIS_TO_REGION` (origin/dev `apps/api/src/services/users/mka_profile.py`), which stays the single source of the Majlis→Region mapping: lowercase, spaces removed, hyphens kept. The alias table adds the exceptions on top.

**Data quirks to address explicitly:**
- The source department-mailbox sheet has the **Atfal/Amoor-e-Tuluba email columns swapped**. The rules file is written from the corrected mapping and has a test row for each.
- `rishtanata.{majlis}` is sometimes used for Nau Mubaeen. Parse it as Rishta Nata. Real exceptions go through roster or admin override, and the parser does not special-case them.
- **[RESOLVED 2026-10-05: `newyorkmetro-region` was an ERROR; `newyorkmetro.region@mkausa.org` is the New York Metro Regional Qaid mailbox (rules 2026.3, `regional_mailbox_aliases`). Original note follows.]** `newyorkmetro-region` was UNVERIFIED. It does not match any Majlis in `MAJLIS_TO_REGION` (origin/dev lists Bronx, Brooklyn, Long Island and Queens under New York Metro). Its alias target is left as `??` until confirmed. Until then the parser returns `partial`.
- `muqami@` (national) vs the Majlis "Muqami" (region "Muqami" in `MAJLIS_TO_REGION`) needs a ruling. Default: `muqami@` is national/executive.

**Algorithm (precedence order, first match wins):**
1. Normalise to lowercase and trim. Malformed address → `unrecognized`.
2. Domain not in `officeholder_domains` → `not_applicable`.
3. Domain `atfalusa.org`: `{nazim|murabbi}.{slug}` → local Atfal role; resolve the slug via domain overrides, then aliases, then generated slugs.
4. No dot in the local part → national exact table (`sadr`, `motamid`→Aitmad, department mailboxes →`mohtamim` of that department, `legal`/`it`/… → national, `department=null`, `role='national_staff'`).
5. `qaid.{slug}`: slug ∈ regions **and** ∈ majlis slugs → `ambiguous`; ∈ regions only → `regional_qaid`; ∈ majlis only → local `qaid`; neither → `partial`.
6. `{prefix}.{slug}` where prefix is a local department prefix or an executive prefix → local role. Slug unknown → `partial`.
7. A two-part personal name such as `first.last` → `unrecognized`. Roster or admin override fills these in (national personal-name officers).
8. Anything else → `unrecognized`.

Step 7 conflicts with step 6 only when a person's first name equals a department prefix. That is unlikely and is covered by a test row.

**Anti-collision rule:** the region-vs-majlis check in step 5 runs at **load time** too. If a rules file would make any `qaid.x` ambiguous, loading logs a warning, and a unit test fails so the conflict is reviewed.

### A5. When attributes are computed (idempotent)

| Trigger | Mechanism |
|---|---|
| Every Google sign-in (first and later) | Hook in `issue_session_or_challenge` (origin/dev `apps/api/src/services/auth/session.py`), only when `amr == AUTH_METHOD_GOOGLE`. It calls `mka_refresh_on_login(db_session, user)` from the fork module. **It never breaks login:** the call is wrapped in try/except, logs on failure, and may run asynchronously after commit. |
| Rules version bump | Lazy: if `rules_version` differs at next login or read, recompute. Eager: admin "Recompute all". |
| Admin bulk recompute | `POST /mka/attributes/recompute` (all users, or a filter) runs as a background task and writes audit rows only when the derived value changes. |
| Backfill of existing users | A one-shot CLI or admin action runs the same recompute over all users whose `signup_method == 'google'` (see A7 for the reason behind that filter). |

Recomputing is a pure function of `(email, rules)`, so running it twice gives the same result. An upsert only writes when `derived` changed. Overrides are never touched by recompute.

### A6. Anti-spoofing

- Derivation only uses an email that Google has verified. `signWithGoogle` (origin/dev `apps/api/src/services/auth/utils.py`) rejects unverified emails and lower-cases the address. For `MKA_GOOGLE_ONLY_DOMAINS` domains, `require_workspace_hd` also requires the Workspace `hd` claim, and `block_non_google_auth` blocks password, magic-link and signup paths (`mka_google_only.py`).
- **Required config change:** add `atfalusa.org` to `MKA_GOOGLE_ONLY_DOMAINS`. Otherwise someone could create a password account as `nazim.albany@atfalusa.org` and pick up officeholder attributes. As a second check, the hook derives only on `amr == google`. A non-Google account with an officeholder-looking address gets `not_applicable` until an admin intervenes.
- No API accepts attribute writes from the user. Admin endpoints require org admin (`is_org_admin`, `apps/api/src/security/org_auth.py`).
- Email changes into or out of the domain are already blocked by `block_email_change`.

### A7. API (fork router `apps/api/src/routers/mka_attributes.py`, mounted at `/mka/attributes`)

| Method/Path | Who | Returns |
|---|---|---|
| `GET /mka/attributes/me?course_uuid=` | any signed-in user | `{attributes (effective, minus source/override metadata), can_view_all: bool, rules_version}`. `can_view_all` = org admin, or course author/maintainer (**UNVERIFIED** symbol for the course-contributor check; there is a `check_resource_access(..., AccessAction.UPDATE)` pattern in course services) |
| `GET /mka/attributes/me/counterparts` | signed-in | §B1.8 |
| `POST /mka/attributes/audience/count` | course authors/admins | `{count, total_officeholders, unrecognized, by_level:{…}}` for a rule; server Python evaluator |
| `GET /mka/attributes/users?status=&level=&department=&q=&page=` | org admin | effective + derived + override, paginated |
| `PUT /mka/attributes/users/{user_id}/override` | org admin | body `{override:{…}, reason (required)}` → audit row |
| `DELETE /mka/attributes/users/{user_id}/override` | org admin | audit row |
| `PUT/DELETE /mka/attributes/roster/{email}` | org admin / companion API token | roster override; audit row |
| `POST /mka/attributes/recompute` | org admin | background job id |
| `GET /mka/attributes/personas` | authors | curated preview personas (§B1.6) |

These routes mount with `dependencies=[Depends(get_non_api_token_user)]`, like `mka_profile`. The roster write is the exception: it accepts the companion service's API token. **UNVERIFIED** how API-token auth composes per-route; follow the existing upstream pattern for API-token routers.

**Admin UI:** extend the existing fork-only `components/mka/MkaProfileEditDialog.tsx`, which already opens from the MKA hook in `OrgUsers.tsx` on origin/dev, with an "Identity" tab showing derived vs effective values, an override form with a required reason, and audit history. Add a fork-only page `app/orgs/[orgslug]/dash/mka/identities/page.tsx` for the "Needs review" queue (status ∈ unrecognized/ambiguous/partial/mismatch) and for bulk recompute. A new route directory is not an upstream edit. It is linked from the dialog.

### A8. How attributes reach the web app

**Decision: an endpoint plus SWR, not JWT claims.** Reasons:
- Claims would need a change to upstream `mint_session_tokens`/`session_claims` (more upstream surface).
- Claims go stale until the token refreshes, so an admin override would not take effect promptly.
- Claims add PII to every request.

The web side uses `useMkaViewer(courseUuid)`, which is SWR on `/mka/attributes/me` with `dedupingInterval: 5 min` and `revalidateOnFocus: false`. The endpoint sends `Cache-Control: private, no-store`. The Next.js server never fetches it with the shared data cache, so attributes cannot leak across users through caching.

### A9. Privacy

- The stored fields are org-role metadata derived from the user's own work email. They are low-sensitivity, but still PII when combined with a name.
- "Not shown to the user" means: the attributes are not shown on profile or settings screens. The user's own values *are* visible in two places: the `/me` response, and any inline field an author deliberately places (`{{my_majlis}}`). This is intended; see Decision D4.
- GDPR: the existing fork functions `profile_status`/`delete_profile` (origin/dev `services/users/mka_profile.py`) are already called from upstream `export_user_data`/`anonymize_user` (`services/admin/admin.py`). Extend those **fork** functions to include or delete attributes, audit rows (anonymise the actor) and roster rows. **No new upstream hook.**
- Audience counts return aggregates only. Authors never see who matched, only how many. Naming individual users in "Preview as a person" is limited to org admins.

---

## Feature B — Conditional-visibility ("Audience") block

### B1. Authoring UX

Design principles: plain language, no boolean jargon, the audience always visible, and an answer to "who sees this?" before publishing.

#### B1.1 Insert

- **Slash menu:** `/audience`, `/show only to`, `/role` → item "Audience section: show this only to certain officeholders" in category `interactive`. Registration is a module side effect, `slashCommands.push(...)` on the array exported from `Extensions/SlashCommands/index.ts`. That works because `filterCommands` reads the module-level `slashCommands` array (`slashCommandsConfig.tsx`, `SlashCommands.ts:50`). **No edit to the upstream slash config.**
- **Wrap the selection:** with blocks selected, `Mod-Alt-A` (defined in the extension's `addKeyboardShortcuts`) or slash wraps them. With nothing selected it inserts an empty section with the cursor inside.
- **Inline fields:** slash "Viewer's Majlis / Region / Department / Role", or type `{{my_majlis}}` (input rule converts it to a chip).
- **Counterparts card:** slash "My counterparts".

On insert the picker opens immediately (the empty state):

```
┌─ Audience section ──────────────────────────────────────────────────┐
│  Who should see this?                                               │
│                                                                     │
│  Quick picks:  [Local officeholders] [Regional Qaids]               │
│                [National team] [Qaids & Naib Qaids] [My department] │
│                                                                     │
│  Or build it:  Show to [Any level ▾] officeholders in [Any dept ▾]  │
│                                                       [More ▾]      │
│                                              [Cancel]  [Done]       │
└─────────────────────────────────────────────────────────────────────┘
```

#### B1.2 The audience picker (one sentence, chips)

```
 ( Show to ● | Hide from ○ )
 ┌───────────────────────────────────────────────────────────────────┐
 │ Show this to  [Local ×] [Regional ×] [+]  officeholders           │
 │ in            [Tabligh ×] [+]                                     │
 │ with role     [Any role ▾]                         (More ▾ shows)  │
 │ in region     [Any region ▾]                       (More ▾ shows)  │
 │ in Majlis     [Any Majlis ▾]                       (More ▾ shows)  │
 │                                                                    │
 │ Reads as: "Local or Regional officeholders in Tabligh"             │
 │ ≈ 71 people see this · 3 unrecognized accounts excluded  (i)       │
 │                                            [Preview as…]  [Done]   │
 └───────────────────────────────────────────────────────────────────┘
```

**Logic model (decided): within a row, OR. Across rows, AND. One whole-rule switch for "Hide from" (NOT).**
- This is the simplest model that covers the real cases: "Local Tabligh" (AND), "Local or Regional" (OR within a field), "Regional Qaids" (level + role), "Everyone except National" (Hide from), "Northeast Majlis Qaids" (region + role).
- Non-technical people already know it from "filter" UIs (Gmail, airline search). Chips in one row read as "or", and rows read as "and". The live **"Reads as"** sentence shows the result in plain English.
- What it cannot express is a union of different shapes, for example "(Local Tabligh) OR (Regional Qaids)". Authors handle that with two sections. The schema already allows multiple groups (B3), so a later "+ Or also show to…" can be added without migrating content. **v1 UI exposes one group.**
- There is no per-row NOT. Mixed include/exclude per field is the usual source of mistakes in rule builders.

**Presets** come from config and are named in the org's vocabulary: Local officeholders, Regional Qaids, National team, Qaids & Naib Qaids, Motamids, **My department**. "My department" is resolved at insert time from the *author's* attributes and is then stored as a concrete department, so the rule stays stable if the author's role changes. Presets fill the picker. They are not stored as a separate preset ID; the stored value is always the expanded rule.

Field pickers use `cmdk` (`components/ui/command.tsx` from the profile PR on origin/dev) with search. The Majlis picker groups by Region and has a "Select whole region" shortcut that converts to the region row.

#### B1.3 In-editor visual treatment

```
 ▌ 👁 Visible to: Local officeholders · Tabligh      ≈62   [Edit] [Preview] [⌄]
 ▌ ─────────────────────────────────────────────────────────────────────────
 ▌  As a local Nazim Tabligh in {my_majlis}, submit your monthly report to …
 ▌  …
```
(The eye glyph is a lucide `Eye` icon. Emoji are not used in the UI.)

- A 4px left colour bar with a header label. Colour comes from level: national violet, regional blue, local green, mixed or other slate, and "Hide from" gets a hatched bar. **Colour is never the only signal**, because the label text is always present.
- Collapsed state (`⌄`) shows only the header line plus "4 blocks hidden". Collapse is an editor-local view setting and is not saved to content.
- Warnings appear in the header:
  - **Zero audience** (count = 0): amber "Nobody currently matches this. Check the filters." For a rule matching only `ambiguous`/`unrecognized` users: "Only accounts we couldn't classify."
  - **Coverage hint** (P2) for 2+ adjacent sections: "These 3 sections cover 94% of officeholders. 12 Regional Qaids see none of them. [Add a section for them]".
  - **Overlap hint** (P2): adjacent sections whose audiences intersect: "18 people will see both."
  - **Nesting:** audience sections may not nest. The schema disallows it (`content` excludes `mkaAudience`), which avoids AND-of-nested confusion. Paste-into-section unwraps nested sections and shows a toast.
- **Count data source:** `POST /mka/attributes/audience/count`, debounced 400 ms and cached per rule hash. It counts **effective attributes of org members who have signed in at least once or were backfilled/rostered.** The tooltip says this. If the companion service later registers an expected roster size, show "≈62 of 64 expected".

#### B1.4 Preview as…

An **Audience bar** appears at the top of the editor (and for admins/authors on the learner page) only when the document contains at least one audience section. It is implemented as a ProseMirror plugin `view()` owned by the extension, so **no upstream layout hook is needed**.

```
 ┌ Viewing: [Everything (author view) ▾]   5 audience sections ─────────┐
 └──────────────────────────────────────────────────────────────────────┘
   ▾ Everything (author view)
     Personas:  Local Nazim Tabligh · Albany
                Local Qaid · Houston
                Regional Qaid · Northeast
                Mohtamim Tabligh (National)
                Atfal Nazim · Syracuse-Binghamton
                Unrecognized account
                Not an officeholder
     A specific person… (admins only, search)  → uses their effective attributes
     Custom…  (level/department/role/Majlis pickers)
```

Under a persona the editor shows exactly what that viewer sees. Non-matching sections collapse to a thin dashed placeholder, "Hidden for this viewer: Visible to Regional Qaids", so the author keeps their place. Inline fields fill with the persona's values. A clear "Exit preview" chip prevents authors forgetting they are previewing. Previewing a specific person writes an audit row.

#### B1.5 Errors and edge states

- Counts endpoint fails → header shows "Count unavailable" and authoring continues.
- Rule references a value not in the current rules (for example a renamed department) → red chip "Unknown: 'Rishta Nata (old)'". The evaluator treats it as non-matching, and the editor offers "Replace with…".
- Rule schema newer than the client (`v` > supported) → the section renders read-only for authors, with "Made with a newer editor". Learners get *hidden*, which is fail-safe.

#### B1.6 Copy, paste, duplicate

- The node has an `id` attribute (uuid). An `appendTransaction` plugin regenerates duplicate ids after paste or duplicate, and the rule is copied with the content.
- Pasting into a non-MKA editor is not possible inside this app because all instances register the node (B6). Cross-instance export is covered in B6.
- Plain-text copy by a learner only includes visible sections, since hidden ones are not in the DOM.

#### B1.7 Keyboard, accessibility, mobile

- Header actions are real buttons. Picker: `Tab` moves through rows, `Enter` opens a select, `Backspace` on a focused chip removes it, `Esc` closes.
- The node view is `role="region"` with `aria-label="Section visible to Local officeholders in Tabligh"`. The count is announced politely via `aria-live`.
- Under 640px the picker opens as a bottom sheet (Radix Popover → full-width sheet), chips wrap, and the header label truncates with the full label in a tooltip or long-press.
- Target sizes are at least 44px. Contrast follows AA for all bars and labels in both themes.

#### B1.8 Inline fields and "My counterparts"

- `mkaViewerField` is an inline atom with attrs `{field: 'majlis'|'region'|'department'|'role_title'|'level', fallback: 'your Majlis'}`. Learners see the value, or the fallback text when it is null. Authors see a chip `‹Majlis›`.
- `mkaCounterparts` is a block node. Data comes from `GET /mka/attributes/me/counterparts`, which uses a pluggable `CounterpartsProvider`:
  - **v1 `MailboxProvider`** needs no roster, because role mailboxes are deterministic. For a viewer in department D at Majlis M, Region R it returns: National: Mohtamim D (`{national_mailbox}@mkausa.org`); Regional: Regional Qaid R (`qaid.{region}@`); Local: Nazim D, M (`{prefix}.{slug}@`). The viewer's own row is omitted.
  - **v2 `RosterProvider`** (companion service): same shape plus names and phone numbers. It is behind an interface, and its feed and schema are out of scope.
  - The card shows a role title, a mailto link and an optional name. Viewers with no department get "Counterparts appear once your role is recognized."

### B2. Viewer behaviour

- **Matching** sections render their content with no chrome (no badge for learners). **Non-matching** sections render `null`: no placeholder and no gap.
- **No flash of hidden content:** `DynamicCanva` uses `immediatelyRender: false` (verified in `components/Objects/Activities/DynamicCanva/DynamicCanva.tsx`), so content is client-rendered anyway. While `useMkaViewer` is loading, audience sections render nothing (a zero-height skeleton line). The extension's `onCreate` prefetches the SWR key, so the fetch starts as soon as the editor mounts.
- **Unrecognized or unknown viewers:** a positive condition never matches a null attribute. In "Hide from" sections a null attribute is treated as not excluded, so the section shows. Net effect: these users see untargeted content and "everyone except…" content. If an activity contains audience sections that are hidden *because* the viewer is unrecognized, a single unobtrusive note appears: "Parts of this lesson are tailored by role. We couldn't recognise your role from your sign-in. Contact your administrator." It is shown once per activity, and its copy is in config.
- **Empty lesson:** if evaluation hides *all* top-level content, show "Nothing in this lesson applies to your role. You can mark it complete and continue." (computed by the plugin over the doc).
- **Admins and authors** (`can_view_all`) see all sections with the header badge "Visible to: …" and the Audience bar defaulting to "Everything". One click switches to "As me", or to a persona.
- **Print:** browser print of the DOM, so learners print what they see. The author-view print stylesheet keeps the "Visible to" labels.
- **Search:** upstream search does not index activity content (`services/search/search.py` covers course metadata via `search_courses` and Discussions), so there is no leak or effect.
- **AI features:** `AICanvaToolkit` acts on the rendered selection, so only visible text is involved. **Course RAG does leak:** `services/ai/rag/content_extraction.py::_walk_prosemirror_node` falls through to "Default: recurse into children" for unknown node types, so text from every audience section is indexed course-wide, and AI chat may quote another audience's instructions. Mitigations: given low sensitivity, accept for v1 and turn off course AI chat on compliance courses if confusing. Optionally add a one-line hook later to annotate audience text (B6, optional hook O3).
- **Embeds:** `app/embed/.../EmbedActivityClient.tsx` renders `DynamicCanva`, so behaviour is the same. Anonymous embed viewers are treated as not officeholders.

### B3. Rule schema (versioned, in node attrs)

```jsonc
// node: { "type": "mkaAudience", "attrs": { "id": "uuid", "rule": <Rule> }, "content": [ block+ ] }
{
  "v": 1,
  "mode": "show",                       // "show" | "hide"
  "groups": [                           // OR across groups (UI v1: exactly 1)
    {                                   // AND across present keys; OR within a key's array
      "officeholder": true,             // optional; default true (officeholders only). false = "anyone signed in"
      "level":      ["local","regional"],
      "department": ["tabligh"],
      "role":       ["qaid","naib_qaid"],
      "region":     ["Northeast"],
      "majlis":     ["Albany"]
    }
  ],
  "label": "Local or Regional officeholders in Tabligh"   // cached display; never used for evaluation
}
```

**Evaluator contract (pure):**
```ts
evaluate(rule: Rule, viewer: MkaAttributes | null, opts: {knownRuleVersion: 1}): boolean
```
- `rule.v > 1` → `false` (fail-safe hide).
- `viewer === null` (anonymous or failed to load) → treat every attribute as null.
- `groupMatches(g)`: for each present key, `viewer[key] != null && g[key].includes(viewer[key])`. Empty arrays are invalid; the editor normalises them by removing the key. `officeholder: true` requires `viewer.is_officeholder === true`.
- `anyGroup = groups.some(groupMatches)`. `show` → `anyGroup`. `hide` → `!anyGroup`. In hide mode a null attribute makes the group not match, so the section is shown, as defined in B2.
- **Extensibility:** a new attribute is a new optional key. Older evaluators that meet an unknown key in a group treat the group as **non-matching** (fail-safe), and the rule does not need to bump `v`. A semantics change bumps `v`.

**One evaluator, two languages:** `apps/web/components/mka/audience/evaluate.ts` and `apps/api/src/services/mka/audience_eval.py`. Both are tested against `apps/api/src/tests/mka/audience_vectors.json`, roughly 60 cases of `{rule, viewer, expected}`. The web test reads the same file by relative path. Python is used only for counts, never for content gating in v1.

### B4. Where to evaluate, and what that means for confidentiality

Evidence on how content is served:
- The learner page `app/orgs/[orgslug]/(withmenu)/course/[courseuuid]/activity/[activityid]/page.tsx` fetches `getActivityWithAuthHeader` (`services/courses/activities.ts`) → `GET activities/activity_{uuid}` → `services/courses/activities/activities.py::get_activity`, which returns **the whole `content` document**. It is already adjusted per user (`paid_access`, and `_apply_activity_lock` scrubbing). That precedent shows a per-user server filter is feasible with one line after `_apply_activity_lock`.
- But the same content is also returned by:
  - non-slim course metadata: `services/courses/chapters.py` puts `"content": activity.content` into the activities map,
  - `GET /{activity_uuid}/versions` and `/versions/{n}`, which `services/courses/activities/versioning.py` checks only at **`AccessAction.READ`**, so a learner can read historical full content,
  - `editor-bootstrap`,
  - course export (`transfer/export_service.py` deep-copies content).
- A real server-side boundary would therefore need hooks in at least `get_activity`, chapters/course-meta, both version endpoints and RAG, and future upstream endpoints could bypass it silently.

**Recommendation:** filter on the client in v1, and **state clearly that the audience block is a presentation tool, not access control.** The content in scope (role instructions, role mailboxes, deadlines) is low-sensitivity and organisation-internal; every learner is a vetted officeholder. The block's help text says: *"Don't put confidential information in an audience section. Anyone enrolled can technically access it. For confidential material use a separate course restricted by user group."* That alternative already exists upstream through `lock_type='restricted'` plus usergroups (`_apply_activity_lock`).

**Optional Phase 3 (only if needed):** a fork function `mka_strip_audience(content, viewer)` hooked into `get_activity` (one line after `_apply_activity_lock`), with hook-coverage tests for the version endpoints and course meta. It is not in the v1 estimate.

### B5. Completion tracking

- **Quizzes inside hidden sections:** `blockQuiz` keeps its state in component memory only (`QuizBlockComponent.tsx`: `useState` `submitted`, no API calls found). Hiding one has no effect on completion. Assignments are activity-level and cannot sit inside a block. A button linking to an assignment inside a hidden section is simply hidden; authors are warned in help text.
- **Activity- or chapter-level targeting:** *not in v1.* Upstream restricted locks look like a fit, but `services/courses/certifications.py::is_course_fully_completed` counts **every published activity** in the course regardless of lock. A learner locked out of a lesson could never reach 100% or get a certificate.
- **Recommended minimal model:**
  1. One course per department, plus the General course. The companion service handles enrolment, so department targeting at course level is already solved.
  2. Within a course, targeting is block-level only.
  3. A lesson that applies to only one level puts its whole body in one audience section. Other learners get the "Nothing in this lesson applies to your role" card and mark it complete in one click, so completion % stays honest and the logic remains upstream's.
  4. Revisit activity-level targeting (with a completion-denominator hook in `is_course_fully_completed`) only if authors report the one-click lessons as friction.

### B6. Fork-safety plan

**Critical compatibility fact:** TipTap 3.31.3 (`apps/web/package.json`) is created with `enableContentCheck: false` by default (`node_modules/@tiptap/core/src/Editor.ts`). When content contains an unknown node, `createNodeFromContent` logs `console.warn('[tiptap warn]: Invalid content.')` and **returns an empty document** (`src/helpers/createNodeFromContent.ts`). Every TipTap instance that loads activity content **must** register the MKA nodes, or the *whole lesson renders blank*.

**Upstream hooks required (verified files and symbols):**

| # | File | Symbol / location | Hook |
|---|---|---|---|
| W1 | `apps/web/components/Objects/Editor/Editor.tsx` | `extensions` `React.useMemo` array (around line 162) | `import { mkaEditorExtensions } from '@components/mka/editor'` + `...mkaEditorExtensions({ editable: true }),` (the import also registers the slash items as a side effect) |
| W2 | `apps/web/components/Objects/Activities/DynamicCanva/DynamicCanva.tsx` | `useEditor({ extensions: [...] })` in `Canva` | import + `...mkaEditorExtensions({ editable: false }),` |
| W3 | `apps/web/components/Objects/Editor/EditorPreview.tsx` | `extensions: [` (line 50); used by `VersionHistoryPanel.tsx`, `MergeConflictModal.tsx` | import + spread (without it, version previews render blank) |
| A1 | `apps/api/src/router.py` | `v1_router.include_router(...)` | import + `include_router(mka_attributes_router, prefix="/mka/attributes", …)`, same pattern as the existing `mka_profile` block |
| A2 | `apps/api/src/services/auth/session.py` (origin/dev) | `issue_session_or_challenge`, which already has an MKA line | `await mka_refresh_on_login(db_session, user, amr)  # MKA fork` (fail-open, Google-only) |

Optional, not in v1: O1 a `get_activity` strip hook (B4); O2 a completion-denominator hook in `is_course_fully_completed` (B5); O3 a `content_extraction._walk_prosemirror_node` audience annotation (B2).

**Not needed (verified):**
- `apps/collab/src/index.ts` is a Hocuspocus server with no ProseMirror schema; it only imports `@hocuspocus/*`, jwt and redis.
- Board canvas (`components/Dashboard/Boards/BoardCanvas.tsx`) holds board content, not activity content (**UNVERIFIED** that boards can never embed activity JSON; `ActivityBlockComponent.tsx` renders `DynamicCanva`, which is covered by W2).
- Discussion editors are separate content.
- GDPR hooks reuse the existing fork functions.
- Admin UI reuses the existing `OrgUsers.tsx` MKA hook.

**Fork-only files:**
- web: `components/mka/editor/` (`index.ts`, `AudienceNode.ts`, `AudienceView.tsx`, `AudiencePicker.tsx`, `AudienceBar.tsx` plugin view, `ViewerField.ts`, `Counterparts.tsx`, `slash.tsx`), `components/mka/audience/evaluate.ts`, `services/mka/attributes.ts`, `app/orgs/[orgslug]/dash/mka/identities/page.tsx`
- api: `services/mka/{identity_parser.py, identity_rules/2026.1.json, attributes.py, audience_eval.py, counterparts.py}`, `db/mka_user_attributes.py`, `routers/mka_attributes.py`, migration, tests

**Unknown-node behaviour elsewhere:**
- **Upstream instance importing a fork export:** the activity renders blank, with a warning in the console. This is acceptable because fork exports are not meant for vanilla instances; document it.
- **Course clone** (`services/courses/courses.py`, around line 1404): copies `content` verbatim, and `_replace_uuids_in_content` only rewrites strings that appear in its uuid map. Audience nodes survive.
- **Export/import** (`transfer/export_service.py`/`import_service.py`): deep copy, so nodes survive.
- **RAG:** recurses into them (see B2).
- **AI course planning / generate-activity:** never emits these nodes. Authors add them afterwards, so there is no conflict.

**Merge-conflict risk:** low. W1–W3 are append-only lines in long extension arrays that upstream edits often, but a one-line spread re-applies trivially. A2 sits next to an existing MKA line in a stable function.

**Upgrade guard:** a fork test `apps/web/tests/mka-editor-hooks.test.mjs` greps every `useEditor(`/`extensions: [` site under `components/Objects` and `app/` and fails if any site that loads activity content (allow-list: Discussion*, Board*, CodeMirror) lacks `mkaEditorExtensions`. This catches a *new* upstream renderer after a pull. Log all hooks in `.codebase-memory/upstream-modifications.md` with exact diffs, per policy.

### B7. Milestones and estimates (one experienced dev; days)

| M | Deliverable | Days |
|---|---|---|
| M1 | Rules file + parser + 150-row test matrix + migration + store + audit + login hook (A2) + backfill/recompute | 4 |
| M2 | Attributes API (me, admin list/override, roster, count), GDPR fork extensions, admin dialog tab + review-queue page | 3.5 |
| M3 | Evaluator (TS + Py) + shared vectors; `mkaAudience` node + viewer rendering + W1–W3 + hook-guard test | 3 |
| M4 | Picker UX (presets, chips, "Reads as", counts, warnings), slash/shortcut, a11y, mobile sheet | 4 |
| M5 | Audience bar + Preview as (personas, person, custom) + empty-lesson and unrecognized notes | 2.5 |
| M6 | Inline fields + Counterparts (MailboxProvider) | 2 |
| M7 | Playwright persona e2e, dev rollout, author pilot fixes | 3 |
| | **Total** | **≈22 days (≈4.5 weeks)**; P2 coverage/overlap hints +2; Phase 3 server strip +3 |

### B8. Test plan

- **Parser matrix** (`test_mka_identity_parser.py`, table-driven, ~150 rows), covering:
  - every department × local prefix (Albany);
  - every national mailbox;
  - `motamid@` → Aitmad; `motamid.albany@` → local Motamid;
  - `qaid.northeast@` → regional; `qaid.albany@` → local Qaid; a synthetic collision rules file → `ambiguous`;
  - `naibqaid.houston@`;
  - `nazim.syracuse@atfalusa.org` and `murabbi.syracuse@atfalusa.org` → Syracuse-Binghamton; `tabligh.syracuse-binghamton@mkausa.org`;
  - `rtp`, `kansascity`, `saintlouis`, `siliconvalley` (→ partial until confirmed; `newyorkmetro-region` was an error, see the 2026-10-05 resolution);
  - Atfal/Amoor-e-Tuluba swap regressions;
  - `rishtanata.x` → Rishta Nata;
  - `mahmood.kauser@` → unrecognized (roster fills it); `someone@gmail.com` → not_applicable;
  - case and whitespace; malformed (`a@@b`, empty); unknown prefix; unknown slug → partial;
  - properties: the parser never raises (hypothesis fuzz), the output is deterministic, and the output is unaffected by `amr` (amr gating is tested in the hook).
- **Store/service:** idempotent recompute (no audit row when unchanged); override precedence; roster precedence; GDPR export/delete; login hook fail-open (parser raising does not block login); non-Google amr does not derive.
- **Evaluator vectors:** shared JSON. Covers show/hide × null attributes, multiple groups, unknown key → no match, `v:2` → false, `officeholder:false`.
- **Router:** authz matrix (learner cannot list or override, author can count but not list people, admin full); audience/count returns aggregates only.
- **Web component** (bun test, matching the existing `apps/web/tests/*.test.mjs` style): picker "Reads as" sentence generation; preset expansion; label rendering; duplicate-id regeneration; hook-guard test.
- **Playwright e2e** (`apps/e2e`), with personas seeded through the roster/override API: Local Nazim Tabligh Albany, Regional Qaid Northeast, Mohtamim Tabligh, Atfal Nazim Syracuse, unrecognized Gmail user, org admin. One fixture lesson with 5 sections + inline fields + counterparts. Assert:
  - exactly the expected text is visible per persona, and hidden text is absent from the DOM;
  - no hidden text appears in the DOM during load (sample the DOM on the first animation frame after mount);
  - the admin sees badges and Preview-as switching;
  - the version-history preview is not blank;
  - mobile viewport picker.

### B9. Rollout

1. Merge behind env flag `MKA_AUDIENCE_ENABLED` (web: hides slash items and bar; nodes still render, so content never goes blank). Attributes derivation runs regardless; it is invisible.
2. **ilm-dev.mkausa.org:** run the backfill and review the "Needs review" queue with the national IT/Aitmad team. Fix rules (expect a few rounds), then seed roster overrides for personal-name national officers.
3. Pilot with 1–2 Mohtamims authoring one real lesson each. Run a 30-minute moderated session that measures time to first correct section, and target under 2 minutes without help.
4. Prod: enable before the **Nov 1** training window with a buffer week. Monitor the counts of `unrecognized`/`partial` accounts and the console-warning rate for `Invalid content` (blank-lesson canary).

---

## Alternatives considered and rejected

| Alternative | Why rejected |
|---|---|
| **Separate course per audience** (Local/Regional/National × 21 depts) | Many copies drift apart; authors maintain duplicates every year; enrolment complexity moves to the companion service. |
| **Generate per-region/per-role courses from a template** (companion service) | Build pipeline + sync problems; edits after generation diverge; authors lose WYSIWYG. |
| **Iframe embed from the companion service** rendering role content | Separate auth/session inside the iframe, no editor integration, poor a11y and print, content lives outside LearnHouse versioning. |
| **Upstream usergroup locks per activity** | Locked activities still count in `is_course_fully_completed`, so learners can never finish. The granularity is the whole activity, and the locked-gate UI says "locked", not "not for you". |
| **JWT claims for attributes** | Upstream token code would need changes; overrides would stay stale until refresh; adds PII to every request. |
| **Server-side content filtering in v1** | Needs ≥4 upstream hooks (activity, course meta, versions ×2) plus RAG and is still bypassable by future endpoints. That cost isn't justified for low-sensitivity content. Kept as optional Phase 3. |
| **Full boolean rule builder** (nested AND/OR/NOT) | Non-technical authors make mistakes with it. AND-across/OR-within plus one NOT covers the real cases, and the schema already allows OR-groups later. |
| **Store audience as attribute on existing nodes** (e.g. on `callout`) | Unknown attrs are dropped silently by upstream schemas, which would make content visible to all, the wrong failure direction. It also can't wrap several blocks. |

---

## Open risks

1. **Identity belongs to the role account, not the person.** Role mailboxes (`tabligh.albany@`) pass to the next officeholder on Nov 1, so last year's progress and certificates come with the account. The successor might see "completed", or completions might be attributed to the wrong person. Mitigations: annual new courses (companion), plus the AMC ID in `mka_user_profile` as the person key for reporting; the profile gate should re-confirm AMC ID each year. *This needs an owner decision outside this spec.*
2. **Blank-lesson failure mode.** Any TipTap instance missing the extension renders the whole activity empty (verified TipTap behaviour). Mitigations: the hook-guard test, the console-warning canary, and nodes registered regardless of the feature flag.
3. **Data quality of the mailbox scheme.** Swapped columns, `rishtanata` reuse, ~~`newyorkmetro-region`~~ (error, resolved 2026-10-05), personal-address officeholders and possible future region/Majlis slug collisions. Mitigations: fail-safe statuses, the review queue, roster overrides, and the load-time collision check.
4. **Audience is not access control.** A learner with dev tools can read other sections, and RAG chat may quote them. This is acceptable only while content is non-confidential; it is stated in the UI.
5. **atfalusa.org spoofing** if `MKA_GOOGLE_ONLY_DOMAINS` is not extended. The fallback amr gate covers it, but the config must change.
6. **Counts undercount** before everyone has signed in (the dataset is signed-in users only). Mitigation: the label says so, and roster backfill from the companion closes the gap.

---

## Decisions needed from the user (recommended defaults in bold)

1. **D1 – Evaluation location:** client-side presentation filter in v1, with server strip as optional Phase 3? **Default: yes, client-side. Mark the block "not for confidential content".**
2. **D2 – Rules storage:** versioned JSON file in the repo (reviewed and tested) vs admin-editable DB table? **Default: file for v1, DB layer later if changes become frequent.**
3. **D3 – Activity-level targeting:** none in v1 (block-level plus "nothing applies to you, continue" card)? **Default: none in v1.**
4. **D4 – "Not shown to the user":** OK that learners can see their own values via author-placed inline fields and the `/me` call? **Default: yes. Attributes are not on any profile or settings screen.**
5. **D5 – Unresolved org facts:** (a) ~~the meaning of `newyorkmetro-region`~~ (resolved: error; `newyorkmetro.region@` is the NY Metro Regional Qaid), (b) `muqami@` national vs local, (c) role-title vocabulary (Nazim/Mohtamim/Regional Qaid), (d) add `atfalusa.org` to `MKA_GOOGLE_ONLY_DOMAINS`. **Defaults: (a) `partial` until confirmed, (b) national executive, (c) titles as in A3 held in config, (d) yes, add it.**
