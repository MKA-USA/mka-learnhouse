/**
 * Plain-code extraction of likely Quran references from free text.
 * The model never generates references; it only judges the ones found here.
 * All numbers are in standard citation numbering (Bismillah not counted).
 */
import { surahNumberFromName, validateReference } from './surahs.js';

export type CandidateKind = 'numeric' | 'named' | 'alias';

export interface Candidate {
  /** Stable index within this text, in order of appearance. */
  id: number;
  chapter: number;
  start: number;
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

const DASH = String.raw`(?:-|–|—|to)`;

// 2:255, 2:255-257, Quran 2:255, Q2:255, Q. 2:255, (Qur'an 2:255)
const NUMERIC = new RegExp(
  String.raw`(\b(?:Qur['’]?an|Quran|Koran|Q)\.?\s*[,:]?\s*)?(\d{1,3})\s*:\s*(\d{1,3})(?:\s*[-–—]\s*(\d{1,3}))?(?!\d|:\d)`,
  'gi',
);

const KEYWORD = /\b(?:surah|surat|sura|chapter)\b\.?/gi;
const WORDS = /^\s+([A-Za-z'’\-]+(?:\s+[A-Za-z'’\-]+){0,2})/;
const NUMBER_AFTER_KEYWORD = /^\s+(\d{1,3})\b/;
const TAIL = new RegExp(
  String.raw`^\s*[,;:(]?\s*(?:(?:verses?|ayah|ayat|ayahs|vv?)\.?\s*(\d{1,3})(?:\s*${DASH}\s*(\d{1,3}))?|\(?\s*(\d{1,3})\s*:\s*(\d{1,3})(?:\s*[-–—]\s*(\d{1,3}))?\)?)`,
  'i',
);

const ALIASES: { re: RegExp; chapter: number; start: number; end: number }[] = [
  { re: /\b(?:ayat(?:ul|\s+al|\s+ul)?[-\s]*kursi|throne\s+verse)\b/gi, chapter: 2, start: 255, end: 255 },
  { re: /\bayat(?:un|\s+an|\s+un)?[-\s]*nur\b/gi, chapter: 24, start: 35, end: 35 },
];

function context(text: string, index: number, endIndex: number): string {
  return text.slice(Math.max(0, index - CONTEXT_CHARS), Math.min(text.length, endIndex + CONTEXT_CHARS));
}

type Raw = Omit<Candidate, 'id' | 'contextWindow' | 'valid' | 'invalidReason'>;

function numericMatches(text: string): Raw[] {
  const out: Raw[] = [];
  for (const m of text.matchAll(NUMERIC)) {
    const prefix = m[1] ?? '';
    const numStart = m.index + prefix.length;
    // A bare number must not be glued to a preceding digit/colon/dot/slash (e.g. 12:30:45, 1.2:3).
    if (!prefix && numStart > 0 && /[\d:.\/]/.test(text[numStart - 1])) continue;
    const chapter = Number(m[2]);
    const start = Number(m[3]);
    const end = m[4] ? Number(m[4]) : start;
    out.push({ chapter, start, end, span: m[0], index: m.index, endIndex: m.index + m[0].length, kind: 'numeric', notes: [] });
  }
  return out;
}

function namedMatches(text: string): Raw[] {
  const out: Raw[] = [];
  for (const kw of text.matchAll(KEYWORD)) {
    const kwEnd = kw.index + kw[0].length;
    const rest = text.slice(kwEnd, kwEnd + 120);
    let chapter: number | null = null;
    let consumed = 0;
    const notes: string[] = [];

    const num = NUMBER_AFTER_KEYWORD.exec(rest);
    if (num) {
      chapter = Number(num[1]);
      consumed = num[0].length;
    } else {
      const w = WORDS.exec(rest);
      if (!w) continue;
      const words = w[1].split(/\s+/);
      for (let n = words.length; n >= 1 && chapter === null; n--) {
        const phrase = words.slice(0, n).join(' ');
        const hit = surahNumberFromName(phrase);
        if (hit) {
          chapter = hit;
          // consumed = leading whitespace + the n words as they appear in the text
          const lead = rest.length - rest.trimStart().length;
          const re = new RegExp(`^\\s*${words.slice(0, n).map(x => x.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('\\s+')}`);
          consumed = re.exec(rest)?.[0].length ?? lead + phrase.length;
        }
      }
      if (chapter === null) continue;
    }

    const tail = TAIL.exec(rest.slice(consumed));
    if (!tail) continue; // surah mentioned without a verse: not a verse citation
    let start: number;
    let end: number;
    if (tail[1]) {
      start = Number(tail[1]);
      end = tail[2] ? Number(tail[2]) : start;
    } else {
      const statedChapter = Number(tail[3]);
      if (statedChapter !== chapter) notes.push(`name/number disagree: surah resolved to ${chapter}, text says ${statedChapter}`);
      start = Number(tail[4]);
      end = tail[5] ? Number(tail[5]) : start;
    }
    const index = kw.index;
    const endIndex = kwEnd + consumed + tail[0].length;
    out.push({ chapter, start, end, span: text.slice(index, endIndex), index, endIndex, kind: 'named', notes });
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
  const raw = [...namedMatches(text), ...numericMatches(text), ...aliasMatches(text)];
  raw.sort((a, b) => b.endIndex - b.index - (a.endIndex - a.index) || a.index - b.index);
  const kept: Raw[] = [];
  for (const r of raw) {
    if (!kept.some(k => r.index < k.endIndex && k.index < r.endIndex)) kept.push(r);
  }
  kept.sort((a, b) => a.index - b.index);
  return kept.map((r, id) => {
    const err = validateReference(r.chapter, r.start, r.end);
    return { ...r, id, contextWindow: context(text, r.index, r.endIndex), valid: err === null, ...(err ? { invalidReason: err } : {}) };
  });
}
