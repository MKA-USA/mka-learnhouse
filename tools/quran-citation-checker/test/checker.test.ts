import { describe, expect, it } from 'vitest';
import { extractCandidates } from '../src/candidates.js';
import { SURAHS, TOTAL_VERSES, surahNumberFromName, validateReference } from '../src/surahs.js';
import { decide, DEFAULT_THRESHOLDS, type JevLike } from '../src/judge.js';
import { fetchVerses, parseEditions, type QuranLike } from '../src/fetch.js';
import { compareQuote, extractQuotedText } from '../src/quote.js';
import { checkText } from '../src/index.js';

const ref = (t: string) => extractCandidates(t).map(c => `${c.chapter}:${c.start}-${c.end}`);

describe('surahs', () => {
  it('has 114 surahs and 6236 verses', () => {
    expect(SURAHS).toHaveLength(114);
    expect(TOTAL_VERSES).toBe(6236);
    SURAHS.forEach((s, i) => expect(s.number).toBe(i + 1));
  });
  it('maps name variants', () => {
    for (const n of ['Al-Baqarah', 'al-baqara', 'Baqarah', 'Baqara', 'AL BAQARAH']) expect(surahNumberFromName(n)).toBe(2);
    expect(surahNumberFromName("An-Nisa'")).toBe(4);
    expect(surahNumberFromName('Ar-Rahman')).toBe(55);
    expect(surahNumberFromName('Al Imran')).toBe(3);
    expect(surahNumberFromName('Ya-Sin')).toBe(36);
    expect(surahNumberFromName('Al-Ikhlas')).toBe(112);
    expect(surahNumberFromName('Genesis')).toBeNull();
  });
  it('validates bounds', () => {
    expect(validateReference(2, 255, 255)).toBeNull();
    expect(validateReference(115, 1, 1)).toMatch(/not in 1..114/);
    expect(validateReference(1, 8, 8)).toMatch(/out of range/);
    expect(validateReference(2, 257, 255)).toMatch(/before start/);
  });
});

describe('candidate extraction', () => {
  it('numeric forms', () => {
    expect(ref('Allah says in Quran 2:255 that')).toEqual(['2:255-255']);
    expect(ref('(Quran 2:255)')).toEqual(['2:255-255']);
    expect(ref('see Q2:255 and Q. 3:18')).toEqual(['2:255-255', '3:18-18']);
    expect(ref("Qur'an 2:255-257")).toEqual(['2:255-257']);
    expect(ref('2:255–257')).toEqual(['2:255-257']);
  });
  it('named forms', () => {
    expect(ref('Surah Al-Baqarah verse 255')).toEqual(['2:255-255']);
    expect(ref('Surah al-Baqarah, verse 255')).toEqual(['2:255-255']);
    expect(ref('Surah al-Baqarah 2:255')).toEqual(['2:255-255']);
    expect(ref('Chapter 2 verse 255')).toEqual(['2:255-255']);
    expect(ref('Surah Al Imran, verses 18-20')).toEqual(['3:18-20']);
  });
  it('named span covers whole phrase and numeric duplicate is not double counted', () => {
    const c = extractCandidates('As in Surah al-Baqarah 2:255.');
    expect(c).toHaveLength(1);
    expect(c[0].span).toBe('Surah al-Baqarah 2:255');
  });
  it('alias', () => {
    expect(ref('Recite Ayat al-Kursi tonight')).toEqual(['2:255-255']);
  });
  it('surah mention without verse is not a candidate', () => {
    expect(ref('We read Surah al-Kahf on Fridays')).toEqual([]);
  });
  it('time-like strings are still candidates (the judge decides), glued digits are not', () => {
    expect(ref('meet at 2:55 pm')).toEqual(['2:55-55']);
    expect(ref('at 12:30:45 sharp')).toEqual([]);
  });
  it('flags invalid references', () => {
    const [c] = extractCandidates('See 115:1');
    expect(c.valid).toBe(false);
    expect(c.invalidReason).toMatch(/not in 1..114/);
    const [d] = extractCandidates('See 1:8');
    expect(d.valid).toBe(false);
  });
  it('captures a ~200 char context window', () => {
    const t = 'a'.repeat(500) + ' Quran 2:255 ' + 'b'.repeat(500);
    const [c] = extractCandidates(t);
    expect(c.contextWindow.length).toBeLessThanOrEqual(400 + c.span.length);
    expect(c.contextWindow).toContain('Quran 2:255');
  });
});

