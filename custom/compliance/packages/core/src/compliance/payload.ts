import type { RosterRow } from "../roster/generate";
import type { CycleCoursesFile } from "../provision/cycle-courses";

/**
 * Contract with the fork's compliance API (worktree mka-learnhouse-mka-compliance-api):
 * routers/mka_compliance.py + services/mka/compliance_import.py. Limits mirrored here.
 */
export const MAX_EXPECTED_ROWS = 2000; // compliance_import.MAX_EXPECTED_ROWS
export const MAX_COURSE_ROWS = 100;    // compliance_import.MAX_COURSE_ROWS
export const FORK_LEVELS = ["national", "regional", "local"] as const;

/** Fork department key = identity-rules key (underscores): sanat-o-tijarat -> sanat_o_tijarat. '' = executive/no department. */
export const forkDepartment = (slug: string) => slug.replace(/-/g, "_");
export const forkLevel = (l: RosterRow["level"]): (typeof FORK_LEVELS)[number] => (l === "region" ? "regional" : l === "majlis" ? "local" : "national");

export interface ExpectedRowPayload {
  email: string; department: string; level: string; majlis: string | null; region: string | null; role_title: string;
  person_name: string | null; source: string; formula_unconfirmed: boolean;
}
export interface RowError { row: number; error: string }

export function toExpectedRow(r: RosterRow): ExpectedRowPayload {
  const level = forkLevel(r.level);
  return {
    email: r.learnerEmail.toLowerCase(), department: forkDepartment(r.departmentSlug), level,
    majlis: level === "local" ? r.majlis || null : null, region: r.region || null, role_title: r.roleTitle,
    person_name: r.personName ?? null, source: r.source, formula_unconfirmed: r.source === "formula-unconfirmed",
  };
}

/** Local mirror of compliance_import.validate_expected_row (so we refuse rows the API would reject). */
export function validateExpectedRow(raw: ExpectedRowPayload): string | null {
  const email = (raw.email ?? "").trim().toLowerCase();
  if (!email) return "email is required";
  if (email.length > 320) return "email must be at most 320 characters";
  if (!email.includes("@") || email.startsWith("@") || email.endsWith("@") || email.includes(" ")) return "email is not valid";
  if (!(FORK_LEVELS as readonly string[]).includes(raw.level)) return "level must be national, regional or local";
  const lim: [string, string | null, number][] = [["department", raw.department, 64], ["majlis", raw.majlis, 100], ["region", raw.region, 100], ["role_title", raw.role_title, 200], ["person_name", raw.person_name, 200], ["source", raw.source, 100]];
  for (const [f, v, n] of lim) if (v && v.length > n) return `${f} must be at most ${n} characters`;
  return null;
}

export function validateExpected(rows: ExpectedRowPayload[]): { ok: ExpectedRowPayload[]; errors: RowError[]; duplicates: number } {
  const ok: ExpectedRowPayload[] = []; const errors: RowError[] = []; const seen = new Set<string>(); let duplicates = 0;
  rows.forEach((r, i) => {
    const e = validateExpectedRow(r);
    if (e) { errors.push({ row: i, error: e }); return; }
    const k = [r.email, r.department, r.level, r.role_title].join("|");
    if (seen.has(k)) duplicates++; seen.add(k); ok.push(r);
  });
  return { ok, errors, duplicates };
}
export function chunk<T>(a: T[], n: number): T[][] { if (n < 1 || n > MAX_EXPECTED_ROWS) throw new Error(`batch size must be 1..${MAX_EXPECTED_ROWS}`); const o: T[][] = []; for (let i = 0; i < a.length; i += n) o.push(a.slice(i, i + n)); return o; }

export interface CyclePayload {
  cycle: string; starts_on: string; deadline: string; deadline_on: string;
  courses: { kind: string; department: string | null; course_uuid: string; signoff: { assignment_uuid: string } | null; contact_check: { assignment_uuid: string } | null }[];
}
const ISO = /^\d{4}-\d{2}-\d{2}$/;

/** out/cycle-courses.json -> POST /mka/compliance/cycles body. Dates come from cycle config, never hard-coded. */
export function buildCyclePayload(file: CycleCoursesFile, startsOn: string, deadlineOn: string): CyclePayload {
  return {
    cycle: file.cycle, starts_on: startsOn, deadline: deadlineOn, deadline_on: deadlineOn,
    courses: file.courses.map((c) => ({ kind: c.kind, department: c.kind === "general" ? null : forkDepartment(c.department), course_uuid: c.course_uuid,
      signoff: c.signoff ? { assignment_uuid: c.signoff.assignment_uuid } : null, contact_check: c.contact_check ? { assignment_uuid: c.contact_check.assignment_uuid } : null })),
  };
}
export function validateCyclePayload(p: CyclePayload): string[] {
  const e: string[] = [];
  if (!p.cycle || p.cycle.length > 100) e.push("cycle label is required (<=100 chars)");
  if (!ISO.test(p.deadline)) e.push("deadline must be YYYY-MM-DD");
  if (!ISO.test(p.starts_on)) e.push("starts_on must be YYYY-MM-DD");
  if (ISO.test(p.deadline) && ISO.test(p.starts_on) && p.starts_on > p.deadline) e.push("starts_on must not be after the deadline");
  if (p.courses.length > MAX_COURSE_ROWS) e.push(`at most ${MAX_COURSE_ROWS} courses per request`);
  p.courses.forEach((c, i) => {
    if (c.kind !== "general" && c.kind !== "department") e.push(`course ${i}: kind must be general or department`);
    if (c.kind === "department" && !c.department) e.push(`course ${i}: department is required for a department course`);
    if (!c.course_uuid || c.course_uuid.length > 200) e.push(`course ${i}: course_uuid is required`);
  });
  return e;
}
