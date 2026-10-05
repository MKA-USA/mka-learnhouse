import { diffDays, maxDay, median } from "./dates";
import { windowStart } from "./status";
import type { CycleInfo, Dimension, ScoredLearner } from "./types";

export interface Aggregate {
  key: string;
  /** Number of roster entries in the group (the denominator for everything). */
  expected: number;
  notStarted: number;
  inProgress: number;
  completed: number;               // finished lessons, not yet attested
  attested: number;
  started: number;                 // expected - notStarted
  overdue: number;
  startedPct: number;              // 0..1
  completedPct: number;            // completed + attested
  attestedPct: number;
  expectedAttestedPct: number;     // mean of per-learner expected curve (handles mid-year appointees)
  medianDaysToComplete: number | null;
  lastActivityAt: string | null;
  selfCheckMismatches: number;     // mismatch fields across the group
  selfCheckMismatchedPeople: number;
  lessonsDone: number;
  lessonsTotal: number;
}

const pct = (a: number, n: number) => (n === 0 ? 0 : a / n);

export function aggregate(key: string, rows: readonly ScoredLearner[], cycle: CycleInfo): Aggregate {
  const n = rows.length;
  const c = { not_started: 0, in_progress: 0, completed: 0, attested: 0 };
  let overdue = 0, mism = 0, mismPeople = 0, expSum = 0, lessonsDone = 0, lessonsTotal = 0;
  const days: number[] = [];
  let last: string | null = null;
  for (const r of rows) {
    c[r.stage]++;
    if (r.overdue) overdue++;
    mism += r.selfCheckMismatches;
    if (r.selfCheckMismatches > 0) mismPeople++;
    expSum += r.expectedAttested;
    lessonsDone += r.lessonsDone; lessonsTotal += r.lessonsTotal;
    last = maxDay(last, r.lastActivityAt);
    if (r.completedAt) days.push(Math.max(0, diffDays(r.completedAt, windowStart(r, cycle))));
  }
  return {
    key, expected: n,
    notStarted: c.not_started, inProgress: c.in_progress, completed: c.completed, attested: c.attested,
    started: n - c.not_started, overdue,
    startedPct: pct(n - c.not_started, n), completedPct: pct(c.completed + c.attested, n), attestedPct: pct(c.attested, n),
    expectedAttestedPct: pct(expSum, n),
    medianDaysToComplete: median(days), lastActivityAt: last,
    selfCheckMismatches: mism, selfCheckMismatchedPeople: mismPeople, lessonsDone, lessonsTotal,
  };
}

export function keyOf(r: ScoredLearner, dim: Dimension): string {
  switch (dim) {
    case "department": return r.departmentSlug;
    case "region": return r.region;
    case "majlis": return r.majlis;
    case "level": return r.level;
  }
}

export function groupBy(rows: readonly ScoredLearner[], dim: Dimension): Map<string, ScoredLearner[]> {
  const m = new Map<string, ScoredLearner[]>();
  for (const r of rows) { const k = keyOf(r, dim); (m.get(k) ?? m.set(k, []).get(k)!).push(r); }
  return m;
}

export function aggregateBy(rows: readonly ScoredLearner[], dim: Dimension, cycle: CycleInfo): Aggregate[] {
  return [...groupBy(rows, dim)].map(([k, v]) => aggregate(k, v, cycle)).sort((a, b) => a.key.localeCompare(b.key));
}

export const CELL_SEP = "␟";
export const cellKey = (a: string, b: string) => `${a}${CELL_SEP}${b}`;

/** Cross-tab (e.g. department x region). Only non-empty cells are present. */
export function crossTab(rows: readonly ScoredLearner[], rowDim: Dimension, colDim: Dimension, cycle: CycleInfo): Map<string, Aggregate> {
  const m = new Map<string, ScoredLearner[]>();
  for (const r of rows) { const k = cellKey(keyOf(r, rowDim), keyOf(r, colDim)); (m.get(k) ?? m.set(k, []).get(k)!).push(r); }
  return new Map([...m].map(([k, v]) => [k, aggregate(k, v, cycle)]));
}
