# Audience block — exploratory testing findings (2026-10-05)

Tool: `custom/test-navigator/` (model-assisted navigator; deterministic replays in `src/probes.ts`). Targets: mock-mode harness (`/examples/mka-audience-editor`, `/examples/mka-audience-playground`) and, read-only, the local real stack.

## Confirmed (each fails 3/3 in `probes.ts`, no model involved)

| # | Severity | Finding | Probe |
|---|---|---|---|
| F1 | High | Mouse-clicking the slash item "Audience section" inserts nothing (keyboard Enter and Mod-Alt-A work). The section is inserted while the editor is blurred, then removed ~400 ms after mousedown, before mouseup. | `slash-click-audience-section` (control: `slash-enter-audience-section`) |
| F2 | Medium (a11y) | After Escape/Cancel closes the picker, focus lands on `<body>` instead of the Edit button. | focus probes |
| F3 | Medium (mobile) | At 375×667 the picker sheet's Cancel/Done footer is ~9 px visible; at 375×700 it is clipped by ~5 px. | mobile footer probe |
| F4 | Low (UX) | "Hide from" with no filters reads "Everyone except all officeholders" with no warning. | describe probe |
| F5 | Low (mock only) | Unknown `?mka_viewer=` silently shows the Local Nazim persona; persona ids differ between `mock-options.ts` and `attributes.mock.ts`. | mock probe |

F1 repro: dev server with MOCK=1, ENABLED=1 → `/examples/mka-audience-editor?mode=edit` at 1280×900 → `__editor.commands.setContent([p "Hello", empty p])` → click into the trailing empty paragraph → type `/audience` → click button "Audience section" → after 700 ms expect 1 `mkaAudience` node and a "Done" button; actual 0 nodes, no picker, an extra empty paragraph.

Passing probes: Escape, Cancel, nested-popover Escape, focus trap, damaged/unknown rules, HTML in department search, rapid open/close, 375 px editor overflow, keyboard shortcut.

## Mission results

- Preview as each persona: 7/7 pass (2–3 steps), no leaks.
- Learner persona views: 7/7 clean on mock; all 8 persona pages matched the oracle on the real stack (lesson content hash unchanged — read-only).
- Author "create a section for Local Tabligh Nazims": **fails with no hint** (40 steps, 50 s); with the hint "audience" and mouse it gets stuck on F1; with mouse denied it succeeds in 23–26 steps / 62–78 s (a human needs ~8 actions). Slash keywords miss "visible", "show". → discoverability concern for the pilot.
- Break the picker (desktop, phone, keyboard) and playground exploration: 40 steps each, no invariant hits; real-stack picker exploration 30 steps, none.

## clef-flash vs Jev (25 navigation decisions, 36 verdicts)

| | clef-flash (local) | Jev (cloud) |
|---|---|---|
| Navigation accuracy | 72% (92% when margin ≥ 0.5) | 96% |
| Verdict accuracy | 89% | 89% |
| Real-stack leak verdicts (40) | 60% | 80% |
| Latency idle / busy | 0.3–0.6 s / 3–5 s | 0.15 s / 3–5 s |
| Cost | free | ≈ $0.01 for all missions |

Recommendation: Jev as navigator; clef-flash for cheap triage and screenshot questions. Neither is reliable for open-ended "does this look wrong" — use oracles/invariants as the gate.

## Unconfirmed (model claims, not re-verified)

1. 11 Jev "looks wrong" flags in the no-hint author run — caused by the tool typing junk into the doc (false positives).
2. Jev flagged playground states and the designed fallback copy "You are in your Majlis" — not bugs.
3. First real-stack picker run logged 2×404 + 3×400 console errors (URLs not captured); two later runs with capture saw none.
4. One author run took 4630 s wall for 213 s model time — likely host sleep; not reproduced.
