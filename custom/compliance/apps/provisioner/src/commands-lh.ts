import { writeFileSync } from "node:fs";
import { join } from "node:path";
import {
  ConflictError, LhApi, LhClient, SafetyError, STAGING_API_BASE, applyCourse, assertStaging, connect, courseMap, dbMapStore, getCycleId, idmap, loadRoster, planCourse, reconcileEnrollments, upsertEnrollmentLog, verifyCourse, type CoursePlan,
} from "@mka/compliance-core";
import { eq } from "drizzle-orm";
import type { Args } from "./args";
import { OUT_DIR, ensureOut, writeOut } from "./commands-data";
import { DEFAULT_CYCLE } from "./cycles";
import { PILOT, buildWorld } from "./world";

function selection(a: Args) {
  if (a.has("pilot")) return { only: PILOT, includeGeneral: true, label: "pilot (General + Aitmad + Tabligh)" };
  if (a.has("only")) return { only: String(a.str("only")).split(",").map((s) => s.trim()).filter(Boolean), includeGeneral: a.has("with-general"), label: `only ${a.str("only")}` };
  if (a.has("all")) return { only: undefined, includeGeneral: true, label: "ALL 22 courses" };
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
  const sel = selection(a) ?? { only: undefined, includeGeneral: true, label: "ALL 22 courses (dry run)" };
  const cycle = a.str("cycle", DEFAULT_CYCLE)!; const { db, sql } = connect();
  try {
    const w = await buildWorld(db, { cycle, only: sel.only, includeGeneral: sel.includeGeneral });
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
  const cycle = a.str("cycle", DEFAULT_CYCLE)!; const { db, sql } = connect();
  try {
    const w = await buildWorld(db, { cycle, only: sel.only, includeGeneral: sel.includeGeneral });
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
  const cycle = a.str("cycle", DEFAULT_CYCLE)!; const { db, sql } = connect();
  try {
    const cid = await getCycleId(db, cycle); if (cid === null) throw new Error(`cycle ${cycle} not found`);
    const maps = await db.select().from(courseMap).where(eq(courseMap.cycleId, cid));
    const general = maps.find((m) => m.kind === "general")?.lhCourseUuid;
    const deptCourse = new Map(maps.filter((m) => m.kind === "department").map((m) => [m.departmentSlug, m.lhCourseUuid]));
    const roster = await loadRoster(db, cid);
    const wanted = roster.filter((r) => (sel.only ? r.departmentSlug && sel.only.includes(r.departmentSlug) : true));
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
