import { writeFileSync } from "node:fs";
import { join } from "node:path";
import {
  ConflictError, LhApi, LhClient, SafetyError, STAGING_API_BASE, applyCourse, assertStaging, connect, courseMap, dbMapStore, getCycleId, idmap, loadRoster, planCourse, reconcileEnrollments, selectLearners, upsertEnrollmentLog, buildCycleCourses, executePublish, publishPlan, DEPARTMENTS, courseName, verifyCourse, withoutExcluded, type ProvisionConfig, type CoursePlan,
} from "@mka/compliance-core";
import { eq } from "drizzle-orm";
import type { Args } from "./args";
import { loadCycleDef } from "./cycles";
import { OUT_DIR, ensureOut, writeOut } from "./commands-data";
import { DEFAULT_CYCLE } from "./cycles";
import { assertNotExcluded, configFrom } from "./config";
import { PILOT, buildWorld } from "./world";

function selection(a: Args) {
  if (a.has("pilot")) return { only: PILOT, includeGeneral: true, label: "pilot (General + Aitmad + Tabligh)" };
  if (a.has("only")) return { only: String(a.str("only")).split(",").map((s) => s.trim()).filter(Boolean), includeGeneral: a.has("with-general"), label: `only ${a.str("only")}` };
  if (a.has("all")) return { only: undefined, includeGeneral: true, label: "ALL courses (General + every non-excluded department)" };
  return null;
}

function clientFromEnv() {
  process.env.LH_API_BASE ||= STAGING_API_BASE;
  assertStaging(process.env.LH_API_BASE);
  return LhClient.fromEnv({ ...process.env, LH_ORG_SLUG: process.env.LH_ORG_SLUG || "default" }, { delayMs: 1200, maxRetries: 2 });
}

export function formatPlan(p: CoursePlan): string {
  const c = p.counts;
  const lines = [`${p.action.toUpperCase().padEnd(9)} ${p.name}  (${c.chapters} chapters, ${c.pages} pages, ${c.assignments} assignments/${c.tasks} tasks, ${c.media} media)`];
  if (p.conflict) lines.push(`    CONFLICT: ${p.conflict}`);
  for (const f of p.flags) lines.push(`    flag: ${f}`);
  if (p.action === "update") for (const i of p.items.filter((x) => x.action === "update" || x.action === "create")) lines.push(`    ${i.action} ${i.level} ${i.key}${i.detail ? ` (${i.detail})` : ""}`);
  return lines.join("\n");
}

export async function cmdPlan(a: Args) {
  const sel = selection(a) ?? { only: undefined, includeGeneral: true, label: "ALL courses (dry run)" };
  const cycle = a.str("cycle", DEFAULT_CYCLE)!; const config = configFrom(a); const { db, sql } = connect();
  try {
    const w = await buildWorld(db, { cycle, only: sel.only, includeGeneral: sel.includeGeneral, config });
    const store = dbMapStore(db, w.cycleId);
    let existing: { name: string; course_uuid: string }[] | null = null;
    if (process.env.LH_API_TOKEN) { try { existing = await new LhApi(clientFromEnv()).listCourses(1, 100, true); } catch { console.log("(could not list LearnHouse courses; conflict check skipped)"); } }
    else console.log("(no LH_API_TOKEN: conflict check against LearnHouse skipped; run via `bun run lh plan`)");
    console.log(`PLAN (dry run, nothing is written) cycle ${cycle}, selection: ${sel.label}`);
    const out: CoursePlan[] = [];
    for (const { spec } of w.specs) { const row = await store.get(spec.kind, spec.departmentSlug); const p = planCourse(spec, row, existing?.find((c) => c.name === spec.name)?.course_uuid ?? null); out.push(p); console.log(formatPlan(p)); }
    const tally = out.reduce<Record<string, number>>((m, p) => ((m[p.action] = (m[p.action] ?? 0) + 1), m), {});
    console.log(`\nsummary: ${JSON.stringify(tally)}${w.warnings.length ? `\nwarnings: ${w.warnings.join("; ")}` : ""}`);
  } finally { await sql.end(); }
}