describe('threshold logic', () => {
  const j = (p: number, kind: any = 'explicit_reference') => ({ citeProbability: p, kind, kindConfidence: 0.9, quotedProbability: 0 });
  it('accepts / rejects / reviews', () => {
    expect(decide(j(0.95))).toBe('confirmed');
    expect(decide(j(0.8))).toBe('confirmed');
    expect(decide(j(0.5))).toBe('needs_review');
    expect(decide(j(0.2))).toBe('rejected');
    expect(decide(j(0.01))).toBe('rejected');
  });
  it('is configurable', () => {
    expect(decide(j(0.6), { accept: 0.5, reject: 0.1 })).toBe('confirmed');
    expect(DEFAULT_THRESHOLDS).toEqual({ accept: 0.8, reject: 0.2 });
  });
  it('kind=not_a_citation downgrades a confirmation', () => {
    expect(decide(j(0.95, 'not_a_citation'))).toBe('needs_review');
  });
});

// ---- stubs ----
function stubJev(cite: number, kind = 'explicit_reference', quoted = 0): JevLike & { calls: number } {
  const s = {
    calls: 0,
    systemOne: async () => {
      s.calls++;
      return { answers: { cite: { type: 'noul', noul: cite }, kind: { type: 'choice', choice: kind, confidence: 0.9 }, quoted: { type: 'noul', noul: quoted } } };
    },
  };
  return s;
}
function stubQuran(): QuranLike & { requests: number[][] } {
  const s = {
    requests: [] as number[][],
    getVersesWithMeta: async (ch: number, a: number, b: number) => {
      s.requests.push([ch, a, b]);
      if (ch === 1 && b > 7) throw new Error('Upstream rejected the request (HTTP 400); check chapter/verse reference');
      const off = ch === 1 || ch === 9 ? 0 : 1;
      const verses = [];
      for (let v = a; v <= b; v++) verses.push({ v, v_: v - off, arabic: `AR${ch}:${v - off}`, translations: { en: { text: `Allah — there is no God but He, the Living, the Self-Subsisting and All-Sustaining. [${ch}:${v - off}]` } } });
      return { retrievedAt: '2026-01-01T00:00:00.000Z', verses };
    },
  };
  return s;
}

describe('fetch', () => {
  it('maps cited numbering to Al Islam numbering and verifies v_', async () => {
    const q = stubQuran();
    const r = await fetchVerses(q, 2, 255, 257, ['en']);
    expect(q.requests).toEqual([[2, 256, 258]]);
    expect(r.ok).toBe(true);
    expect(r.verses.map(v => v.citedVerse)).toEqual([255, 256, 257]);
    expect(r.verses[0].arabic).toBe('AR2:255');
    expect(r.warnings).toEqual([]);
  });
  it('no offset for chapters 1 and 9', async () => {
    const q = stubQuran();
    await fetchVerses(q, 9, 129, 129);
    await fetchVerses(q, 1, 7, 7);
    expect(q.requests).toEqual([[9, 129, 129], [1, 7, 7]]);
  });
  it('reports RangeError / HTTP 400 as invalid reference', async () => {
    const r = await fetchVerses({ getVersesWithMeta: async () => { throw new RangeError('chapter must be an integer from 1 to 114'); } }, 115, 1, 1);
    expect(r.ok).toBe(false);
    expect(r.error).toMatch(/^invalid reference/);
    const r2 = await fetchVerses(stubQuran(), 1, 8, 8);
    expect(r2.error).toMatch(/^invalid reference/);
  });
  it('parses editions', () => {
    expect(parseEditions('en,ur')).toEqual(['en', 'ur']);
    expect(() => parseEditions('xx')).toThrow(/Unknown edition/);
  });
});

