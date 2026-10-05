import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  DEFAULT_THINKIFIC_DIR, applyNames, applyOverrides, applyStoredOverrides, buildGapReport, connect, ensureCycle, generateRoster, getCycleId, listTkCourses,
  loadPlans, loadRoster, parseDeptPlans, pruneExcludedRoster, parseNames, parseOverrides, seedPlansFromThinkific, upsertDeptPlans, upsertOverrides, upsertRoster, type Issue,
} from "@mka/compliance-core";
import type { Args } from "./args";
import { configFrom } from "./config";
import { DEFAULT_CYCLE, loadCycleDef } from "./cycles";

export const OUT_DIR = fileURLToPath(new URL("../../../out", import.meta.url));
export function ensureOut() { mkdirSync(OUT_DIR, { recursive: true }); }
export function writeOut(name: string, body: string) { mkdirSync(OUT_DIR, { recursive: true }); const p = join(OUT_DIR, name); mkdirSync(dirname(p), { recursive: true }); writeFileSync(p, body); return p; }
const read = (p: string) => readFileSync(p, "utf8");
const summarize = (issues: Issue[]) => { const c: Record<string, number> = {}; for (const i of issues) c[i.code] = (c[i.code] ?? 0) + 1; return JSON.stringify(c); };

export async function cmdRoster(a: Args) {
  const label = a.str("cycle", DEFAULT_CYCLE)!; const { db, sql } = connect();
  try {
    const def = await loadCycleDef(db, label, a); const cid = await ensureCycle(db, def, def.fromFlags);
    const { excludedDepartments } = configFrom(a);
    const pruned = await pruneExcludedRoster(db, cid, excludedDepartments);
    const n = await upsertRoster(db, cid, generateRoster({ excludedDepartments }));
    const ov = await applyStoredOverrides(db, cid);
    console.log(`cycle ${label}: ${n} roster roles upserted${excludedDepartments.length ? ` (excluded by config: ${excludedDepartments.join(", ")}; ${pruned} stale rows removed)` : ""}; ${ov.changed} rows changed by stored overrides`);
  } finally { await sql.end(); }
}

export async function cmdImport(a: Args) {
  const [, kind, file] = a.pos;
  if (!kind || !file) throw new Error("usage: import <dept-plans|overrides|names> <file.csv> [--cycle 2026-27]");
  const label = a.str("cycle", DEFAULT_CYCLE)!; const { db, sql } = connect();
  try {
    const def = await loadCycleDef(db, label, a); const cid = await ensureCycle(db, def, def.fromFlags);
    const text = read(file);
    if (kind === "dept-plans") {
      const r = parseDeptPlans(text, "dept_plans.csv"); const n = await upsertDeptPlans(db, cid, r.rows);
      console.log(`dept_plans: ${n} upserted; issues ${r.issues.length} ${summarize(r.issues)}`);
    } else if (kind === "overrides") {
      const r = parseOverrides(text, "directory_overrides.csv"); const n = await upsertOverrides(db, cid, r.rows);
      const ap = await applyStoredOverrides(db, cid);
      console.log(`directory_overrides: ${n} stored; ${ap.changed} roster rows changed; issues ${r.issues.length + ap.issues.length} ${summarize([...r.issues, ...ap.issues])}`);
    } else if (kind === "names") {
      const r = parseNames(text, "names.csv"); const ap = await applyNames(db, cid, r.names);
      console.log(`names: ${ap.updated} roster rows named; ${ap.unknown.length} emails not in roster; issues ${r.issues.length} ${summarize(r.issues)}`);
    } else throw new Error(`unknown import kind ${kind}`);
  } finally { await sql.end(); }
}

export async function cmdSeedThinkific(a: Args) {
  const dir = a.str("dir", process.env.THINKIFIC_DIR ?? DEFAULT_THINKIFIC_DIR)!;
  if (!existsSync(dir)) throw new Error(`Thinkific data dir not found: ${dir}`);
  const { db, sql } = connect();
  try {
    const cid = await ensureCycle(db, await loadCycleDef(db, "2025-26"));
    const seed = seedPlansFromThinkific(listTkCourses(dir));
    await upsertDeptPlans(db, cid, seed.plans);
    const lines = ["# Thinkific content flags (review before publishing)", "", ...seed.flags.filter((f) => f.flag.severity === "warn").map((f) => `- [${f.department}] ${f.lesson}: ${f.flag.detail}`),
      "", "## Info", "", ...seed.flags.filter((f) => f.flag.severity === "info").map((f) => `- [${f.department}] ${f.lesson}: ${f.flag.detail}`), ""];
    writeOut("content-flags.md", lines.join("\n"));
    console.log(`2025-26: ${seed.plans.length} stale dept plans seeded (source thinkific-2025-26); ${seed.flags.length} content flags -> out/content-flags.md; missing: ${seed.missing.length}`);
  } finally { await sql.end(); }
}

export async function cmdGapReport(a: Args) {
  const label = a.str("cycle", DEFAULT_CYCLE)!; const dataDir = a.str("data"); const carry = a.str("carry-over", "2025-26")!;
  const { db, sql } = connect();
  try {
    const cid = await getCycleId(db, label);
    if (cid === null) throw new Error(`cycle ${label} not found; run 'roster' first`);
    const issues: Issue[] = [];
    if (dataDir) {
      const f = (n: string) => join(dataDir, n);
      if (existsSync(f("dept_plans.csv"))) issues.push(...parseDeptPlans(read(f("dept_plans.csv"))).issues);
      if (existsSync(f("directory_overrides.csv"))) issues.push(...parseOverrides(read(f("directory_overrides.csv"))).issues);
      if (existsSync(f("names.csv"))) issues.push(...parseNames(read(f("names.csv"))).issues);
    }
    const excluded = configFrom(a).excludedDepartments;
    const roster = (await loadRoster(db, cid, excluded)).map((r) => ({ ...r, level: r.level as "national" | "region" | "majlis", personName: r.personName }));
    const own = (await loadPlans(db, cid)).map((p) => ({ departmentSlug: p.departmentSlug, level: p.level, stale: p.stale, source: p.source }));
    const have = new Set(own.map((p) => p.departmentSlug));
    const carryId = await getCycleId(db, carry);
    const carried = carryId === null ? [] : (await loadPlans(db, carryId)).filter((p) => !have.has(p.departmentSlug)).map((p) => ({ departmentSlug: p.departmentSlug, level: p.level, stale: true, source: `${p.source} (carried over)` }));
    const { markdown, counts } = buildGapReport({ cycleLabel: label, roster, plans: [...own, ...carried], issues, excludedDepartments: excluded, notes: [
      "Muqami is counted among the 52 Majlis in the fork's MAJLIS_TO_REGION and is also a region; muqami@ is the national Mohtamim Muqami and also the Muqami chapter Qaid (no qaid.muqami@; General course only, no department course).",
      "Names are optional enrichment: supply names.csv (email,name) to fill them. Thinkific directory snapshots were not imported (PII, stale).",
    ] });
    const path = writeOut("data-gap-report.md", markdown);
    console.log(`gap report -> ${path}\n${JSON.stringify(counts)}`);
  } finally { await sql.end(); }
}
export { applyOverrides };
