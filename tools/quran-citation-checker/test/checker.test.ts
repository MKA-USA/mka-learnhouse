import { describe, expect, it } from 'vitest';
import { extractCandidates } from '../src/candidates.js';
import { ARABIC_NAMES, SURAHS, TOTAL_VERSES, surahNumberFromName, validateReference } from '../src/surahs.js';
import { decide, DEFAULT_THRESHOLDS, type JevLike } from '../src/judge.js';
import { fetchVerses, parseEditions, type QuranLike } from '../src/fetch.js';
import { compareQuote, extractQuotedText } from '../src/quote.js';
import { checkText } from '../src/index.js';
import { findQuotedPassages } from '../src/quote.js';

const ref = (t: string) => extractCandidates(t).map(c => `${c.chapter}:${c.start}-${c.end}`);

describe('surahs', () => {
  it('has 114 surahs and 6236 verses', () => {
    expect(SURAHS).toHaveLength(114);
    expect(ARABIC_NAMES).toHaveLength(114);
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
  it('surah mention without verse is a verseless surah_mention candidate', () => {
    const [c] = extractCandidates('We read Surah al-Kahf on Fridays');
    expect(c.kind).toBe('surah_mention');
    expect(c.chapter).toBe(18);
    expect(c.span).toBe('Surah al-Kahf');
    expect(extractCandidates('This chapter 3 is long')).toEqual([]);
    expect(extractCandidates('Surah Genesis')).toEqual([]);
  });
  it('verse-first word order', () => {
    expect(ref('verse 255 of Surah al-Baqarah')).toEqual(['2:255-255']);
    expect(ref('ayah 255 of chapter 2')).toEqual(['2:255-255']);
    expect(ref('verses 255-257 of the Surah al-Baqarah')).toEqual(['2:255-257']);
    const c = extractCandidates('He recited verse 255 of Surah al-Baqarah today');
    expect(c).toHaveLength(1);
    expect(c[0].span).toBe('verse 255 of Surah al-Baqarah');
  });
  it('Arabic-script names and Arabic-Indic / Persian digits', () => {
    expect(ref('سورة البقرة آية ٢٥٥')).toEqual(['2:255-255']);
    expect(ref('سورة البقرة آية ۲۵۵')).toEqual(['2:255-255']);
    expect(ref('سُورَةُ الْبَقَرَةِ آيَةُ ٢٥٥')).toEqual(['2:255-255']);
    expect(ref('آية ٢٥٥ من سورة البقرة')).toEqual(['2:255-255']);
    expect(ref('قال تعالى (البقرة: ٢٥٥)')).toEqual(['2:255-255']);
    expect(ref('القرآن ٢:٢٥٥')).toEqual(['2:255-255']);
    expect(ref('سورة آل عمران آية 18')).toEqual(['3:18-18']);
    expect(extractCandidates('سورة الكهف')[0]).toMatchObject({ kind: 'surah_mention', chapter: 18 });
    expect(ref('آية الكرسي')).toEqual(['2:255-255']);
  });
  it('span refers to the original text even with diacritics', () => {
    const t = 'قال: سُورَةُ الْبَقَرَةِ آيَةُ ٢٥٥ هي';
    const [c] = extractCandidates(t);
    expect(t.slice(c.index, c.endIndex)).toBe(c.span);
    expect(c.span.startsWith('سُورَةُ')).toBe(true);
    expect(c.span.endsWith('٢٥٥')).toBe(true);
  });
  it('"Surah 2:255" is a numeric reference, not a surah mention', () => {
    const c = extractCandidates('Surah 2:255');
    expect(c).toHaveLength(1);
    expect(c[0].kind).toBe('numeric');
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
function stubJev(cite: number, kind = 'explicit_reference', quoted = 0, match: number[] = []): JevLike & { calls: number; states: any[] } {
  const s = {
    calls: 0,
    states: [] as any[],
    systemOne: async (req: { state: unknown; questions: Record<string, unknown> }) => {
      s.calls++;
      s.states.push(req.state);
      const answers: Record<string, any> = {};
      for (const k of Object.keys(req.questions)) {
        if (k === 'cite') answers.cite = { type: 'noul', noul: cite };
        else if (k === 'kind') answers.kind = { type: 'choice', choice: kind, confidence: 0.9 };
        else if (k === 'quoted') answers.quoted = { type: 'noul', noul: quoted };
        else answers[k] = { type: 'noul', noul: match[Number(k.slice(1))] ?? 0 };
      }
      return { answers };
    },
  };
  return s;
}
function stubQuran(searchRows: { ch: number; v: number; v_: number }[] = []): QuranLike & { requests: number[][]; searches: [string, string][] } {
  const s = {
    requests: [] as number[][],
    searches: [] as [string, string][],
    search: async (q: string, mode: 'keyword' | 'semantic') => {
      s.searches.push([q, mode]);
      return { verses: searchRows };
    },
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

describe('Arabic names', () => {
  it('every Arabic name resolves to its own surah number', () => {
    ARABIC_NAMES.forEach((n, i) => expect(surahNumberFromName(n)).toBe(i + 1));
  });
});

describe('surah_mention', () => {
  it('is judged by Jev but never fetches verses', async () => {
    const jev = stubJev(0.95);
    const quran = stubQuran();
    const out = await checkText('Surah Al-Kahf is read on Fridays.', { jev, quran });
    expect(jev.calls).toBe(1);
    expect(jev.states[0].parsed_reference).toMatchObject({ chapter: 18, first_verse: null });
    expect(out.results[0].verdict).toBe('surah_mention');
    expect(out.results[0].surah).toEqual({ chapter: 18, name: 'Al-Kahf' });
    expect(out.results[0].fetched).toBeUndefined();
    expect(quran.requests).toEqual([]);
    expect(out.containsCitation).toBe(false);
  });
  it('is rejected when Jev says it is not the Quran', async () => {
    const out = await checkText('Surah Al-Kahf is read on Fridays.', { jev: stubJev(0.05, 'not_a_citation'), quran: stubQuran() });
    expect(out.results[0].verdict).toBe('rejected');
  });
});

describe('numberingMap option', () => {
  it('false requests the cited numbers unchanged and warns', async () => {
    const q = stubQuran();
    const r = await fetchVerses(q, 2, 255, 255, ['en'], false);
    expect(q.requests).toEqual([[2, 255, 255]]);
    expect(r.warnings[0]).toMatch(/off by one/);
    expect(r.verses[0].citedVerse).toBe(255);
    const q2 = stubQuran();
    await checkText('Quran 2:255', { jev: stubJev(0.95), quran: q2, numberingMap: false });
    expect(q2.requests).toEqual([[2, 255, 255]]);
  });
  it('defaults to on', async () => {
    const q = stubQuran();
    await checkText('Quran 2:255', { jev: stubJev(0.95), quran: q });
    expect(q.requests).toEqual([[2, 256, 256]]);
  });
});

describe('unreferenced quotes', () => {
  const arabic = 'اَللّٰهُ لَاۤ اِلٰهَ اِلَّا هُوَ الْحَیُّ الْقَیُّوْمُ';
  const rows = [{ ch: 2, v: 256, v_: 255 }, { ch: 3, v: 3, v_: 2 }];

  it('finds Arabic runs (>= 4 words) and English quotes', () => {
    expect(findQuotedPassages(`قال ${arabic} ثم`).some(p => p.language === 'arabic')).toBe(true);
    expect(findQuotedPassages('كلمتان فقط هنا')).toEqual([]);
    const en = findQuotedPassages('He said "There is no god but He, the Living" here');
    expect(en).toHaveLength(1);
    expect(en[0].language).toBe('english');
  });
  it('is off by default: no search calls', async () => {
    const quran = stubQuran(rows);
    const out = await checkText(`قال ${arabic}`, { jev: stubJev(0.9), quran });
    expect(out.unreferenced).toBeUndefined();
    expect(quran.searches).toEqual([]);
  });
  it('Arabic uses keyword search, proposes needs_review (never confirmed), best match first, fetched attached', async () => {
    const quran = stubQuran(rows);
    const jev = stubJev(0.9, 'explicit_reference', 0, [0.3, 0.92]);
    const out = await checkText(`قال تعالى ${arabic}`, { jev, quran, findUnreferenced: true });
    expect(out.containsCitation).toBe(false);
    expect(quran.searches[0][1]).toBe('keyword');
    const u = out.unreferenced![0];
    expect(u.verdict).toBe('needs_review');
    expect(u.proposals.map(p => `${p.chapter}:${p.verse}`)).toEqual(['3:2', '2:255']);
    expect(u.proposals[0].matchProbability).toBe(0.92);
    expect(u.proposals[0].fetched.verses[0].arabic).toBe('AR3:2');
    // fetched with the cited->Al Islam mapping (2:255 -> 256, 3:2 -> 3)
    expect(quran.requests).toContainEqual([2, 256, 256]);
    expect(quran.requests).toContainEqual([3, 3, 3]);
  });
  it('English quote uses semantic search; weak matches become no_match', async () => {
    const quran = stubQuran(rows);
    const out = await checkText('He said "Allah there is no God but He the Living" to them.', { jev: stubJev(0.9, 'explicit_reference', 0, [0.05, 0.1]), quran, findUnreferenced: true });
    expect(quran.searches[0][1]).toBe('semantic');
    expect(out.unreferenced![0].verdict).toBe('no_match');
    expect(out.unreferenced![0].proposals.length).toBe(2);
  });
  it('skips passages that already have a reference nearby', async () => {
    const quran = stubQuran(rows);
    const out = await checkText(`Quran 2:255: ${arabic}`, { jev: stubJev(0.95), quran, findUnreferenced: true });
    expect(out.unreferenced).toEqual([]);
    expect(quran.searches).toEqual([]);
  });
  it('search failure is reported on the result, not thrown', async () => {
    const quran = stubQuran(rows);
    quran.search = async () => { throw new Error('upstream down'); };
    const out = await checkText(arabic, { jev: stubJev(0.9), quran, findUnreferenced: true });
    expect(out.unreferenced![0].error).toMatch(/upstream down/);
    expect(out.unreferenced![0].verdict).toBe('no_match');
  });
});

