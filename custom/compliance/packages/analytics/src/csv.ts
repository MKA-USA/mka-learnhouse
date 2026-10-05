import type { ScoredLearner } from "./types";

/** Neutralise spreadsheet formula injection (=, +, -, @, tab, CR) and quote per RFC 4180. */
export function csvCell(v: string | number | null | undefined): string {
  let s = v === null || v === undefined ? "" : String(v);
  if (/^[=+\-@\t\r]/.test(s)) s = `'${s}`;
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export const CHASE_HEADERS = ["Department", "Role", "Level", "Region", "Majlis", "Name", "Mailbox", "Status", "Lessons done", "Lessons total", "Due on", "Days overdue", "Last activity", "Contact mismatches"] as const;

/** Chase list: everyone not yet attested, overdue first. Callers MUST pass already-scoped rows. */
export function chaseList(rows: readonly ScoredLearner[], deptName: (slug: string) => string): ScoredLearner[] {
  return rows.filter((r) => r.stage !== "attested").sort((a, b) =>
    b.daysOverdue - a.daysOverdue || a.lessonsDone / (a.lessonsTotal || 1) - b.lessonsDone / (b.lessonsTotal || 1) || a.email.localeCompare(b.email));
}

export function chaseCsv(rows: readonly ScoredLearner[], deptName: (slug: string) => string): string {
  const out = [CHASE_HEADERS.join(",")];
  for (const r of chaseList(rows, deptName)) {
    out.push([deptName(r.departmentSlug), r.roleTitle, r.level, r.region, r.majlis, r.personName, r.email, r.status, r.lessonsDone, r.lessonsTotal, r.dueOn, r.daysOverdue, r.lastActivityAt, r.selfCheckMismatches].map(csvCell).join(","));
  }
  return out.join("\r\n") + "\r\n";
}