describe('quote heuristic', () => {
  it('extracts and compares', () => {
    const ctx = 'He said, "Allah — there is no God but He, the Living, the Self-Subsisting" in 2:255.';
    const q = extractQuotedText(ctx)!;
    expect(q).toContain('the Living');
    expect(compareQuote(q, 'Allah — there is no God but He, the Living, the Self-Subsisting and All-Sustaining.').quoteMatch).toBe(true);
    expect(compareQuote(q, 'Completely different words about patience and prayer here.').quoteMatch).toBe(false);
  });
});

describe('checkText with stubs', () => {
  it('confirms "Allah says in Quran 2:255" and fetches', async () => {
    const jev = stubJev(0.97);
    const quran = stubQuran();
    const out = await checkText('Allah says in Quran 2:255 that He is the Ever-Living.', { jev, quran });
    expect(out.containsCitation).toBe(true);
    expect(out.results[0].verdict).toBe('confirmed');
    expect(out.results[0].fetched?.verses[0].arabic).toBe('AR2:255');
  });
  it('confirms a named citation', async () => {
    const out = await checkText('Surah Al-Baqarah verse 255 is the greatest.', { jev: stubJev(0.95), quran: stubQuran() });
    expect(out.results[0].candidate.chapter).toBe(2);
    expect(out.results[0].verdict).toBe('confirmed');
  });
  it('rejects "meet at 2:55 pm": parsed but judged not a citation, no fetch', async () => {
    const quran = stubQuran();
    const out = await checkText('Lets meet at 2:55 pm.', { jev: stubJev(0.03, 'not_a_citation'), quran });
    expect(out.results).toHaveLength(1);
    expect(out.results[0].verdict).toBe('rejected');
    expect(out.containsCitation).toBe(false);
    expect(quran.requests).toEqual([]);
  });
  it('fetches the full range 2:255-257', async () => {
    const quran = stubQuran();
    const out = await checkText('Read Quran 2:255-257.', { jev: stubJev(0.9), quran });
    expect(out.results[0].fetched?.verses).toHaveLength(3);
  });
  it('invalid 115:1 skips Jev and fetch, reports invalid_reference', async () => {
    const jev = stubJev(0.99);
    const quran = stubQuran();
    const out = await checkText('See 115:1.', { jev, quran });
    expect(out.results[0].verdict).toBe('invalid_reference');
    expect(jev.calls).toBe(0);
    expect(quran.requests).toEqual([]);
  });
  it('needs_review in the middle band, and no fetch', async () => {
    const quran = stubQuran();
    const out = await checkText('Chapter 3 verse 5 says', { jev: stubJev(0.5), quran });
    expect(out.results[0].verdict).toBe('needs_review');
    expect(quran.requests).toEqual([]);
  });
  it('judge failure becomes needs_review, not a crash', async () => {
    const jev: JevLike = { systemOne: async () => { throw new Error('boom'); } };
    const out = await checkText('Quran 2:255', { jev, quran: stubQuran() });
    expect(out.results[0].verdict).toBe('needs_review');
    expect(out.results[0].error).toMatch(/boom/);
  });
  it('quote check runs only when Jev says quoted', async () => {
    const text = 'Quran 2:255: "Allah — there is no God but He, the Living, the Self-Subsisting"';
    const out = await checkText(text, { jev: stubJev(0.95, 'quoted_verse_with_reference', 0.9), quran: stubQuran() });
    expect(out.results[0].quoteChecks?.some(c => c.quoteMatch)).toBe(true);
    const out2 = await checkText(text, { jev: stubJev(0.95, 'explicit_reference', 0.1), quran: stubQuran() });
    expect(out2.results[0].quoteChecks).toBeUndefined();
  });
});
