import type { Edition } from 'alislam-quran';
import { extractCandidates, type Candidate } from './candidates.js';
import { createQuranClient, fetchVerses, type FetchResult, type QuranLike } from './fetch.js';
import { createJevClient, decide, DEFAULT_THRESHOLDS, judgeCandidate, type JevLike, type Judgement, type Thresholds, type Verdict } from './judge.js';
import { compareQuote, extractQuotedText, type QuoteComparison } from './quote.js';

export * from './candidates.js';
export * from './surahs.js';
export * from './judge.js';
export * from './fetch.js';
export * from './quote.js';

export type FinalVerdict = Verdict | 'invalid_reference';

export interface CandidateResult {
  candidate: Candidate;
  verdict: FinalVerdict;
  judgement?: Judgement;
  /** Present for confirmed candidates. */
  fetched?: FetchResult;
  /** Heuristic only; present when Jev says a verse text is quoted and one was found. */
  quoteChecks?: QuoteComparison[];
  /** Errors from judging (the candidate then needs review). */
  error?: string;
}

export interface CheckOptions {
  editions?: Edition[];
  thresholds?: Thresholds;
  /** Injectable for tests; defaults are created from env / real client. */
  jev?: JevLike;
  quran?: QuranLike;
}

export async function checkText(text: string, opts: CheckOptions = {}): Promise<{ containsCitation: boolean; results: CandidateResult[] }> {
  const candidates = extractCandidates(text);
  const editions = opts.editions ?? ['en'];
  const thresholds = opts.thresholds ?? DEFAULT_THRESHOLDS;
  const needsJev = candidates.some(c => c.valid);
  const jev = needsJev ? (opts.jev ?? createJevClient()) : undefined;
  const quran = opts.quran ?? createQuranClient();

  const results = await Promise.all(
    candidates.map(async (c): Promise<CandidateResult> => {
      if (!c.valid) return { candidate: c, verdict: 'invalid_reference' };
      let judgement: Judgement;
      try {
        judgement = await judgeCandidate(jev!, c);
      } catch (e) {
        return { candidate: c, verdict: 'needs_review', error: `judge failed: ${e instanceof Error ? e.message : String(e)}` };
      }
      const verdict = decide(judgement, thresholds);
      if (verdict !== 'confirmed') return { candidate: c, verdict, judgement };

      const fetched = await fetchVerses(quran, c.chapter, c.start, c.end, editions);
      const result: CandidateResult = { candidate: c, verdict, judgement, fetched };
      if (!fetched.ok && /invalid reference/.test(fetched.error ?? '')) result.verdict = 'invalid_reference';
      if (fetched.ok && judgement.quotedProbability >= thresholds.accept) {
        const quoted = extractQuotedText(c.contextWindow);
        if (quoted) {
          const checks: QuoteComparison[] = [];
          for (const v of fetched.verses) for (const t of Object.values(v.translations)) checks.push(compareQuote(quoted, t));
          // Also compare against the whole range joined, for multi-verse quotes.
          if (fetched.verses.length > 1) for (const ed of editions) checks.push(compareQuote(quoted, fetched.verses.map(v => v.translations[ed] ?? '').join(' ')));
          result.quoteChecks = checks;
        }
      }
      return result;
    }),
  );
  return { containsCitation: results.some(r => r.verdict === 'confirmed'), results };
}
