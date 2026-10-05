/** Date helpers. All "day" values are YYYY-MM-DD (UTC). Timestamps may be ISO or LearnHouse naive strings. */
const DAY = 86_400_000;

/** Parse a day or timestamp into UTC midnight ms; null when unparseable. LearnHouse writes naive local strings, so day precision is all we rely on. */
export function dayMs(input: string | null | undefined): number | null {
  if (!input) return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(input.trim());
  if (!m) return null;
  const t = Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  return Number.isNaN(t) ? null : t;
}
export function toDay(ms: number): string { return new Date(ms).toISOString().slice(0, 10); }
export function addDays(day: string, n: number): string { const t = dayMs(day); if (t === null) throw new Error(`bad day: ${day}`); return toDay(t + n * DAY); }
export function diffDays(a: string, b: string): number { const x = dayMs(a), y = dayMs(b); if (x === null || y === null) return 0; return Math.round((x - y) / DAY); }
export function maxDay(...v: (string | null | undefined)[]): string | null {
  let best: number | null = null;
  for (const s of v) { const t = dayMs(s); if (t !== null && (best === null || t > best)) best = t; }
  return best === null ? null : toDay(best);
}
export function median(xs: number[]): number | null {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b), m = s.length >> 1;
  return s.length % 2 ? s[m]! : (s[m - 1]! + s[m]!) / 2;
}
