import { redirect } from "next/navigation";
import { resolveScopes, scopeRows, scopeLabel, type Scope, type ScopeOverride, type ViewerAttributes } from "@mka/analytics/scope";
import type { Dataset, ScoredLearner } from "@mka/analytics/pure";
import { getViewerAttributes } from "@/lib/attributes";
import { getDataset, getOverrides } from "@/lib/data";
import { env } from "@/lib/env";
import { personaByKey } from "@/lib/personas";
import { getViewer, type Viewer } from "@/lib/viewer";

/** Everything a page may see. `rows` and `history` are ALREADY scoped; there is no unscoped escape hatch. */
export interface ScopedData {
  viewer: Viewer;
  scopes: Scope[];
  scopeText: string;
  source: Dataset["source"];
  cycle: Dataset["cycle"];
  asOf: string;
  departments: Dataset["departments"];
  rows: ScoredLearner[];
  history: Record<string, ScoredLearner[]>;
}

/** The single scoping choke point. Pure given its inputs, so authorization tests call it directly. */
export function scopeDataset(dataset: Dataset, viewer: Viewer, attributes: ViewerAttributes | null, overrides: readonly ScopeOverride[], isAdmin: boolean): ScopedData {
  const scopes = resolveScopes({ email: viewer.email, attributes, overrides, isAdmin });
  const history: Record<string, ScoredLearner[]> = {};
  for (const [d, rows] of Object.entries(dataset.history)) history[d] = scopeRows(rows, scopes);
  return {
    viewer, scopes, scopeText: scopeLabel(scopes), source: dataset.source, cycle: dataset.cycle, asOf: dataset.asOf, departments: dataset.departments,
    rows: scopeRows(dataset.rows, scopes), history,
  };
}

export async function loadScoped(viewer: Viewer): Promise<ScopedData> {
  const [dataset, attributes, overrides] = await Promise.all([getDataset(), getViewerAttributes(viewer.email, viewer.devPersona), getOverrides()]);
  const isAdmin = env.adminEmails().includes(viewer.email) || !!(viewer.devPersona && personaByKey(viewer.devPersona)?.isAdmin);
  return scopeDataset(dataset, viewer, attributes, overrides, isAdmin);
}

/** For pages: redirects unauthenticated viewers to /login and viewers without any scope to /no-access. */
export async function requireScoped(): Promise<ScopedData> {
  const viewer = await getViewer();
  if (!viewer) redirect("/login");
  const data = await loadScoped(viewer);
  if (!data.scopes.length) redirect("/no-access");
  return data;
}
