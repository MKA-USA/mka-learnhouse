/**
 * Plain-code extraction of likely Quran references from free text.
 * The model never generates references; it only judges the ones found here.
 * All numbers are in standard citation numbering (Bismillah not counted).
 *
 * Matching runs on a canonicalized copy of the text (Arabic diacritics removed,
 * alef/yaa/taa-marbuta variants unified, Arabic-Indic and Persian digits turned
 * into ASCII digits). An index map takes every match back to the original text,
 * so `span`/`index` always refer to the untouched input.
 */
import { ARABIC_DIACRITICS, canonArabicChar, surahNumberFromName, validateReference, surahByNumber } from './surahs.js';

/** `surah_mention` = a surah named with no verse (never fetched as verses). */
export type CandidateKind = 'numeric' | 'named' | 'alias' | 'surah_mention';

export interface Candidate {
  /** Stable index within this text, in order of appearance. */
  id: number;
  chapter: number;
  /** 0 for surah_mention. */
  start: number;
  /** 0 for surah_mention. */
  end: number;
  /** Exact substring of the input that produced the candidate. */
  span: string;
  /** Offsets of span in the input text. */
  index: number;
  endIndex: number;
  contextWindow: string;
  kind: CandidateKind;
  /** false when the reference cannot exist (chapter > 114, verse beyond count, ...). */
  valid: boolean;
  invalidReason?: string;
  notes: string[];
}

export const CONTEXT_CHARS = 200;

const LETTER = String.raw`A-Za-z'’\-ء-ي`;
const RANGE = String.raw`(?:-|–|—|to|الي|الى)`; // to / الي
const VERSE_KW = String.raw`(?:verses?|ayah|ayat|ayahs|vv?|ايه|اية|ايات)`; // ايه / اية / ايات
const SURAH_KW = String.raw`(?:\b(?:surah|surat|sura|chapter)\b\.?|سوره)`; // سوره (after canonicalization)

// 2:255, 2:255-257, Quran 2:255, Q2:255, Q. 2:255, القران 2:255
const NUMERIC = new RegExp(
  String.raw`((?:\b(?:Qur['’]?an|Quran|Koran|Q)|القران)\.?\s*[,:]?\s*)?(\d{1,3})\s*:\s*(\d{1,3})(?:\s*[-–—]\s*(\d{1,3}))?(?!\d|:\d)`,
  'gi',
);
const KEYWORD = new RegExp(SURAH_KW, 'gi');
const WORDS = new RegExp(String.raw`^\s+([${LETTER}]+(?:\s+[${LETTER}]+){0,2})`);
const NUMBER_AFTER_KEYWORD = /^\s+(\d{1,3})\b/;
const TAIL = new RegExp(
  String.raw`^\s*[,;:،(]?\s*(?:${VERSE_KW}\.?\s*(\d{1,3})(?:\s*${RANGE}\s*(\d{1,3}))?|\(?\s*(\d{1,3})\s*:\s*(\d{1,3})(?:\s*[-–—]\s*(\d{1,3}))?\)?)`,
  'i',
);
// "verse 255 of Surah al-Baqarah", "ayah 255 of chapter 2", "آية 255 من سورة البقرة"
const REVERSE = new RegExp(
  String.raw`(?<![A-Za-z])${VERSE_KW}\.?\s*(\d{1,3})(?:\s*${RANGE}\s*(\d{1,3}))?\s*(?:of|from|in|من|في)\s+(?:the\s+)?${SURAH_KW}`,
  'gi',
);
// (البقرة: 255)  [البقرة:255-257]  ﴿...﴾ style brackets
const ARABIC_BRACKET = new RegExp(
  String.raw`[(\[﴿]\s*([ء-ي]+(?:\s+[ء-ي]+)?)\s*[:،]\s*(\d{1,3})(?:\s*${RANGE}\s*(\d{1,3}))?\s*[)\]﴾]`,
  'g',
);

const ALIASES: { re: RegExp; chapter: number; start: number; end: number }[] = [
  { re: /\b(?:ayat(?:ul|\s+al|\s+ul)?[-\s]*kursi|throne\s+verse)\b|ايه\s+الكرسي/gi, chapter: 2, start: 255, end: 255 },
  { re: /\bayat(?:un|\s+an|\s+un)?[-\s]*nur\b|ايه\s+النور/gi, chapter: 24, start: 35, end: 35 },
];

/** Canonicalized text plus map[i] = index in the original of canonical char i (map[len] = original length). */
export function canonicalize(text: string): { norm: string; map: number[] } {
  let norm = '';
  const map: number[] = [];
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (ARABIC_DIACRITICS.test(ch)) continue;
    const c = ch.charCodeAt(0);
    let out = canonArabicChar(ch);
    if (c >= 0x660 && c <= 0x669) out = String(c - 0x660);
    else if (c >= 0x6f0 && c <= 0x6f9) out = String(c - 0x6f0);
    norm += out;
    map.push(i);
  }
  map.push(text.length);
  return { norm, map };
}

type Raw = Omit<Candidate, 'id' | 'contextWindow' | 'valid' | 'invalidReason'>;
const rangeEnd = (start: number, e: string | undefined) => (e ? Number(e) : start);

function numericMatches(text: string): Raw[] {
  const out: Raw[] = [];
  for (const m of text.matchAll(NUMERIC)) {
    const prefix = m[1] ?? '';
    const numStart = m.index + prefix.length;
    // A bare number must not be glued to a preceding digit/colon/dot/slash (e.g. 12:30:45, 1.2:3).
    if (!prefix && numStart > 0 && /[\d:.\/]/.test(text[numStart - 1])) continue;
    const start = Number(m[3]);
    out.push({ chapter: Number(m[2]), start, end: rangeEnd(start, m[4]), span: m[0], index: m.index, endIndex: m.index + m[0].length, kind: 'numeric', notes: [] });
  }
  return out;
}

