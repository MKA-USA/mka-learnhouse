import {
  aggregate, aggregateBy, attention, buildSeries, cellKey, chaseCsv, compareAttention, crossTab, keyOf, trendVs, withConfig,
  type Aggregate, type Attention, type Dimension, type ScoredLearner, type SeriesPoint, type Trend, type AttentionConfig,
} from "@mka/analytics/pure";
import type { ScopedData } from "@/lib/access";

export interface Filters { dept?: string; region?: string; majlis?: string; status?: string; q?: string }

export const CFG: AttentionConfig = withConfig();

export function parseFilters(sp: Record<string, string | string[] | undefined>): Filters {
  const one = (k: string) => { const v = sp[k]; const s = Array.isArray(v) ? v[0] : v; return s && s.length <= 100 ? s : undefined; };
  const region = one("region");
  const dept = one("dept");
  return { dept: dept === "executive" ? "" : dept, region: region === "_national" ? "" : region, majlis: one("majlis"), status: one("status"), q: one("q") };
}

/** Narrowing filters. These can only SHRINK an already-scoped row set. */
export function applyFilters(rows: readonly ScoredLearner[], f: Filters): ScoredLearner[] {
  const q = f.q?.trim().toLowerCase();
  return rows.filter((r) =>
    (f.dept === undefined || r.departmentSlug === f.dept) && (f.region === undefined || r.region === f.region) && (f.majlis === undefined || r.majlis === f.majlis) &&
    (f.status === undefined || r.status === f.status || (f.status === "attention" && r.stage !== "attested")) &&
    (!q || `${r.email} ${r.personName ?? ""} ${r.roleTitle} ${r.majlis}`.toLowerCase().includes(q)));
}

export interface GroupRow { key: string; label: string; agg: Aggregate; att: Attention; series: SeriesPoint[]; trend: Trend }

export function groupRows(data: ScopedData, rows: readonly ScoredLearner[], dim: Dimension, nameOf: (k: string) => string): GroupRow[] {
  const out = aggregateBy(rows, dim, data.cycle).map((agg) => {
    const series = buildSeries(data.history, data.cycle, (r) => keyOf(r, dim) === agg.key && rowsHas(rows, r), CFG);
    return { key: agg.key, label: nameOf(agg.key), agg, att: attention(agg, data.cycle, data.asOf, CFG), series, trend: trendVs(series, data.asOf, 7, CFG) };
  });
  return out.sort((a, b) => compareAttention(a, b));
}
// history rows are already scoped; narrowing filters are applied by membership of the roster ids in `rows`
const idSets = new WeakMap<readonly ScoredLearner[], Set<string>>();
function rowsHas(rows: readonly ScoredLearner[], r: ScoredLearner): boolean {
  let s = idSets.get(rows);
  if (!s) { s = new Set(rows.map((x) => x.rosterId)); idSets.set(rows, s); }
  return s.has(r.rosterId);
}

export function overview(data: ScopedData, f: Filters) {
  const rows = applyFilters(data.rows, { dept: f.dept, region: f.region });
  const name = (s: string) => data.departments.find((d) => d.slug === s)?.name ?? (s === "" ? "Executive (Qaids)" : s);
  const total = aggregate("all", rows, data.cycle);
  const series = buildSeries(data.history, data.cycle, (r) => rowsHas(rows, r), CFG);
  const departments = groupRows(data, rows, "department", name);
  const cells = crossTab(rows, "department", "region", data.cycle);
  const regions = [...new Set(rows.map((r) => r.region))].sort((a, b) => (a === "" ? -1 : b === "" ? 1 : a.localeCompare(b)));
  const deptOrder = departments.map((d) => d.key);
  return {
    rows, total, att: attention(total, data.cycle, data.asOf, CFG), series, trend: trendVs(series, data.asOf, 1, CFG), trend7: trendVs(series, data.asOf, 7, CFG),
    departments, regions, deptOrder, heat: (d: string, r: string) => { const agg = cells.get(cellKey(d, r)); return agg ? { agg, att: attention(agg, data.cycle, data.asOf, CFG) } : null; },
    nameOf: name,
  };
}

/** CSV for the chase list. Scope comes from `data` (already scoped); filters only narrow. */
export function chaseCsvFor(data: ScopedData, f: Filters): string {
  const name = (s: string) => data.departments.find((d) => d.slug === s)?.name ?? (s === "" ? "Executive (Qaids)" : s);
  return chaseCsv(applyFilters(data.rows, { dept: f.dept, region: f.region, majlis: f.majlis, q: f.q, status: f.status }), name);
}

