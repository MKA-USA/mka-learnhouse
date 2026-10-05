# quran-citation-checker

Standalone Node/TypeScript tool (isolated from the LearnHouse apps). Given free text it:

1. **Finds candidate references in plain code** (`src/candidates.ts`): `2:255`, `2:255-257`, `Quran 2:255`, `Q2:255`, `Surah al-Baqarah, verse 255`, `Surah al-Baqarah 2:255`, `Chapter 2 verse 255`, `Ayat al-Kursi` (small alias map). Chapter/verse numbers are parsed by code and validated against the 114-surah table in `src/surahs.ts`; the model never generates references.
2. **Asks TypeSafe's Jev** (`src/judge.ts`) whether each candidate really cites the Quran (vs. `2:55 pm`, a score, a Bible verse, ...). One `systemOne` request per candidate with three independent questions: `noul` cite probability, `choice` citation kind, `noul` "verse text quoted alongside?".
3. **Fetches official text** for confirmed candidates (`src/fetch.ts`) through the `alislam-quran` client: Arabic (unmodified), requested translation editions, `retrievedAt`, source `Al Islam (api.readquran.app)`.
4. **Optionally compares a quoted passage** to the fetched translation (`src/quote.ts`). This is a string heuristic (normalized containment + token Jaccard), not a model, and is flagged `heuristic: true`.

## Setup

```sh
cd tools/quran-citation-checker
npm install
npm link alislam-quran        # not published to npm; globally linked from ~/Documents/GitHub/quran-mcp
export TYPESAFE_API_KEY=...   # never printed, logged or written by this tool
```

Requires Node >= 20.

## Usage

```sh
npx tsx src/cli.ts "Allah says in the Quran 2:255 that He is the Ever-Living."
npx tsx src/cli.ts --file notes.txt --editions en,ur
echo "see Surah al-Baqarah verse 255" | npx tsx src/cli.ts --json
npm run smoke:fetch           # live fetch of 2:255 (en); needs no Jev key
npm run typecheck && npm test
```

Flags: `--file`, `--editions en,ur` (known: `en zk ur sc v5 sp_en sp_ur`), `--accept`, `--reject`, `--json`.

Verdicts per candidate: `confirmed`, `needs_review`, `rejected`, `invalid_reference` (chapter outside 1..114, verse beyond the surah's length, reversed range; these skip Jev and the fetch).

Library:

```ts
import { checkText } from './src/index.js';
const { containsCitation, results } = await checkText(text, { editions: ['en'] });
```

`jev` and `quran` options accept stubs (used by the tests).

## Numbering (important)

People cite in standard numbering (2:255 = Ayat al-Kursi, Bismillah not counted). Al Islam's `v` counts the Bismillah as verse 1 in every chapter except 1 and 9; `v_` matches standard numbering. Observed live: requesting chapter 2 verse 255 returns `v=255, v_=254` (standard 2:254). So the fetch step requests verse N+1 for chapters other than 1 and 9, then keeps only rows whose `v_` equals the cited verse and warns if the count is off. Returned rows are never relabelled: both `v` and `v_` are shown and Arabic is untouched. Note the Arabic verse-end marker in Al Islam text carries Al Islam's number (e.g. 2:255 ends with `256`).

## Limits

- **Thresholds are untuned.** Defaults: cite probability >= 0.8 confirmed, <= 0.2 rejected, between is `needs_review` (`DEFAULT_THRESHOLDS` in `src/judge.ts`, overridable). Calibrate on labelled examples before trusting them. `kind=not_a_citation` downgrades a confirmation to `needs_review`.
- Jev's `kind` confidence is often low (e.g. 41% for a clear bare reference); the decision uses the cite probability only.
- The Al Islam API is undocumented upstream (see the quran-mcp README): no stability, rate-limit or redistribution guarantees. Do not assume you may republish the fetched translations.
- Only referenced citations are found. Un-referenced quotes (Arabic or English with no `chapter:verse`) are not detected yet; future work: run quoted passages through `client.search` and judge the hits.
- Not detected: "verse 255 of Surah al-Baqarah" word order, bare surah mentions without a verse, non-English surah names or Arabic-script names, 3+ word ranges like "2:255, 257".
- One Jev request per candidate; text with many candidates makes many requests.
- Judge failures are reported as `needs_review` with an `error`, not thrown.
