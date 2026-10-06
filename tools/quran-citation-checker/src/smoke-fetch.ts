// Live smoke test of the fetch step only (no Jev key needed): prints 2:255 (en).
import { createQuranClient, fetchVerses } from './fetch.js';

const r = await fetchVerses(createQuranClient(), 2, 255, 255, ['en']);
if (!r.ok) {
  console.error('FAILED:', r.error);
  process.exit(1);
}
const v = r.verses[0];
console.log(`source=${r.source} retrievedAt=${r.retrievedAt} warnings=${JSON.stringify(r.warnings)}`);
console.log(`2:${v.citedVerse} (Al Islam v=${v.alIslamV}, v_=${v.alIslamVUnderscore})`);
console.log(v.arabic);
console.log(v.translations.en);
