import { markdownToProseMirror } from "../content/html";
import type { PMDoc } from "../content/pm";
import { parseCsv } from "./csv";
import { resolveDepartment } from "./resolve";
import { type Issue, SHEET_ERROR_RE } from "./types";

export interface DeptPlanInput {
  departmentSlug: string; level: string; responsibilitiesMd: string; okrsMd: string; resourcesMd: string;
  responsibilitiesDoc: PMDoc | null; okrsDoc: PMDoc | null; resourcesDoc: PMDoc | null;
  updatedBy: string | null; stale: boolean; source: string;
}
export const PLAN_LEVELS = ["all", "national", "region", "majlis"];
const FILE = "dept_plans.csv";

/** Idempotent + validating. Bad rows become Issues; nothing throws. Last duplicate wins. */
export function parseDeptPlans(csv: string, file = FILE): { rows: DeptPlanInput[]; issues: Issue[] } {
  const { headers, rows } = parseCsv(csv);
  const issues: Issue[] = [];
  const idx = (n: string) => headers.indexOf(n);
  const need = ["department", "level"];
  const missing = need.filter((n) => idx(n) < 0);
  if (missing.length) { issues.push({ file, line: 1, severity: "error", code: "missing-column", message: `missing column(s): ${missing.join(", ")}` }); return { rows: [], issues }; }
  const out = new Map<string, DeptPlanInput>();
  for (const r of rows) {
    if (r.cells.length !== headers.length) {
      const extra = r.cells.slice(headers.length).some((c) => c.trim());
      if (r.cells.length < headers.length || extra) { issues.push({ file, line: r.line, severity: "error", code: "shifted-row", message: `expected ${headers.length} columns, found ${r.cells.length}; row skipped` }); continue; }
    }
    const get = (n: string) => { const c = (r.cells[idx(n)] ?? "").trim(); if (SHEET_ERROR_RE.test(c)) { issues.push({ file, line: r.line, severity: "warn", code: "sheet-error", message: `${n} contains ${c}; treated as blank` }); return ""; } return c; };
    const rawDept = get("department");
    const dept = resolveDepartment(rawDept);
    if (!dept) { issues.push({ file, line: r.line, severity: "error", code: "unknown-department", message: `unknown department "${rawDept}"; row skipped` }); continue; }
    if (rawDept && resolveDepartment(rawDept) && rawDept.toLowerCase().replace(/[^a-z]/g, "") !== dept.replace(/[^a-z]/g, "")) issues.push({ file, line: r.line, severity: "info", code: "slug-alias", message: `department "${rawDept}" resolved to ${dept}` });
    const level = (get("level") || "all").toLowerCase();
    if (!PLAN_LEVELS.includes(level)) { issues.push({ file, line: r.line, severity: "error", code: "bad-level", message: `level "${level}" not in ${PLAN_LEVELS.join("/")}; row skipped` }); continue; }
    const resp = get("responsibilities_md"), okrs = get("okrs_md"), res = get("resources_md");
    if (!resp && !okrs && !res) { issues.push({ file, line: r.line, severity: "warn", code: "empty-plan", message: `${dept}/${level} has no content; row skipped` }); continue; }
    const key = `${dept}|${level}`;
    if (out.has(key)) issues.push({ file, line: r.line, severity: "warn", code: "duplicate-key", message: `duplicate ${dept}/${level}; later row wins` });
    const staleRaw = idx("stale") >= 0 ? get("stale").toLowerCase() : "";
    out.set(key, {
      departmentSlug: dept, level, responsibilitiesMd: resp, okrsMd: okrs, resourcesMd: res,
      responsibilitiesDoc: resp ? markdownToProseMirror(resp).doc : null, okrsDoc: okrs ? markdownToProseMirror(okrs).doc : null,
      resourcesDoc: res ? markdownToProseMirror(res).doc : null,
      updatedBy: idx("updated_by") >= 0 ? get("updated_by") || null : null, stale: staleRaw === "true" || staleRaw === "1" || staleRaw === "yes", source: "csv",
    });
  }
  return { rows: [...out.values()], issues };
}
