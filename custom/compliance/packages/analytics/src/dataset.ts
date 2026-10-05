import { DEPARTMENTS } from "../../core/src/seed/departments";
import { addDays } from "./dates";
import { FIXTURE_CYCLE, generateWorld, snapshotAt } from "./fixtures";
import type { CycleInfo, ScoredLearner } from "./types";

export interface Dataset {
  source: "fixtures" | "snapshots";
  cycle: CycleInfo;
  asOf: string;
  rows: ScoredLearner[];                                   // snapshot on asOf
  history: Record<string, ScoredLearner[]>;                // per-day snapshots incl. asOf
  departments: { slug: string; name: string }[];
}

export const EXECUTIVE = { slug: "", name: "Executive (Qaids)" };
export const departmentName = (d: Dataset | { departments: { slug: string; name: string }[] }, slug: string) =>
  d.departments.find((x) => x.slug === slug)?.name ?? (slug === "" ? EXECUTIVE.name : slug);

export function buildFixtureDataset(opts: { asOf?: string; historyDays?: number; seed?: number; cycle?: CycleInfo } = {}): Dataset {
  const cycle = opts.cycle ?? FIXTURE_CYCLE;
  const asOf = opts.asOf ?? "2026-11-18";
  const world = generateWorld({ seed: opts.seed, cycle });
  const history: Record<string, ScoredLearner[]> = {};
  const n = opts.historyDays ?? 14;
  for (let i = n; i >= 0; i--) { const d = addDays(asOf, -i); history[d] = snapshotAt(world, d); }
  return {
    source: "fixtures", cycle, asOf, rows: history[asOf]!, history,
    departments: [...DEPARTMENTS.map((d) => ({ slug: d.slug, name: d.name })), EXECUTIVE],
  };
}
