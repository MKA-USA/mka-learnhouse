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
