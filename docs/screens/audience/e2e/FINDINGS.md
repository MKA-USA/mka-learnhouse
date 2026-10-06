# Audience block e2e: product findings (M7)

STATUS (re-run on `fix/mka-audience-explorer-findings` 9f8d75a8 merged): FINDING-0, 1, 2, 3, 4 are FIXED and verified by
the suite (the `test.fail` pins were removed; 59 specs pass, 3 consecutive runs). FINDING-5 is by design. Counterparts
observations are resolved (see the end). The text below is the original report.

Found by `apps/e2e/features/mka-audience` against a real local stack (production web build with
`NEXT_PUBLIC_MKA_AUDIENCE_ENABLED=1`, mock unset, real API). Product code was NOT changed. Each finding is pinned in the
suite as an expected-failure (`test.fail`): when the bug is fixed the test reports "expected to fail but passed" and the
annotation must be removed. Repro for all: `apps/e2e/mka/stack.sh up`, then
`cd apps/e2e && bunx playwright test -c mka/playwright.config.ts`.

## FINDING-0 (high) [FIXED, verified: the bar mounts on the learner page for admin and course author on every load]: the document-level Audience chrome does not mount on the learner page
- Repro: open the lesson as any learner. Inspect `document.querySelector('.ProseMirror').editor.storage.mkaAudience.store.get()`.
- Expected: after `/mka/attributes/me` resolves, the learner filter runs (`copyPolicy.kind` becomes `viewer`), the learner
  notes and (for admins/authors) the Audience bar render.
- Actual: `copyPolicy` stays `none` and `editor.state.doc` still holds every hidden section. Measured in cold, fresh
  contexts: learners 0 of 26+ loads, org admin about 2 of 8, course author 0 of 40; on the EDITOR route 12 of 12 loads
  mount. Instrumenting the built chunk showed the `AudienceChrome` component's effects never run, and its mount element
  `.mka-audience-chrome` stays empty: the `ReactRenderer` created inside the ProseMirror plugin `view()` (chromePlugin.ts)
  is never attached to a React portal. Likely a creation-order race with `EditorContent` under `useEditor`
  `immediatelyRender:false` in a production build.
- Consequences are FINDING-1, 2, 3 below. Hidden section CONTENT stays out of the DOM (node views hide it independently), so
  the first-frame and `page.content()` checks pass.

## FINDING-1 (high) [FIXED]: table of contents lists hidden headings
- Expected (runbook smoke test step 5): a learner's TOC lists no hidden heading. Actual: all six headings, including the
  headings of sections hidden from that learner, for every learner persona (`.toc-item`, stable for 8+ s).
- Test: `02-toc-and-copy` "table of contents does not list hidden headings" (6 personas, expected-failure).

## FINDING-2 (medium) [FIXED]: "tailored by role" note never shown to an unrecognized account
- Expected: one-line note when sections are hidden because the viewer is unrecognized. Actual: never rendered
  (`mka-note-unrecognized` absent). Same cause as FINDING-0. Test: `01-learner-views` last test (expected-failure).

## FINDING-3 (high) [FIXED]: select-all + copy serializes the whole lesson, hidden sections included
- Repro: as a learner click into the lesson, Ctrl+A, Ctrl+C, read the `copy` event's `clipboardData` (text/plain).
- Expected (runbook step 5): no hidden text. Actual: text/plain contains every section's heading and body. The DOM
  selection (`getSelection().toString()`) is clean; the clipboard payload is not. Test: `02-toc-and-copy` "select-all +
  copy contains no hidden text" (6 personas, expected-failure); "contains the sections the learner can see" passes.

## FINDING-4 (low) [FIXED]: read-only badge for a "Hide from" section reads the opposite of the rule
- Admin or course author on the learner page: the badge reads "Hidden from: Everyone except national officeholders" for a
  rule that hides the section from national officeholders. The author header (editor) strips "Everyone except"; the
  badge (`ReadOnlyBadge` in AudienceHeader.tsx) does not. Test: `05-admin-and-author` (expected-failure).

## FINDING-5 (by design): the 375px bottom-sheet picker is unreachable because the editor is desktop-only
- `ResponsivePopover` switches to a bottom sheet at <= 639px, but `Editor.tsx` replaces the editor with "Desktop Only" at
  <= 767px, and the picker only exists in the editor. The spec item "picker at 375px opens as a bottom sheet" cannot be
  exercised; the suite asserts the "Desktop Only" gate instead (`06-editor-flows`). The sheet is dead code unless the
  editor gate changes.

## Counterparts (resolved)
Own office is now omitted: a national Mohtamim gets no card; a recognized executive without a department (Regional Qaid)
gets `reason: not_applicable` and the card "No department contacts apply to your role." Specs updated accordingly.

## Observations (original, superseded where noted above)
- Regional Qaid (matched, `region: Northeast`, no department) gets `reason: no_department`, so the counterparts card says
  "Counterparts appear once your role is recognized." for a recognized person (contract §2.3 wording, misleading copy).
- A national Mohtamim's counterparts card lists their own role mailbox (`tabligh@mkausa.org`) unless the account's own
  address equals it; with the synthetic address it is shown.
- The activity JSON, hidden sections included, is still delivered to every enrolled browser (known: presentation, not
  secrecy). `page.content()` and raw SSR HTML contain no hidden BODY text because the lesson is fetched client-side.
- The email validator rejects `@example.invalid` (reserved TLD), so personas use `@e2e-tests.com` (non-MKA, never mailed).
