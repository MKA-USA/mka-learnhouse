/**
 * Unreferenced quotes: a quoted passage (Arabic run >= 4 words, or an English quote)
 * with no parsed reference near it. We search Al Islam for the best hits and have Jev
 * judge whether the passage matches each verse. NEVER auto-confirms: the best result is
 * `needs_review` with proposed references; a human decides.
 *
 * Costs upstream calls (1 search + up to MAX_HITS verse fetches per passage), so it is
 * opt-in and capped at MAX_PASSAGES. Calls are sequential; the client also queues to
 * at most 2 concurrent requests.
 */
import type { Edition } from 'alislam-quran';
import { CONTEXT_CHARS, type Candidate } from './candidates.js';
import { fetchVerses, type FetchResult, type QuranLike } from './fetch.js';
import { judgePassageMatches, type JevLike, type PassageHit, type Thresholds } from './judge.js';
import { findQuotedPassages, type Passage } from './quote.js';

export const MAX_HITS = 3;
export const MAX_PASSAGES = 5;
const MAX_QUERY_CHARS = 300;

export interface Proposal {
  chapter: number;
  verse: number; // standard numbering
  matchProbability: number;
  fetched: FetchResult;
}

export interface UnreferencedResult {
  passage: Passage;
  /** needs_review: some proposal exceeds the reject threshold. no_match: nothing plausible (or search failed). Never "confirmed". */
  verdict: 'needs_review' | 'no_match';
  searchMode: 'keyword' | 'semantic';
  proposals: Proposal[];
  error?: string;
}

/** Passages with no candidate span within CONTEXT_CHARS of them. */
export function unreferencedPassages(text: string, nearCandidates: Candidate[]): Passage[] {
  return findQuotedPassages(text).filter(
    p => !nearCandidates.some(c => p.index < c.endIndex + CONTEXT_CHARS && c.index < p.endIndex + CONTEXT_CHARS),
  );
}

export async function resolveUnreferenced(
  jev: JevLike,
  quran: QuranLike,
  passages: Passage[],
  editions: Edition[],
  thresholds: Thresholds,
  numberingMap = true,
): Promise<UnreferencedResult[]> {
  const out: UnreferencedResult[] = [];
  const fetchEditions: Edition[] = editions.includes('en') ? editions : ['en', ...editions];
  for (const passage of passages.slice(0, MAX_PASSAGES)) {
    const searchMode = passage.language === 'arabic' ? 'keyword' : 'semantic';
    const base: UnreferencedResult = { passage, verdict: 'no_match', searchMode, proposals: [] };
    try {
      if (!quran.search) throw new Error('quran client has no search()');
      const query = passage.text.replace(/\s+/g, ' ').slice(0, MAX_QUERY_CHARS);
      const res = await quran.search(query, searchMode, ['en']);
      const rows = Array.isArray(res.verses) ? (res.verses as Record<string, unknown>[]) : [];
      const seen = new Set<string>();
      const refs: { chapter: number; verse: number }[] = [];
      for (const r of rows) {
        const chapter = Number(r.ch);
        const verse = Number(r.v_ ?? r.v); // v_ is standard numbering
        const key = `${chapter}:${verse}`;
        if (!Number.isInteger(chapter) || !Number.isInteger(verse) || verse < 1 || seen.has(key)) continue;
        seen.add(key);
        refs.push({ chapter, verse });
        if (refs.length === MAX_HITS) break;
      }
      if (!refs.length) {
        out.push(base);
        continue;
      }
      const fetched: FetchResult[] = [];
      for (const r of refs) fetched.push(await fetchVerses(quran, r.chapter, r.verse, r.verse, fetchEditions, numberingMap));
      const usable = refs.map((r, i) => ({ r, f: fetched[i] })).filter(x => x.f.ok && x.f.verses.length > 0);
      if (!usable.length) {
        out.push({ ...base, error: 'search returned hits but fetching them failed' });
        continue;
      }
      const hits: PassageHit[] = usable.map(({ r, f }) => ({ chapter: r.chapter, verse: r.verse, arabic: f.verses[0].arabic, translation: f.verses[0].translations.en ?? '' }));
      const probs = await judgePassageMatches(jev, passage.text, hits);
      const proposals = usable
        .map(({ r, f }, i) => ({ chapter: r.chapter, verse: r.verse, matchProbability: probs[i], fetched: f }))
        .sort((a, b) => b.matchProbability - a.matchProbability);
      out.push({ ...base, proposals, verdict: proposals[0].matchProbability > thresholds.reject ? 'needs_review' : 'no_match' });
    } catch (e) {
      out.push({ ...base, error: e instanceof Error ? e.message : String(e) });
    }
  }
  return out;
}
