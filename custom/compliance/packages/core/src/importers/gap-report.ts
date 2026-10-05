import { DEFAULT_EXCLUDED_DEPARTMENTS, activeDepartments, withoutExcluded } from "../config";
import type { RosterRow } from "../roster/generate";
import type { Issue } from "./types";

export interface PlanStatus { departmentSlug: string; level: string; stale: boolean; source: string }
export interface GapReportInput { cycleLabel: string; roster: RosterRow[]; plans: PlanStatus[]; issues: Issue[]; notes?: string[]; excludedDepartments?: readonly string[] }
export interface GapCounts {
  rosterRows: number; rosterByLevel: Record<string, number>; unconfirmedMailboxes: number; missingNames: number; duplicateMailboxes: number; departmentsWithoutPlan: number; departmentsStalePlanOnly: number;
  byCode: Record<string, number>;
}

export function buildGapReport(input: GapReportInput): { markdown: string; counts: GapCounts } {
  const excluded = input.excludedDepartments ?? DEFAULT_EXCLUDED_DEPARTMENTS;
  const DEPARTMENTS = activeDepartments(excluded);
  const roster = withoutExcluded(input.roster, excluded); const plans = withoutExcluded(input.plans, excluded); const { issues } = input;
  const byLevel: Record<string, number> = {}; for (const r of roster) byLevel[r.level] = (byLevel[r.level] ?? 0) + 1;
  const unconfirmed = roster.filter((r) => r.source === "formula-unconfirmed").length;
  const missing = roster.filter((r) => !r.personName);
  const emailCount = new Map<string, number>();
  for (const r of roster) emailCount.set(r.learnerEmail, (emailCount.get(r.learnerEmail) ?? 0) + 1);
  const dupes = [...emailCount.entries()].filter(([, n]) => n > 1);
  const byCode: Record<string, number> = {};
  for (const i of issues) byCode[i.code] = (byCode[i.code] ?? 0) + 1;
  if (dupes.length) byCode["duplicate-mailbox-in-roster"] = dupes.length;

  const planByDept = new Map<string, PlanStatus[]>();
  for (const p of plans) planByDept.set(p.departmentSlug, [...(planByDept.get(p.departmentSlug) ?? []), p]);
  const noPlan = DEPARTMENTS.filter((d) => !planByDept.has(d.slug));
  const staleOnly = DEPARTMENTS.filter((d) => planByDept.get(d.slug)?.every((p) => p.stale));

  const missByDept = new Map<string, number>(); const totByDept = new Map<string, number>();
  for (const r of roster) { const k = r.departmentSlug || "(no department)"; totByDept.set(k, (totByDept.get(k) ?? 0) + 1); if (!r.personName) missByDept.set(k, (missByDept.get(k) ?? 0) + 1); }

  const L: string[] = [];
  L.push(`# Data-gap report: cycle ${input.cycleLabel}`, "", `Generated ${new Date().toISOString()}. Role mailboxes only; no personal names are listed.`, "");
  L.push("## Headline", "",
    `- Roster roles generated: **${roster.length}** (every Majlis has every role).`,
    `- By level: ${Object.entries(byLevel).map(([k, v]) => `${k} ${v}`).join(", ")}.`,
    ...(unconfirmed ? [`- **UNCONFIRMED mailbox pattern:** ${unconfirmed} mailboxes flagged \`formula-unconfirmed\` (pattern not yet confirmed by the user).`] : []),
    `- Roles with **no person name**: **${missing.length}** of ${roster.length}.`,
    `- Departments with **no plan**: **${noPlan.length}** of ${DEPARTMENTS.length}; with only **stale** plans: **${staleOnly.length}**.`,
    `- Duplicate mailboxes in roster: **${dupes.length}**.`,
    `- Import issues: **${issues.length}** (${Object.entries(byCode).map(([k, v]) => `${k}: ${v}`).join(", ") || "none"}).`, "");
  if (excluded.length) L.push(`- Excluded by config (not counted anywhere above): ${excluded.join(", ")}.`, "");
  if (input.notes?.length) { L.push("## Notes", "", ...input.notes.map((n) => `- ${n}`), ""); }
  L.push("## Missing names by department", "", "| Department | Roles | Missing names |", "|---|---|---|");
  for (const [k, tot] of [...totByDept.entries()].sort()) L.push(`| ${k} | ${tot} | ${missByDept.get(k) ?? 0} |`);
  L.push("", "## Plans", "");
  if (noPlan.length) L.push(`**No plan for:** ${noPlan.map((d) => d.name).join(", ")}`, "");
  if (staleOnly.length) L.push(`**Only stale (carried over) plans:** ${staleOnly.map((d) => d.name).join(", ")}`, "");
  if (!noPlan.length && !staleOnly.length) L.push("All departments have a current plan.", "");
  L.push("## Duplicate mailboxes in roster", "");
  L.push(dupes.length ? dupes.map(([e, n]) => `- ${e} (${n} roles)`).join("\n") : "None.", "");
  L.push("## Import issues", "");
  const groups = new Map<string, Issue[]>();
  for (const i of issues) groups.set(i.code, [...(groups.get(i.code) ?? []), i]);
  if (!groups.size) L.push("None.", "");
  for (const [code, list] of groups) {
    L.push(`### ${code} (${list.length})`, "");
    for (const i of list.slice(0, 25)) L.push(`- ${i.file}${i.line ? `:${i.line}` : ""} [${i.severity}] ${i.message}`);
    if (list.length > 25) L.push(`- ... and ${list.length - 25} more`);
    L.push("");
  }
  return { markdown: L.join("\n"), counts: {
    rosterRows: roster.length, rosterByLevel: byLevel, unconfirmedMailboxes: unconfirmed, missingNames: missing.length, duplicateMailboxes: dupes.length,
    departmentsWithoutPlan: noPlan.length, departmentsStalePlanOnly: staleOnly.length, byCode } };
}
