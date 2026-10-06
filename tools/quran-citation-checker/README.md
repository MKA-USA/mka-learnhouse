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

Flags: `--file`, `--editions en,ur` (known: `en zk ur sc v5 sp_en sp_ur`), `--accept`, `--reject`, `--json`, `--find-unreferenced`, `--no-numbering-map`.

Verdicts per candidate: `confirmed`, `needs_review`, `rejected`, `surah_mention`, `invalid_reference` (chapter outside 1..114, verse beyond the surah's length, reversed range; these skip Jev and the fetch).

Reference forms recognised: everything listed above plus verse-first order (`verse 255 of Surah al-Baqarah`, `ayah 255 of chapter 2`), Arabic-script names (`سورة البقرة آية ٢٥٥`, `آية ٢٥٥ من سورة البقرة`, `(البقرة: 255)`), with or without diacritics and with Arabic-Indic or Persian digits. Matching runs on a canonicalized copy of the text; `span`/`index` always point into the original input.

### Surah-only mentions

A surah named with no verse (`Surah Al-Kahf is read on Fridays`) gets the verdict `surah_mention` (chapter + name) once Jev confirms it refers to the Quran. No verses are fetched and it does not set `containsCitation`. Bare `chapter 3` is not treated as a mention (too ambiguous); `Surah 3` is.

### Unreferenced quotes (`--find-unreferenced`, off by default)

Finds quoted passages (an Arabic-script run of >= 4 words, or a quote-marked English passage of >= 20 chars) with no candidate reference within 200 chars. Each passage (max 5 per text) is searched on Al Islam (`semantic` for English, `keyword` for Arabic), the top 3 hits are fetched, and Jev (`noul`) judges per hit whether the passage quotes or closely paraphrases that verse. The result is never auto-confirmed: it is `needs_review` with the proposed references, match probabilities (best first) and the fetched Arabic/translation, or `no_match` when even the best hit is at or below the reject threshold (or the search failed). Costs 1 search + up to 3 verse fetches + 1 Jev call per passage; calls run sequentially (the client also queues to 2 concurrent requests). Search ranking is noisy (the right verse is often 2nd or 3rd), so the judged top 3 can miss it.

Library:

```ts
import { checkText } from './src/index.js';
const { containsCitation, results } = await checkText(text, { editions: ['en'] });
```

`jev` and `quran` options accept stubs (used by the tests).

## Numbering (important)

People cite in standard numbering (2:255 = Ayat al-Kursi, Bismillah not counted). Al Islam's `v` counts the Bismillah as verse 1 in every chapter except 1 and 9; `v_` matches standard numbering. Observed live: requesting chapter 2 verse 255 returns `v=255, v_=254` (standard 2:254). So the fetch step requests verse N+1 for chapters other than 1 and 9, then keeps only rows whose `v_` equals the cited verse and warns if the count is off. Returned rows are never relabelled: both `v` and `v_` are shown and Arabic is untouched. `--no-numbering-map` (`numberingMap: false`) turns the mapping off and passes cited numbers to Al Islam unchanged. **Off means off by one for every chapter except 1 and 9**: citing 2:255 returns standard 2:254. Use it only if your references are already in Al Islam numbering. Note the Arabic verse-end marker in Al Islam text carries Al Islam's number (e.g. 2:255 ends with `256`).

## Limits

- **Thresholds are untuned.** Defaults: cite probability >= 0.8 confirmed, <= 0.2 rejected, between is `needs_review` (`DEFAULT_THRESHOLDS` in `src/judge.ts`, overridable). Calibrate on labelled examples before trusting them. `kind=not_a_citation` downgrades a confirmation to `needs_review`.
- Jev's `kind` confidence is often low on bare references (41% on a clear `Quran 2:255`, 99% on `verse 255 of Surah al-Baqarah`). `kind` is therefore only a consistency check (`not_a_citation` downgrades a confirmation); the decision uses the cite probability.
- The Al Islam API is undocumented upstream (see the quran-mcp README): no stability, rate-limit or redistribution guarantees. Do not assume you may republish the fetched translations.
- Unreferenced quotes need `--find-unreferenced` and are only ever proposals; unquoted paraphrases and short (< 4 word) Arabic quotes are not detected.
- Not detected: lists like "2:255, 257", surah names in other scripts/languages (Urdu etc.), `Surah al-Baqarah: 255` without the word verse.
- One Jev request per candidate; text with many candidates makes many requests.
- Judge failures are reported as `needs_review` with an `error`, not thrown.
