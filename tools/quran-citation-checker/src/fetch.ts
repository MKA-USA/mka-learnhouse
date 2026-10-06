/**
 * Fetch official Arabic + translations from Al Islam via the alislam-quran client.
 *
 * Numbering: people cite the standard way (2:255 = Ayat al-Kursi). Al Islam's `v`
 * counts the Bismillah as verse 1 in every chapter except 1 and 9 (`v_` is 0 for
 * that Bismillah row and matches standard numbering afterwards). So a cited verse N
 * is requested as Al Islam verse N+1 for chapters other than 1 and 9, and every
 * returned row is verified against `v_ === N` (live check, 2026-10-04: request
 * 2:255 returns v=255/v_=254, i.e. standard 2:254). Rows are returned unmodified;
 * both `v` and `v_` are exposed so nothing is relabelled.
 */
import { AlIslamQuranClient } from 'alislam-quran';
import type { Edition } from 'alislam-quran';

export const SOURCE = 'Al Islam (api.readquran.app)';
export const KNOWN_EDITIONS = ['en', 'zk', 'ur', 'sc', 'v5', 'sp_en', 'sp_ur'] as const;

export interface QuranLike {
  getVersesWithMeta(chapter: number, start: number, end: number, editions: Edition[]): Promise<{ retrievedAt: string; verses: Record<string, unknown>[] }>;
  /** Only needed for the unreferenced-quote search. */
  search?(query: string, mode: 'keyword' | 'semantic', editions?: Edition[]): Promise<Record<string, unknown>>;
}

export interface FetchedVerse {
  /** Verse number in standard citation numbering (= Al Islam v_). */
  citedVerse: number;
  alIslamV: unknown;
  alIslamVUnderscore: unknown;
  /** Arabic exactly as returned upstream. */
  arabic: string;
  /** edition -> text (raw upstream text, unsanitized). */
  translations: Record<string, string>;
}

export interface FetchResult {
  ok: boolean;
  error?: string;
  retrievedAt?: string;
  source: string;
  verses: FetchedVerse[];
  warnings: string[];
}

export function parseEditions(csv: string): Edition[] {
  const list = csv.split(',').map(s => s.trim()).filter(Boolean);
  const bad = list.filter(e => !(KNOWN_EDITIONS as readonly string[]).includes(e));
  if (!list.length || bad.length) throw new Error(`Unknown edition(s): ${bad.join(', ') || '(none given)'}. Known: ${KNOWN_EDITIONS.join(', ')}`);
  return list as Edition[];
}

export function alIslamOffset(chapter: number): number {
  return chapter === 1 || chapter === 9 ? 0 : 1;
}

function translationsOf(row: Record<string, unknown>, editions: Edition[]): Record<string, string> {
  const out: Record<string, string> = {};
  const t = row.translations;
  if (Array.isArray(t)) {
    for (const x of t) if (x && typeof x === 'object') out[String((x as any).edition)] = String((x as any).text ?? '');
  } else if (t && typeof t === 'object') {
    for (const [k, v] of Object.entries(t as Record<string, any>)) out[k] = typeof v === 'string' ? v : String(v?.text ?? '');
  }
  for (const e of editions) if (!(e in out) && row[e] !== undefined) out[e] = typeof row[e] === 'string' ? (row[e] as string) : String((row[e] as any)?.text ?? '');
  return out;
}

export async function fetchVerses(
  client: QuranLike,
  chapter: number,
  start: number,
  end: number,
  editions: Edition[] = ['en'],
  numberingMap = true,
): Promise<FetchResult> {
  const warnings: string[] = [];
  const off = numberingMap ? alIslamOffset(chapter) : 0;
  try {
    const { retrievedAt, verses } = await client.getVersesWithMeta(chapter, start + off, end + off, editions);
    let rows = verses;
    if (numberingMap) {
      rows = verses.filter(r => Number(r.v_) >= start && Number(r.v_) <= end);
      if (rows.length !== end - start + 1) warnings.push(`expected ${end - start + 1} verse(s) with v_ in ${start}..${end}, got ${rows.length}; check numbering`);
    } else if (alIslamOffset(chapter) !== 0) {
      warnings.push('numbering map disabled: verse numbers are Al Islam numbering (Bismillah = verse 1), off by one from standard citations');
    }
    return {
      ok: true,
      retrievedAt,
      source: SOURCE,
      warnings,
      verses: rows.map(r => ({
        citedVerse: Number(numberingMap ? r.v_ : r.v),
        alIslamV: r.v,
        alIslamVUnderscore: r.v_,
        arabic: String(r.arabic ?? r.ar ?? ''),
        translations: translationsOf(r, editions),
      })),
    };
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    const invalid = e instanceof RangeError || /HTTP 400/.test(msg);
    return { ok: false, error: invalid ? `invalid reference: ${msg}` : msg, source: SOURCE, verses: [], warnings };
  }
}

export function createQuranClient(): AlIslamQuranClient {
  return new AlIslamQuranClient({ timeoutMs: 15_000 });
}
