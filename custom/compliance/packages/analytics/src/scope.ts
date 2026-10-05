/**
 * Authorization scoping (pure, fail-closed). Viewer attributes come from the fork (companion spec A3);
 * the override table can add scopes or deny. Anything not positively granted yields no rows.
 */
import type { ScoredLearner } from "./types";

export interface ViewerAttributes {
  status: "matched" | "partial" | "ambiguous" | "unrecognized" | "not_applicable";
  is_officeholder: boolean | null;
  level: "national" | "regional" | "local" | null;
  department: string | null;
  role: string | null;
  majlis: string | null;
  region: string | null;
}

export type Scope =
  | { kind: "all" }
  | { kind: "department"; department: string }
  | { kind: "region"; region: string }
  | { kind: "majlis"; majlis: string };

export interface ScopeOverride { email: string; scopeType: "all" | "department" | "region" | "majlis" | "deny"; scopeValue: string }

export const ALL_ACCESS_ROLES = new Set(["sadr", "naib_sadr", "motamid"]);

const key = (s: string | null | undefined) => (s ?? "").toLowerCase().replace(/[^a-z0-9]+/g, "");

export interface ViewerInput { email: string; attributes: ViewerAttributes | null; isAdmin?: boolean; overrides?: readonly ScopeOverride[] }

/** Scopes granted to a viewer. Empty array = no access. A `deny` override always wins. */
export function resolveScopes(v: ViewerInput): Scope[] {
  const email = v.email.trim().toLowerCase();
  const mine = (v.overrides ?? []).filter((o) => o.email.trim().toLowerCase() === email);
  if (mine.some((o) => o.scopeType === "deny")) return [];
  const scopes: Scope[] = [];
  if (v.isAdmin) scopes.push({ kind: "all" });
  const a = v.attributes;
  if (a && a.status === "matched" && a.is_officeholder === true && a.role) {
    if (ALL_ACCESS_ROLES.has(a.role)) scopes.push({ kind: "all" });
    else if (a.role === "mohtamim" && a.department) scopes.push({ kind: "department", department: a.department });
    else if (a.role === "regional_qaid" && a.region) scopes.push({ kind: "region", region: a.region });
    else if (a.role === "qaid" && a.level === "local" && a.majlis) scopes.push({ kind: "majlis", majlis: a.majlis });
  }
  for (const o of mine) {
    if (o.scopeType === "all") scopes.push({ kind: "all" });
    else if (o.scopeType === "department" && o.scopeValue) scopes.push({ kind: "department", department: o.scopeValue });
    else if (o.scopeType === "region" && o.scopeValue) scopes.push({ kind: "region", region: o.scopeValue });
    else if (o.scopeType === "majlis" && o.scopeValue) scopes.push({ kind: "majlis", majlis: o.scopeValue });
  }
  return scopes;
}

export function rowInScope(r: Pick<ScoredLearner, "departmentSlug" | "region" | "majlis">, scopes: readonly Scope[]): boolean {
  return scopes.some((s) => {
    switch (s.kind) {
      case "all": return true;
      case "department": return r.departmentSlug !== "" && key(r.departmentSlug) === key(s.department);
      case "region": return r.region !== "" && key(r.region) === key(s.region);
      case "majlis": return r.majlis !== "" && key(r.majlis) === key(s.majlis);
    }
  });
}

/** The single choke point every page, API route and CSV must use. */
export function scopeRows<T extends Pick<ScoredLearner, "departmentSlug" | "region" | "majlis">>(rows: readonly T[], scopes: readonly Scope[]): T[] {
  if (!scopes.length) return [];
  if (scopes.some((s) => s.kind === "all")) return [...rows];
  return rows.filter((r) => rowInScope(r, scopes));
}

export const scopeLabel = (s: readonly Scope[]): string =>
  !s.length ? "No access" : s.map((x) => x.kind === "all" ? "Everything" : x.kind === "department" ? `Department: ${x.department}` : x.kind === "region" ? `Region: ${x.region}` : `Majlis: ${x.majlis}`).join(" + ");
