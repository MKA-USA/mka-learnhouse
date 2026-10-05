import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import {
  LhApi, LhClient, LhHttpError, MAX_EXPECTED_ROWS, SafetyError, STAGING_API_BASE, assertStaging, assignAuthors, buildCyclePayload, chunk, connect, courseMap, getCycleId,
  loadRoster, parseCsv, pushCycle, pushExpected, resolveDepartment, selectLearners, withoutExcluded, toExpectedRow, validateCyclePayload, validateExpected, type CycleCoursesFile, type RosterRow,
} from "@mka/compliance-core";
import { eq } from "drizzle-orm";
import type { Args } from "./args";
import { assertNotExcluded, configFrom } from "./config";
import { OUT_DIR, writeOut } from "./commands-data";
import { DEFAULT_CYCLE, loadCycleDef } from "./cycles";
import { PILOT } from "./world";

function client(delayMs = 1000) {
  process.env.LH_API_BASE ||= STAGING_API_BASE; assertStaging(process.env.LH_API_BASE);
  return LhClient.fromEnv({ ...process.env, LH_ORG_SLUG: process.env.LH_ORG_SLUG || "default" }, { delayMs, maxRetries: 2 });
}
function gate(a: Args, what: string) { if (a.has("apply") && !a.has("confirm-staging")) throw new SafetyError(`${what} --apply requires --confirm-staging`); }
/** Clear, PII-free messages. Token rights per the fork API: reads need courses+assignments read (Read-only preset), imports/deletes all Full Access update rights (courses, activities, assignments, coursechapters, usergroups, certifications). */
export function explainHttp(e: LhHttpError): string {
  const need = "Create the org API token with the **Full Access** preset (reads work with Read-only, writes (push-*, apply, assign-authors, reconcile --apply) need a token created with the Full Access preset; the UI cannot grant users/organizations rights); see docs/runbooks/cycle-rollout.md";
  if (e.status === 403) return `HTTP 403 forbidden: ${(e.detail ?? "").replace(/\S+@\S+/g, "<email>")}. ${need}.`;
  if (e.status === 401) return "HTTP 401: the API token was rejected (expired or revoked). Re-issue it and update the keychain item MKA_LH_DEV_API_TOKEN.";
  if (e.status === 409) return "HTTP 409: conflicting concurrent import; nothing was lost, re-run the same command.";
  if (e.status === 404) return `HTTP 404${e.detail ? ` (${e.detail.slice(0, 80)})` : ""}: cycle not found (run push-cycle first) or the fork compliance API is not deployed on this host.`;
  return `HTTP ${e.status}`;
}
const errStatus = (e: unknown) => (e instanceof LhHttpError ? explainHttp(e) : (e as Error).message);

export async function cmdPushCycle(a: Args) {
  gate(a, "push-cycle"); const apply = a.has("apply");
  const cycle = a.str("cycle", DEFAULT_CYCLE)!; const { db, sql } = connect();
  try {
    const def = await loadCycleDef(db, cycle, a);
    const file = a.str("file", join(OUT_DIR, "cycle-courses.json"))!;
    if (!existsSync(file)) throw new Error(`${file} not found; run export-courses (or apply) first`);
    const cfg = JSON.parse(readFileSync(file, "utf8")) as CycleCoursesFile; const excl = configFrom(a).excludedDepartments;
    const payload = buildCyclePayload({ ...cfg, courses: cfg.courses.filter((c) => !excl.includes(c.department_slug)) }, def.startsOn, def.deadlineOn);
    const errs = validateCyclePayload(payload);
    console.log(`PUSH-CYCLE ${apply ? "APPLY" : "(dry run, nothing is sent)"} ${payload.cycle}: starts ${payload.starts_on}, deadline ${payload.deadline}, ${payload.courses.length} courses`);
    if (errs.length) { errs.forEach((e) => console.log("  invalid: " + e)); throw new Error("refusing: payload would be rejected by the API"); }
    writeOut("payload-cycle.json", JSON.stringify(payload, null, 1));
    if (!apply) return;
    const r = await pushCycle(client(), payload);
    console.log(`cycle ${r.cycle.label} (${r.cycle.action}): ${r.ok} ok, ${r.failed} failed`);
    for (const c of r.courses.filter((x) => !x.ok)) console.log(`  course row ${c.row}: ${c.error}`);
    writeOut("push-cycle-report.json", JSON.stringify(r, null, 1));
    if (r.failed) process.exitCode = 1;
  } catch (e) { if (e instanceof LhHttpError) throw new Error(errStatus(e)); throw e; } finally { await sql.end(); }
}