export async function cmdApply(a: Args) {
  if (!a.has("confirm-staging")) throw new SafetyError("apply requires --confirm-staging");
  const sel = selection(a);
  if (!sel) throw new SafetyError("apply requires --pilot, --only <slugs> or --all (the first apply must be --pilot)");
  const client = clientFromEnv(); const api = new LhApi(client);
  const cycle = a.str("cycle", DEFAULT_CYCLE)!; const config = configFrom(a); const { db, sql } = connect();
  try {
    const w = await buildWorld(db, { cycle, only: sel.only, includeGeneral: sel.includeGeneral, config });
    const store = dbMapStore(db, w.cycleId);
    const courses = await api.listCourses(1, 1, true);
    const orgId = courses[0]?.org_id ?? 1;
    console.log(`APPLY on staging, cycle ${cycle}, selection: ${sel.label}; all courses stay DRAFT`);
    const results: { name: string; uuid: string; created: number; updated: number; verify: string }[] = [];
    for (const { spec, thinkificCourseId } of w.specs) {
      try {
        const r = await applyCourse({ api, store, orgId, log: (s) => console.log(s) }, spec, thinkificCourseId);
        const v = await verifyCourse(api, r.courseUuid, spec);
        results.push({ name: spec.name, uuid: r.courseUuid, created: r.created, updated: r.updated, verify: `${v.ok ? "OK" : "MISMATCH"} ${v.detail}` });
      } catch (e) {
        if (e instanceof ConflictError) { console.error(`CONFLICT ${spec.name}: ${e.message}`); continue; }
        throw e;
      }
    }
    await exportCycleCourses(db, w.cycleId, cycle, config);
    const rows = await db.select().from(idmap);
    ensureOut();
    writeFileSync(join(OUT_DIR, "idmap.json"), JSON.stringify(rows.map(({ id, createdAt, ...r }) => r), null, 1)) ;
    const base = (process.env.LH_API_BASE ?? STAGING_API_BASE).replace(/\/api\/v1$/, "");
    for (const r of results) console.log(`${r.name}: ${r.uuid} created=${r.created} updated=${r.updated} readback ${r.verify}\n   ${base}/course/${r.uuid.replace(/^course_/, "")}`);
    writeOut("apply-report.md", ["# Apply report", "", ...results.map((r) => `- ${r.name}: \`${r.uuid}\` (created ${r.created}, updated ${r.updated}); readback ${r.verify}`), ""].join("\n"));
  } finally { await sql.end(); }
}

export async function cmdReconcile(a: Args) {
  const apply = a.has("apply");
  if (apply && !a.has("confirm-staging")) throw new SafetyError("reconcile --apply requires --confirm-staging");
  const sel = selection(a);
  if (!sel) throw new SafetyError("reconcile requires --pilot, --only <slugs> or --all");
  const client = clientFromEnv(); const api = new LhApi(client);
  const cycle = a.str("cycle", DEFAULT_CYCLE)!; const config = configFrom(a); assertNotExcluded(sel.only, config); const { db, sql } = connect();
  try {
    const cid = await getCycleId(db, cycle); if (cid === null) throw new Error(`cycle ${cycle} not found`);
    const maps = withoutExcluded(await db.select().from(courseMap).where(eq(courseMap.cycleId, cid)), config.excludedDepartments);
    const general = maps.find((m) => m.kind === "general")?.lhCourseUuid;
    const deptCourse = new Map(maps.filter((m) => m.kind === "department").map((m) => [m.departmentSlug, m.lhCourseUuid]));
    const roster = await loadRoster(db, cid, config.excludedDepartments);
    const wanted = selectLearners(roster, sel.only);
    const byEmail = new Map<string, Set<string>>(); const missingCourses = new Set<string>();
    for (const r of wanted) {
      const set = byEmail.get(r.learnerEmail) ?? new Set<string>();
      if (general) set.add(general); else missingCourses.add("general");
      if (r.departmentSlug) { const c = deptCourse.get(r.departmentSlug); if (c) set.add(c); else missingCourses.add(r.departmentSlug); }
      byEmail.set(r.learnerEmail, set);
    }
    const targets = [...byEmail.entries()].filter(([, s]) => s.size).map(([email, s]) => ({ email, courseUuids: [...s] }));
    console.log(`RECONCILE ${apply ? "APPLY" : "(dry run, nothing is written)"} cycle ${cycle}, selection: ${sel.label}: ${targets.length} learners${missingCourses.size ? `; courses not provisioned yet: ${[...missingCourses].join(", ")}` : ""}`);
    const r = await reconcileEnrollments(api, targets, { apply, log: (s) => console.log(s) });
    if (apply) await upsertEnrollmentLog(db, cid, r.enrollmentRows);
    const lines = [`# Reconcile report (${apply ? "applied" : "dry run"}) cycle ${cycle}`, "", `Learners considered: ${r.learners}. Not yet signed up: ${r.notSignedUp.length}. Lookup failures: ${r.lookupFailed}.`, "",
      "| Course | Wanted (have account) | Already enrolled | To enroll | Enrolled now | Skipped (not org member) |", "|---|---|---|---|---|---|",
      ...r.perCourse.map((c) => `| ${c.courseUuid} | ${c.wanted} | ${c.alreadyEnrolled} | ${c.toEnroll} | ${c.enrolled} | ${c.skippedNotInOrg} |`), ""];
    writeOut("reconcile-report.md", lines.join("\n"));
    writeOut("not-signed-up.csv", ["email", ...r.notSignedUp].join("\n") + "\n");
    console.log(lines.join("\n"));
  } finally { await sql.end(); }
}

