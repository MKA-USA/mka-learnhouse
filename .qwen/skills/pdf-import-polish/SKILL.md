---
name: pdf-import-polish
description: Mandatory workflow for importing PDF content into LearnHouse — covers extraction rules, content structuring, Islamic content handling, and a final polish pass to catch PDF artifacts. Use whenever importing, converting, or restructuring PDF-sourced content into LearnHouse activities.
---

# PDF Import & Polish Workflow

When importing PDF content into LearnHouse (or any ProseMirror-based system), follow this workflow to avoid the common artifacts and quality issues that come from PDF text extraction.

## When to Use

- Importing PDF-sourced content into LearnHouse activities
- Converting PDF text to ProseMirror JSON
- Restructuring existing imported content
- Any time PDF extraction is the source of truth for course content

## Phase 1: Extraction Rules

### Preserve ALL text content
- **Arabic text**: Never strip Arabic Unicode characters (\u0600-\u06FF). Quranic verses, prayer recitations, basmala, azan text — all must be preserved.
- **Mark Arabic paragraphs** with `"attrs": {"dir": "rtl"}` so LearnHouse renders them right-to-left with the Tajawal font.
- **Mixed Arabic/English** lines are fine — LearnHouse's `unicode-bidi: plaintext` handles direction per-paragraph automatically.

### Decode encoding artifacts
PDF extraction produces HTML entities and encoding artifacts. Decode ALL of these:
- `&#39;` → `'` (apostrophe — extremely common)
- `&amp;` → `&`
- `&lt;` → `<`, `&gt;` → `>`
- `&quot;` → `"`
- `&#x[hex];` → decoded character
- Use `html.unescape()` (Python) or equivalent in other languages

### Strip only intentional artifacts
- **Page numbers**: Standalone numbers on their own line at page boundaries
- **`[Publishers]` markers**: Editorial markers from the source PDF
- **Header/footer text**: Repeated text that appears on every page

**Do NOT strip**: Footnote reference numbers that are part of the content flow, Arabic text, or any content you're unsure about.

## Phase 2: Content Structuring

### Break up walls of text
PDF extraction produces long paragraphs. Restructure into:
- **Max 3-5 sentences per paragraph** — split on natural topic breaks
- **Headings from ALL CAPS lines** — PDF section headers are often in all caps. Convert to `heading` nodes (level 2 or 3).
- **Callout blocks** for key content:
  - Quranic verse translations → `calloutInfo` with citation
  - Key definitions or important statements → `calloutInfo`
  - Warnings or important notes → `calloutWarning`
  - Tips or helpful context → `calloutTip`

### Heading hierarchy
- **H2**: Major section breaks (from ALL CAPS PDF headers)
- **H3**: Subsections (from title-case lines that introduce new topics)
- **H4**: Minor subdivisions if needed

## Phase 3: Islamic Content Handling

### Honorific conventions
LearnHouse has **no superscript mark** in the TipTap editor. Use parenthetical convention:

| PDF artifact | Correct form |
|---|---|
| `Ahmadas` | `Ahmad (as)` |
| `Prophetsa` | `Prophet (sa)` |
| `Messengersa` | `Messenger (sa)` |
| `Messiahas` | `Messiah (as)` |
| `Mahdias` | `Mahdi (as)` |
| `Ahmadra` | `Ahmad (ra)` |
| `(as)`, `(sa)`, `(ra)` | Leave as-is (already correct) |

**Detection regex**: `\b(Ahmad|Prophet|Messenger|Jesus|Moses|Abraham|Messiah|Mahdi)(as|sa|ra)\b`

### Quranic citations
Use the `alislam-quran` API (`import { AlIslamQuranClient } from 'alislam-quran'`) for all Quranic verse references:

1. **Find references** in content: surah names + verse numbers (e.g., "Surah Al-Baqarah, 2:256", "Al-Fatihah 1:1-7")
2. **Map surah name → chapter number** (114 surahs)
3. **Fetch verses**: `await client.getVerses(chapter, startVerse, endVerse)`
4. **Format citations**:
   - Arabic text in RTL paragraph: `"attrs": {"dir": "rtl"}`
   - English translation in calloutInfo: `"\"<translation>\" — Surah <Name>, <chapter>:<verse>"`
   - Clean citation format: `Surah <Name>, <chapter>:<verse>` (capitalize "Al-", remove footnote numbers)