export async function cmdPushRoster(a: Args) {
  gate(a, "push-roster"); const apply = a.has("apply");
  const only = a.has("pilot") ? PILOT : a.has("only") ? String(a.str("only")).split(",").map((s) => s.trim()) : a.has("all") ? undefined : null;
  if (only === null) throw new SafetyError("push-roster requires --all, --pilot or --only <slugs>");
  const batch = Number(a.str("batch-size", "1000")); if (!(batch >= 1 && batch <= MAX_EXPECTED_ROWS)) throw new SafetyError(`--batch-size must be 1..${MAX_EXPECTED_ROWS}`);
  const cycle = a.str("cycle", DEFAULT_CYCLE)!; const config = configFrom(a); assertNotExcluded(only ?? undefined, config); const { db, sql } = connect();
  try {
    const cid = await getCycleId(db, cycle); if (cid === null) throw new Error(`cycle ${cycle} not found`);
    const roster = (await loadRoster(db, cid, config.excludedDepartments)).map((r) => ({ ...r, level: r.level as RosterRow["level"] })) as RosterRow[];
    const rows = selectLearners(roster, only).map(toExpectedRow);
    const v = validateExpected(rows);
    console.log(`PUSH-ROSTER ${apply ? (a.has("server-dry-run") ? "APPLY (server dry_run)" : "APPLY") : "(dry run, nothing is sent)"} ${cycle}: ${rows.length} rows, ${v.errors.length} rejected locally, ${v.duplicates} duplicate keys, ${rows.filter((r) => r.formula_unconfirmed).length} flagged formula_unconfirmed`);
    writeOut("payload-expected.json", JSON.stringify({ cycle, batchSize: batch, rows: v.ok }, null, 1));
    const report: Record<string, unknown> = { cycle, localErrors: v.errors, batches: [] as unknown[] };
    if (apply) {
      const c = client(); const batches = chunk(v.ok, batch); let offset = 0;
      if (!a.has("server-dry-run") && v.ok.length) { await pushExpected(c, cycle, v.ok.slice(0, 1), true); console.log("preflight ok (token rights and cycle verified, nothing written)"); }
      for (const [i, b] of batches.entries()) {
        const r = await pushExpected(c, cycle, b, a.has("server-dry-run"));
        (report.batches as unknown[]).push({ batch: i, rowOffset: offset, ...r, errors: r.errors.map((e) => ({ ...e, row: e.row + offset })) });
        console.log(`batch ${i + 1}/${batches.length}: created ${r.created}, updated ${r.updated}, unchanged ${r.unchanged}, failed ${r.failed}${r.departments_without_course.length ? `, departments without course: ${r.departments_without_course.join(",")}` : ""}`);
        offset += b.length;
      }
    }
    writeOut("push-roster-report.json", JSON.stringify(report, null, 1));
    if (v.errors.length) process.exitCode = 1;
  } catch (e) { if (e instanceof LhHttpError) throw new Error(errStatus(e)); throw e; } finally { await sql.end(); }
}

export async function cmdAssignAuthors(a: Args) {
  gate(a, "assign-authors"); const apply = a.has("apply");
  const map = a.str("map"); if (!map) throw new Error("--map mohtamims.csv is required (columns: department,email)");
  const { headers, rows } = parseCsv(readFileSync(map, "utf8"));
  const di = headers.indexOf("department"), ei = headers.indexOf("email");
  if (di < 0 || ei < 0) throw new Error("CSV needs columns department,email");
  const cycle = a.str("cycle", DEFAULT_CYCLE)!; const config = configFrom(a); const { db, sql } = connect();
  try {
    const cid = await getCycleId(db, cycle); if (cid === null) throw new Error(`cycle ${cycle} not found`);
    const maps = withoutExcluded(await db.select().from(courseMap).where(eq(courseMap.cycleId, cid)), config.excludedDepartments);
    const course = new Map(maps.filter((m) => m.kind === "department").map((m) => [m.departmentSlug, m.lhCourseUuid]));
    const todo: { department: string; email: string; courseUuid: string }[] = []; const skipped: string[] = [];
    for (const r of rows) {
      const slug = resolveDepartment(r.cells[di] ?? ""); const email = (r.cells[ei] ?? "").trim().toLowerCase();
      if (!slug || !email.includes("@")) { skipped.push(`line ${r.line}: bad department or email`); continue; }
      if (config.excludedDepartments.includes(slug)) { skipped.push(`line ${r.line}: ${slug} is excluded by config (pass --include-atfal to include Atfal); row ignored`); continue; }
      const c = course.get(slug); if (!c) { skipped.push(`line ${r.line}: ${slug} has no provisioned course`); continue; }
      todo.push({ department: slug, email, courseUuid: c });
    }
    console.log(`ASSIGN-AUTHORS ${apply ? "APPLY" : "(dry run, nothing is written)"}: ${todo.length} assignments, ${skipped.length} skipped`);
    skipped.forEach((s) => console.log("  skipped " + s));
    if (!todo.length) return;
    if (!process.env.LH_API_TOKEN) { console.log("(no LH_API_TOKEN: lookups skipped; run via `bun run lh assign-authors`)"); return; }
    const res = await assignAuthors(new LhApi(client()), todo, apply);
    const tally = res.reduce<Record<string, number>>((m, r) => ((m[r.status] = (m[r.status] ?? 0) + 1), m), {});
    console.log(`result: ${JSON.stringify(tally)}`);
    writeOut("assign-authors-report.json", JSON.stringify({ cycle, apply, results: res, skipped }, null, 1));
  } finally { await sql.end(); }
}
