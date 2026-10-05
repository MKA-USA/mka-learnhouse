/**
 * Jev (TypeSafe System One) judgement of whether a regex-found candidate really
 * cites the Quran. One systemOne request per candidate, three independent
 * questions over the same state. Question IDs are not sent to the model, so each
 * question carries its full meaning in its own text.
 */
import { choice, noul, TypeSafeClient } from '@typesafe-ai/sdk';
import type { Candidate } from './candidates.js';

/** UNTUNED defaults. Calibrate against labelled examples before relying on them. */
export interface Thresholds {
  /** cite probability >= accept  => confirmed */
  accept: number;
  /** cite probability <= reject  => rejected; in between => needs_review */
  reject: number;
}
export const DEFAULT_THRESHOLDS: Thresholds = { accept: 0.8, reject: 0.2 };

export const CITATION_KINDS = ['explicit_reference', 'quoted_verse_with_reference', 'passing_mention', 'not_a_citation'] as const;
export type CitationKind = (typeof CITATION_KINDS)[number];

export type Verdict = 'confirmed' | 'needs_review' | 'rejected';

export interface Judgement {
  /** Probability that the span cites a Quran verse (Jev noul). */
  citeProbability: number;
  kind: CitationKind;
  kindConfidence: number;
  /** Probability that a verse text is quoted alongside the reference (Jev noul). */
  quotedProbability: number;
}

/** The slice of TypeSafeClient we use; lets tests inject a stub. */
export interface JevLike {
  systemOne(req: { state: unknown; questions: Record<string, unknown> }): PromiseLike<{ answers: Record<string, any> }>;
}

export function createJevClient(): TypeSafeClient {
  if (!process.env.TYPESAFE_API_KEY) {
    throw new Error('TYPESAFE_API_KEY is not set. Export it in your environment to use the Jev judge (the key is never printed or stored).');
  }
  return new TypeSafeClient(); // reads TYPESAFE_API_KEY; default model jev-latest
}

export async function judgeCandidate(jev: JevLike, c: Candidate): Promise<Judgement> {
  const quoted = JSON.stringify(c.span);
  const ref = `${c.chapter}:${c.start}${c.end !== c.start ? `-${c.end}` : ''}`;
  const state = {
    text_excerpt: c.contextWindow,
    candidate_span: c.span,
    parsed_reference: { chapter: c.chapter, first_verse: c.start, last_verse: c.end, as_text: ref },
  };
  const res = await jev.systemOne({
    state,
    questions: {
      cite: noul(
        `In text_excerpt, does the candidate_span ${quoted} cite a verse or passage of the Quran (the Islamic scripture) as chapter:verse? Answer no if it is something else, such as a clock time like 2:55 pm, a ratio, a sports score, a Bible verse, a page or section number, or a timestamp.`,
      ),
      kind: choice(
        `How does text_excerpt use the candidate_span ${quoted}?`,
        {
          explicit_reference: 'A bare reference to a Quran verse, with no verse text quoted.',
          quoted_verse_with_reference: 'A reference to a Quran verse together with its text quoted or closely paraphrased nearby.',
          passing_mention: 'Mentions a Quran chapter or verse only in passing.',
          not_a_citation: 'Not a Quran citation at all (a time, score, ratio, Bible verse, page number, etc.).',
        },
      ),
      quoted: noul(
        `In text_excerpt, is the wording of a verse (a quoted passage, in English or Arabic) given right next to the candidate_span ${quoted}, as opposed to the reference standing alone?`,
      ),
    },
  });
  const a = res.answers;
  return {
    citeProbability: a.cite.noul,
    kind: a.kind.choice,
    kindConfidence: a.kind.confidence,
    quotedProbability: a.quoted.noul,
  };
}

/** Pure threshold logic. */
export function decide(j: Judgement, t: Thresholds = DEFAULT_THRESHOLDS): Verdict {
  let v: Verdict = j.citeProbability >= t.accept ? 'confirmed' : j.citeProbability <= t.reject ? 'rejected' : 'needs_review';
  // Consistency guard: the kind question contradicting a confirmation needs a human.
  if (v === 'confirmed' && j.kind === 'not_a_citation') v = 'needs_review';
  return v;
}