/** Parse the surah (name or number) that follows a surah keyword. */
function resolveSurahAfter(rest: string): { chapter: number; consumed: number; byName: boolean } | null {
  const num = NUMBER_AFTER_KEYWORD.exec(rest);
  if (num) return { chapter: Number(num[1]), consumed: num[0].length, byName: false };
  const w = WORDS.exec(rest);
  if (!w) return null;
  const words = w[1].split(/\s+/);
  for (let n = words.length; n >= 1; n--) {
    const chapter = surahNumberFromName(words.slice(0, n).join(' '));
    if (!chapter) continue;
    // consumed = leading whitespace + the first n words exactly as written
    const re = new RegExp(`^\\s*${words.slice(0, n).map(x => x.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('\\s+')}`);
    return { chapter, consumed: re.exec(rest)?.[0].length ?? 0, byName: true };
  }
  return null;
}

function namedMatches(text: string): Raw[] {
  const out: Raw[] = [];
  for (const kw of text.matchAll(KEYWORD)) {
    const kwEnd = kw.index + kw[0].length;
    const rest = text.slice(kwEnd, kwEnd + 120);
    const surahWord = !/chapter/i.test(kw[0]);
    const ref = resolveSurahAfter(rest);
    if (!ref) continue;
    const tail = TAIL.exec(rest.slice(ref.consumed));
    const notes: string[] = [];
    if (!tail) {
      if (!ref.byName && /^\s*:\s*\d/.test(rest.slice(ref.consumed))) continue; // "Surah 2:255": the numeric pattern owns it
      // Surah named without a verse. Bare "chapter 3" is too ambiguous; require a name, or the word surah + number.
      if (ref.byName || surahWord) {
        out.push({ chapter: ref.chapter, start: 0, end: 0, span: text.slice(kw.index, kwEnd + ref.consumed), index: kw.index, endIndex: kwEnd + ref.consumed, kind: 'surah_mention', notes });
      }
      continue;
    }
    let start: number;
    let end: number;
    if (tail[1]) {
      start = Number(tail[1]);
      end = rangeEnd(start, tail[2]);
    } else {
      if (Number(tail[3]) !== ref.chapter) notes.push(`name/number disagree: surah resolved to ${ref.chapter}, text says ${tail[3]}`);
      start = Number(tail[4]);
      end = rangeEnd(start, tail[5]);
    }
    const endIndex = kwEnd + ref.consumed + tail[0].length;
    out.push({ chapter: ref.chapter, start, end, span: text.slice(kw.index, endIndex), index: kw.index, endIndex, kind: 'named', notes });
  }
  return out;
}

function reverseMatches(text: string): Raw[] {
  const out: Raw[] = [];
  for (const m of text.matchAll(REVERSE)) {
    const afterKw = m.index + m[0].length;
    const ref = resolveSurahAfter(text.slice(afterKw, afterKw + 120));
    if (!ref) continue;
    const start = Number(m[1]);
    const endIndex = afterKw + ref.consumed;
    out.push({ chapter: ref.chapter, start, end: rangeEnd(start, m[2]), span: text.slice(m.index, endIndex), index: m.index, endIndex, kind: 'named', notes: ['verse-first word order'] });
  }
  return out;
}

function arabicBracketMatches(text: string): Raw[] {
  const out: Raw[] = [];
  for (const m of text.matchAll(ARABIC_BRACKET)) {
    const chapter = surahNumberFromName(m[1]);
    if (!chapter) continue;
    const start = Number(m[2]);
    out.push({ chapter, start, end: rangeEnd(start, m[3]), span: m[0], index: m.index, endIndex: m.index + m[0].length, kind: 'named', notes: ['bracketed Arabic name'] });
  }
  return out;
}

function aliasMatches(text: string): Raw[] {
  const out: Raw[] = [];
  for (const a of ALIASES) {
    for (const m of text.matchAll(a.re)) {
      out.push({ chapter: a.chapter, start: a.start, end: a.end, span: m[0], index: m.index, endIndex: m.index + m[0].length, kind: 'alias', notes: ['famous-name alias'] });
    }
  }
  return out;
}

/** Find candidate Quran references. Overlaps are resolved in favour of the longest span. */
export function extractCandidates(text: string): Candidate[] {
  const { norm, map } = canonicalize(text);
  const raw = [...namedMatches(norm), ...reverseMatches(norm), ...arabicBracketMatches(norm), ...numericMatches(norm), ...aliasMatches(norm)];
  raw.sort((a, b) => b.endIndex - b.index - (a.endIndex - a.index) || a.index - b.index);
  const kept: Raw[] = [];
  for (const r of raw) {
    if (!kept.some(k => r.index < k.endIndex && k.index < r.endIndex)) kept.push(r);
  }
  kept.sort((a, b) => a.index - b.index);
  return kept.map((r, id) => {
    const index = map[r.index];
    const endIndex = map[r.endIndex];
    const err = r.kind === 'surah_mention' ? (surahByNumber(r.chapter) ? null : `chapter ${r.chapter} is not in 1..114`) : validateReference(r.chapter, r.start, r.end);
    return {
      ...r,
      id,
      index,
      endIndex,
      span: text.slice(index, endIndex),
      contextWindow: text.slice(Math.max(0, index - CONTEXT_CHARS), Math.min(text.length, endIndex + CONTEXT_CHARS)),
      valid: err === null,
      ...(err ? { invalidReason: err } : {}),
    };
  });
}
