/** Heuristic (no model) comparison of a quoted passage against a fetched translation. */

const QUOTE_PATTERNS = [/“([^”]{20,})”/g, /"([^"]{20,})"/g, /‘([^’]{20,})’/g];

/** Longest quote-marked passage (>= 20 chars) in the context window, or null. */
export function extractQuotedText(context: string): string | null {
  let best: string | null = null;
  for (const re of QUOTE_PATTERNS) {
    for (const m of context.matchAll(re)) if (!best || m[1].length > best.length) best = m[1];
  }
  return best;
}

export interface Passage {
  text: string;
  index: number;
  endIndex: number;
  language: 'arabic' | 'english';
}

const ARABIC_CH = String.raw`[\u0600-\u06FF\uFB50-\uFDFF\uFE70-\uFEFF]`;
/** Arabic-script run of at least 4 whitespace-separated words. */
const ARABIC_RUN = new RegExp(String.raw`${ARABIC_CH}+(?:\s+${ARABIC_CH}+){3,}`, 'g');

/** Quote-marked English passages (>= 20 chars, >= 3 Latin words) and Arabic runs (>= 4 words), in text order. */
export function findQuotedPassages(text: string): Passage[] {
  const out: Passage[] = [];
  for (const m of text.matchAll(ARABIC_RUN)) out.push({ text: m[0], index: m.index, endIndex: m.index + m[0].length, language: 'arabic' });
  for (const re of QUOTE_PATTERNS) {
    for (const m of text.matchAll(re)) {
      const inner = m[1];
      if ((inner.match(/[A-Za-z]+/g) ?? []).length < 3) continue;
      const index = m.index + 1;
      if (out.some(p => index < p.endIndex && p.index < index + inner.length)) continue;
      out.push({ text: inner, index, endIndex: index + inner.length, language: 'english' });
    }
  }
  return out.sort((a, b) => a.index - b.index);
}

export function normalizeForCompare(s: string): string {
  return s
    .replace(/\[[A-Za-z0-9]+\]/g, '') // footnote markers like [a], [1]
    .normalize('NFKD')
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s]/gu, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

export interface QuoteComparison {
  quoted: string;
  translation: string;
  contained: boolean;
  /** token Jaccard similarity of quoted vs translation, 0..1 */
  similarity: number;
  quoteMatch: boolean;
  heuristic: true;
}

export function compareQuote(quoted: string, translation: string, minSimilarity = 0.6): QuoteComparison {
  const q = normalizeForCompare(quoted);
  const t = normalizeForCompare(translation);
  const contained = q.length > 0 && t.length > 0 && (t.includes(q) || q.includes(t));
  const qs = new Set(q.split(' ').filter(Boolean));
  const ts = new Set(t.split(' ').filter(Boolean));
  let inter = 0;
  for (const w of qs) if (ts.has(w)) inter++;
  const union = qs.size + ts.size - inter;
  const similarity = union === 0 ? 0 : inter / union;
  return { quoted, translation, contained, similarity, quoteMatch: contained || similarity >= minSimilarity, heuristic: true };
}