async function exportCycleCourses(db: any, cycleId: number, cycle: string, config: ProvisionConfig) {
  const rows = await dbMapStoreRows(db, cycleId, config);
  const def = await loadCycleDef(db, cycle);
  writeOut("cycle-courses.json", JSON.stringify(buildCycleCourses(cycle, def.startsOn, def.deadlineOn, rows), null, 1));
  return rows.length;
}
async function dbMapStoreRows(db: any, cycleId: number, config: ProvisionConfig) {
  const rows = withoutExcluded(await db.select().from(courseMap).where(eq(courseMap.cycleId, cycleId)), config.excludedDepartments);
  return rows.map((r: any) => ({ cycleId, kind: r.kind, departmentSlug: r.departmentSlug, lhCourseUuid: r.lhCourseUuid, lhCourseId: r.lhCourseId, structure: r.structure, contentHash: r.contentHash }));
}

export async function cmdExportCourses(a: Args) {
  const cycle = a.str("cycle", DEFAULT_CYCLE)!; const config = configFrom(a); const { db, sql } = connect();
  try { const cid = await getCycleId(db, cycle); if (cid === null) throw new Error(`cycle ${cycle} not found`); const n = await exportCycleCourses(db, cid, cycle, config); console.log(`out/cycle-courses.json: ${n} courses`); } finally { await sql.end(); }
}

/** Publishes course + activities + assignments. Dry run unless --execute. NEVER invoked by apply/plan/reconcile. */
export async function cmdPublish(a: Args) {
  const execute = a.has("execute");
  if (execute && !a.has("confirm-staging")) throw new SafetyError("publish --execute requires --confirm-staging");
  const which = a.str("course"); const all = a.has("all");
  if (!which && !all) throw new SafetyError("publish requires --course <name|uuid> or --all");
  const client = clientFromEnv(); const api = new LhApi(client);
  const cycle = a.str("cycle", DEFAULT_CYCLE)!; const { db, sql } = connect();
  try {
    const cid = await getCycleId(db, cycle); if (cid === null) throw new Error(`cycle ${cycle} not found`);
    const rows = await dbMapStoreRows(db, cid, configFrom(a));
    const nameOf = (r: any) => courseName(cycle, r.kind === "general" ? "General" : DEPARTMENTS.find((d) => d.slug === r.departmentSlug)?.name ?? r.departmentSlug);
    const chosen = all ? rows : rows.filter((r: any) => r.lhCourseUuid === which || nameOf(r).toLowerCase() === String(which).toLowerCase());
    if (!chosen.length) throw new Error(`no provisioned course matches ${which}`);
    console.log(`PUBLISH ${execute ? "EXECUTE" : "(dry run, nothing is changed)"} on staging: ${chosen.length} course(s)`);
    for (const r of chosen) {
      const items = publishPlan({ courseUuid: r.lhCourseUuid, name: nameOf(r), activities: Object.entries(r.structure.activities).map(([key, x]: [string, any]) => ({ key, uuid: x.uuid, assignmentUuid: x.assignmentUuid })) });
      const c = (l: string) => items.filter((i) => i.level === l).length;
      console.log(`${nameOf(r)} (${r.lhCourseUuid}): will set published=true on ${c("activity")} activities, ${c("assignment")} assignments, then the course`);
      if (execute) await executePublish(api, items, (s) => console.log("  " + s));
    }
  } finally { await sql.end(); }
}
