import { DEPARTMENTS, type DepartmentSeed } from "./seed/departments";

/**
 * THE single switch for departments that are out of scope for the cycle (product decision 2026-10-05: ignore Atfal for now).
 * Every consumer (roster generation, course planning, push, reconcile, reports) derives its department set from here.
 * To switch Atfal back on: pass `--include-atfal` to the provisioner CLI (or empty this list), then re-run `roster`, `plan`, `apply`.
 */
export const DEFAULT_EXCLUDED_DEPARTMENTS: readonly string[] = ["atfal"];

export interface ProvisionConfig { excludedDepartments: readonly string[] }

export function resolveConfig(o: { includeAtfal?: boolean; excludedDepartments?: readonly string[] } = {}): ProvisionConfig {
  const base = o.excludedDepartments ?? DEFAULT_EXCLUDED_DEPARTMENTS;
  return { excludedDepartments: o.includeAtfal ? base.filter((s) => s !== "atfal") : [...base] };
}

export const isExcluded = (slug: string, excluded: readonly string[]) => excluded.includes(slug);
/** Canonical departments minus the excluded ones (these get courses, roster rows and report counts). */
export const activeDepartments = (excluded: readonly string[]): DepartmentSeed[] => DEPARTMENTS.filter((d) => !excluded.includes(d.slug));
/** Drops rows (roster rows, course_map rows, ...) that belong to an excluded department. Rows without a department are kept. */
export const withoutExcluded = <T extends { departmentSlug: string }>(rows: T[], excluded: readonly string[]): T[] =>
  excluded.length ? rows.filter((r) => !excluded.includes(r.departmentSlug)) : rows;
