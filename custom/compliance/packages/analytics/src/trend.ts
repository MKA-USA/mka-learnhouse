import { aggregate } from "./aggregate";
import { attention } from "./attention";
import { DEFAULT_CONFIG, type AttentionConfig } from "./config";
import { addDays } from "./dates";
import type { CycleInfo, ScoredLearner } from "./types";

export interface SeriesPoint {
  date: string; n: number;
  attestedPct: number; startedPct: number; expectedAttestedPct: number;
  overdue: number; score: number;
}

/** Daily series for one scope from per-day snapshots (`filter` selects the scope). */
export function buildSeries(
  byDate: Record<string, readonly ScoredLearner[]>, cycle: CycleInfo,
  filter: (r: ScoredLearner) => boolean = () => true, cfg: AttentionConfig = DEFAULT_CONFIG,
): SeriesPoint[] {
  return Object.keys(byDate).sort().map((date) => {
    const a = aggregate("", byDate[date]!.filter(filter), cycle);
    return {
      date, n: a.expected, attestedPct: a.attestedPct, startedPct: a.startedPct,
      expectedAttestedPct: a.expectedAttestedPct, overdue: a.overdue, score: attention(a, cycle, date, cfg).score,
    };
  });
}

export interface Trend {
  from: string | null; to: string | null;
  attestedDelta: number;           // fraction points, e.g. 0.08 = +8 pts
  startedDelta: number;
  overdueDelta: number;
  scoreDelta: number;
  direction: "improving" | "worsening" | "flat" | "unknown";
}

/** Compare the point on/before `asOf` with the latest point on/before `asOf - daysBack`. Falls back to the earliest point. */
export function trendVs(series: readonly SeriesPoint[], asOf: string, daysBack = 1, cfg: AttentionConfig = DEFAULT_CONFIG): Trend {
  const sorted = [...series].sort((a, b) => a.date.localeCompare(b.date));
  const cur = [...sorted].reverse().find((p) => p.date <= asOf);
  if (!cur) return { from: null, to: null, attestedDelta: 0, startedDelta: 0, overdueDelta: 0, scoreDelta: 0, direction: "unknown" };
  const target = addDays(asOf, -daysBack);
  const prev = [...sorted].reverse().find((p) => p.date <= target && p.date < cur.date);
  if (!prev) return { from: null, to: cur.date, attestedDelta: 0, startedDelta: 0, overdueDelta: 0, scoreDelta: 0, direction: "unknown" };
  const attestedDelta = cur.attestedPct - prev.attestedPct;
  const overdueDelta = cur.overdue - prev.overdue;
  const scoreDelta = Math.round((cur.score - prev.score) * 10) / 10;
  const flat = cfg.trend.flatBelow / 100;
  const direction = attestedDelta >= flat ? "improving"
    : (overdueDelta > 0 || scoreDelta >= 3) ? "worsening" : "flat";
  return { from: prev.date, to: cur.date, attestedDelta, startedDelta: cur.startedPct - prev.startedPct, overdueDelta, scoreDelta, direction };
}
