# MKA Audience block: rollout to ilm-dev

The Audience block lets an author show or hide part of a lesson by officeholder attributes (level, department, role,
region, Majlis). Author guide: `docs/runbooks/mka-audience-block-author-guide.md`. Design record:
`docs/superpowers/specs/2026-10-04-mka-conditional-visibility-design.md`, contracts
`docs/superpowers/specs/2026-10-05-mka-audience-contracts.md`. It depends on the identity attributes API from
`docs/runbooks/mka-compliance-rollout.md` (same branch family; deploy that first or together).

## Env var (runtime, not build time)
| Var | Where | Value |
|---|---|---|
| `NEXT_PUBLIC_MKA_AUDIENCE_ENABLED` | the web/app container, in Coolify, per environment | `1` to turn authoring on; unset or anything else = off |
| `NEXT_PUBLIC_MKA_AUDIENCE_MOCK` | nowhere | MUST be unset. Build-time dev mock, hard-off in production builds, and deliberately NOT runtime-enablable |

How it reaches the browser: `apps/web/server-wrapper.js` copies every `NEXT_PUBLIC_*` from the container environment
into `window.__RUNTIME_CONFIG__` (served as `/runtime-config.js`, which can execute after hydration). The flag code
(`apps/web/services/mka/flags.ts`) reads that on the client and `process.env` at runtime on the server, and re-checks for
about 5 seconds so the entry points appear once the config loads. A change is an env var change plus a container
restart; no rebuild.

Compose pass-through: Coolify injects service env into the container, but if the compose file lists `environment:`
entries explicitly, add `NEXT_PUBLIC_MKA_AUDIENCE_ENABLED: ${NEXT_PUBLIC_MKA_AUDIENCE_ENABLED:-}` to the app service.
Verify after deploy: `docker exec <app> printenv NEXT_PUBLIC_MKA_AUDIENCE_ENABLED` prints `1`, and
`https://<host>/runtime-config.js` contains `"NEXT_PUBLIC_MKA_AUDIENCE_ENABLED":"1"`.

## What the flag gates, and what it does not
Gated (authoring entry points only): the `/audience` slash items (section, viewer fields, counterparts), the Mod-Alt-A
shortcut, the header Preview button, and the Audience bar (except while a preview is active, so an author can always
exit one).

NOT gated, always on: registering the three nodes in every editor and viewer, evaluating sections, hiding content for
learners, learner notes. Turning the flag off therefore never blanks a lesson and never reveals hidden content;
existing sections keep working, authors just cannot add new ones.

## Blank-lesson canary
TipTap runs with `enableContentCheck: false`: a document containing a node the editor does not register renders as an
EMPTY lesson and logs `[tiptap warn]: Invalid content.` in the browser console. If a lesson with audience sections
ever looks blank, check the console for that line first. It means some TipTap instance lacks the MKA nodes (a new
upstream editor site after a pull). `apps/web/tests/mka-editor-hooks.test.mjs` is the guard and fails in CI until the
site calls `mkaEditorExtensions`.

## Rollback
1. Fastest, no code change: unset `NEXT_PUBLIC_MKA_AUDIENCE_ENABLED` and restart. Nodes keep rendering and hiding.
2. Full: revert the merge of the audience branch. Lessons that already contain audience sections would then render
   BLANK on the reverted build (unknown node), so only do this if no real lesson uses sections yet, or after removing
   them.

## Known risks (tell authors and admins)
- Presentation, not secrecy. Hidden sections are removed from what the browser renders and from the learner's editor
  state, but the lesson JSON is still served to the browser by the existing API (the API does not strip it). Do not put
  anything in a section that a learner must not be able to read by other means.
- Course AI / RAG. Course AI chat indexes every section's text course-wide, so it can quote another audience's
  instructions. Consider turning course AI chat off on audience-targeted courses.
- Per-activity "ask AI" is filtered by section (fork hook in `ai.py`: a learner's prompt only contains the sections they see); course RAG chat (`/rag/chat`, `rag/content_extraction.py`) still indexes all section text.
- Unrecognized users. An account whose email local part matches no identity rule, including unmatched `@atfalusa.org`
  addresses, is `unrecognized`: it never matches a "Show to" section, still sees untargeted and "Hide from" sections,
  and sees a one-line note that parts of the lesson are tailored by role. If every section is hidden it sees "Nothing in
  this lesson applies to your role". Watch the identities "Needs review" queue after launch.
- Counts and previews are for authors and admins only (the API enforces it); "Preview as a specific person" writes an
  audit row.

## Smoke test on ilm-dev (about 10 minutes)
1. Deploy; confirm the env var and `/runtime-config.js` as above. Browser console: no `[tiptap warn]: Invalid content.`
2. As an org admin open a test course, add an activity, type `/audience`: the Audience section item appears. Insert,
   pick "Local officeholders", Done. Header reads "Visible to: Local officeholders".
3. Select two paragraphs and press Mod-Alt-A: they are wrapped and the picker opens. Press Esc: the section is
   removed and the paragraphs remain.
4. Use the bar to preview as "Regional Qaid": the local section turns into a dashed "Hidden for this viewer"
   placeholder; "Exit preview" restores editing.
5. Save and publish. As a real local officeholder (and as a plain member, and as an unrecognized account) open the
   lesson: only matching sections are visible; right-click, view source or copy-all shows no hidden text; the table of
   contents lists no hidden heading; the unrecognized account sees the "tailored by role" note.
6. As an admin open the learner page: every section shows with a read-only "Visible to" badge and the bar defaults to
   Everything.
7. Unset the flag, restart: step 2's slash item is gone, step 5's lesson still renders and hides correctly.
