# test-navigator (fork-only)

Model-assisted **exploratory** tester. Deterministic Playwright does every click; a typed-decision model only picks among
enumerated element ids. Models are for exploration and fuzzy judgment, never pass/fail gating. Anything reported as a
finding must be re-verified by a deterministic probe (`src/probes.ts`) with no model involved.

## How it works

1. `observe.ts` enumerates visible, unobstructed controls (buttons, links, inputs, menu items, the rich-text editor) and
   tags each `e1..eN` with a stable CSS path. The model never sees or produces selectors.
2. `navigator.ts` asks one **Choice** question per step: options = shortlisted element ids + `key_*` + `done`/`stuck`
   (+ `type_i` candidates when a field has focus). Budgets: max steps, max model calls. Guards: no-op and cycle detection,
   `stuck` only after step 8, false `done` is checked against the mission's deterministic `success`.
3. After each step: screenshot (`docs/screens/audience/explore/<mission>/step-NN.jpg`), `trace.json`, invariants
   (JS errors, 4xx/5xx, h-overflow, blank page, `undefined`/`NaN` text, invalid authored rules) and an optional Jev
   "does this look wrong" Noul (`model-flag`, always *unconfirmed*).
4. Identical decisions are cached (`.decision-cache.json`, git-ignored).

Backends (`models.ts`), same request shape (`POST /v1/systemone`):

| id | model | where | notes |
|---|---|---|---|
| `clef` | `clef-flash:latest` | local Ollama `127.0.0.1:11434/v1/systemone` | max 26 options per Choice; text only (no images); free |
| `jev` | `jev-latest` | `api.typesafe.ai`, `TYPESAFE_API_KEY` env | up to 255 options; $0.042 / Mtok input |

Default: `--primary clef --fallback jev`; Jev is asked again when clef's top-2 probability margin is below `--min-margin` (0.2).

## Run

```sh
# dev server with the mock layer (free port)
NEXT_PUBLIC_MKA_AUDIENCE_MOCK=1 NEXT_PUBLIC_MKA_AUDIENCE_ENABLED=1 next dev -p 3517 --turbopack   # in apps/web
cd custom/test-navigator && bun install
TN_BASE=http://localhost:3517 bun run src/cli.ts all            # missions: author authorhint authorkbd preview learner picker playground
TN_BASE=http://localhost:3517 bun run src/probes.ts --runs 3    # deterministic repros (the confirmed-findings source)
TN_BASE=http://localhost:3517 bun run src/bench.ts              # clef vs Jev, labelled decisions + verdicts
bun run src/real.ts [/private/tmp/claude-501/mka-e2e-stack.json]  # phase 2: real local stack, read-only
```

Chromium is reused from the `apps/e2e` Playwright cache (`~/Library/Caches/ms-playwright`); override with `TN_CHROMIUM`.