5. **Always** `await client.release()` when done. Add 300ms delay between API calls.

### Approved sources
For MKA Ilm courses, Islamic content must come from approved sources only:
- Philosophy-of-Teachings-of-Islam.pdf
- alislam.org (always include URLs)
- Holy-Quran-English.pdf
- The alislam-quran API

## Phase 4: Final Polish Pass (MANDATORY)

**This pass is non-negotiable.** Run it after every PDF import before declaring content ready.

### 4.1 Mid-word hyphenation (most common PDF artifact)
PDF line breaks insert hyphens mid-word: "suf- fering", "per- son", "supplica- tion".

**Fix**: Find pattern `(\w{2,})-\s+(\w{2,})` in English text nodes. If joining the parts produces a valid English word (5+ letters, all alphabetic), replace with the joined word.

**Skip**: Text nodes containing Arabic Unicode characters — transliteration hyphens may be intentional.

**Detection regex**: `/\b\w{2,}-\s+\w{2,}\b/g` in non-Arabic text nodes.

### 4.2 Footnote remnant numbers
PDF footnote markers become standalone numbers at paragraph starts: "4", "18", "25".

**Fix**: Remove leading numbers (1-2 digits) from paragraph starts when the number is followed by whitespace and nothing else, or when it's clearly a footnote marker (sequential numbers like 18, 19, 20...).

### 4.3 Broken words across ProseMirror nodes
Sometimes a word splits across two adjacent text nodes: one ends with "peo-" and the next starts with "ple".

**Fix**: Check adjacent text nodes for `word-` / `continuation` patterns. Merge if they form a valid word.

### 4.4 Double spaces
Replace 2+ consecutive spaces with single space in English text. Skip Arabic text.

### 4.5 Stray punctuation
- Periods or commas at the start of paragraphs
- Multiple consecutive periods that aren't ellipses ("...." → "...")
- Orphan single characters

### 4.6 Repeated words
Accidental duplication: "the the", "is is". Detection: `\b(\w+)\s+\1\b`

### 4.7 Verify structure
- Every reading should have headings breaking up the text (no section > 500 words without a heading)
- Callout blocks should be used for Quranic translations and key quotes
- Paragraphs should be 3-5 sentences max
- No paragraph should exceed 200 words

## Phase 5: Verification Script

After all fixes, run a verification scan that checks for:

```
✓ No HTML entities remaining (&#39;, &amp;, etc.)
✓ No merged honorifics (Ahmadas, Prophetsa, etc.)
✓ No mid-word hyphenation in English text
✓ No standalone footnote numbers at paragraph starts
✓ No double spaces in English text
✓ Arabic text present where expected (if source PDF had Arabic)
✓ Callout blocks present for Quranic citations
✓ Heading density adequate (no wall-of-text sections)
```

## Quick Reference: Common PDF Artifacts

| Artifact | Example | Fix |
|---|---|---|
| Line-break hyphenation | "suf- fering" | Join: "suffering" |
| HTML entities | "Bai&#39;at" | Decode: "Bai'at" |
| Merged honorifics | "Ahmadas" | Split: "Ahmad (as)" |
| Footnote remnants | "18" at paragraph start | Remove |
| Double spaces | "word  word" | Collapse: "word word" |
| Broken word across nodes | "peo-" / "ple" | Merge: "people" |
| Stripped Arabic | Missing basmala | Restore from source |
| [Publishers] markers | Editorial notes | Remove |
| Page numbers | "15" on own line | Remove |

## Scripts

- **Extraction + structuring**: `scripts/build_restructured_courses.py` (migration repo)
- **Honorific + entity fix**: `scripts/fix_content_quality.py`
- **Quranic citations**: `scripts/fix_quranic_citations.mjs`
- **PDF artifact polish**: `scripts/fix_pdf_artifacts.mjs`

All scripts are in `/Users/mamjed/Documents/mka-thinkific-migration/scripts/`.
