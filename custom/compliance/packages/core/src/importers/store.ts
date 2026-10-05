import { eq, sql } from "drizzle-orm";
import type { PostgresJsDatabase } from "drizzle-orm/postgres-js";
import { cycle, deptPlan, directoryOverride, personRole } from "../schema";
import type { DeptPlanInput } from "./dept-plans";
import type { OverrideInput } from "./overrides";

export async function ensureCycle(db: PostgresJsDatabase<any>, c: { label: string; startsOn: string; deadlineOn: string }, update = false): Promise<number> {
  if (update) await db.insert(cycle).values(c).onConflictDoUpdate({ target: cycle.label, set: { startsOn: c.startsOn, deadlineOn: c.deadlineOn } });
  else await db.insert(cycle).values(c).onConflictDoNothing({ target: cycle.label });
  const [row] = await db.select().from(cycle).where(eq(cycle.label, c.label));
  return row!.id;
}
export async function getCycleId(db: PostgresJsDatabase<any>, label: string): Promise<number | null> {
  const [row] = await db.select().from(cycle).where(eq(cycle.label, label));
  return row?.id ?? null;
}
/** Idempotent on (cycle, department, level). */
export async function upsertDeptPlans(db: PostgresJsDatabase<any>, cycleId: number, rows: DeptPlanInput[]): Promise<number> {
  for (const r of rows) {
    await db.insert(deptPlan).values({ cycleId, ...r }).onConflictDoUpdate({
      target: [deptPlan.cycleId, deptPlan.departmentSlug, deptPlan.level],
      set: { responsibilitiesMd: r.responsibilitiesMd, okrsMd: r.okrsMd, resourcesMd: r.resourcesMd, responsibilitiesDoc: r.responsibilitiesDoc as any, okrsDoc: r.okrsDoc as any, resourcesDoc: r.resourcesDoc as any, updatedBy: r.updatedBy, stale: r.stale, source: r.source, updatedAt: sql`now()` },
    });
  }
  return rows.length;
}
export async function upsertOverrides(db: PostgresJsDatabase<any>, cycleId: number, rows: OverrideInput[]): Promise<number> {
  for (const r of rows) {
    await db.insert(directoryOverride).values({ cycleId, departmentSlug: r.departmentSlug, level: r.level, role: r.role, region: r.region, majlis: r.majlis, learnerEmail: r.learnerEmail, personName: r.personName, note: r.note })
      .onConflictDoUpdate({ target: [directoryOverride.cycleId, directoryOverride.departmentSlug, directoryOverride.level, directoryOverride.role, directoryOverride.region, directoryOverride.majlis], set: { learnerEmail: r.learnerEmail, personName: r.personName, note: r.note } });
  }
  return rows.length;
}
export async function loadRoster(db: PostgresJsDatabase<any>, cycleId: number) {
  return db.select().from(personRole).where(eq(personRole.cycleId, cycleId));
}

/** Apply stored overrides + names to person_role rows in place. Returns rows changed and pure-apply issues. */
export async function applyStoredOverrides(db: PostgresJsDatabase<any>, cycleId: number) {
  const { applyOverrides } = await import("./overrides");
  const rows = await loadRoster(db, cycleId);
  const ovs = await db.select().from(directoryOverride).where(eq(directoryOverride.cycleId, cycleId));
  const inputs = ovs.map((o) => ({ departmentSlug: o.departmentSlug, level: o.level as "national" | "region" | "majlis", role: o.role, region: o.region, majlis: o.majlis, learnerEmail: o.learnerEmail, personName: o.personName, note: o.note }));
  const { roster, issues } = applyOverrides(rows as any[], inputs);
  let changed = 0;
  for (let i = 0; i < roster.length; i++) {
    const a = rows[i]!, b = roster[i]!;
    if (a.learnerEmail !== b.learnerEmail || a.personName !== b.personName || a.source !== b.source) {
      await db.update(personRole).set({ learnerEmail: b.learnerEmail, personName: b.personName, source: b.source, updatedAt: sql`now()` }).where(eq(personRole.id, a.id));
      changed++;
    }
  }
  return { changed, issues };
}

/** Set person_name for existing roster mailboxes. Returns emails not found in the roster. */
export async function applyNames(db: PostgresJsDatabase<any>, cycleId: number, names: Map<string, string>) {
  const rows = await loadRoster(db, cycleId);
  const byEmail = new Map<string, number[]>();
  for (const r of rows) byEmail.set(r.learnerEmail, [...(byEmail.get(r.learnerEmail) ?? []), r.id]);
  let updated = 0; const unknown: string[] = [];
  for (const [email, name] of names) {
    const ids = byEmail.get(email);
    if (!ids) { unknown.push(email); continue; }
    for (const id of ids) { await db.update(personRole).set({ personName: name, updatedAt: sql`now()` }).where(eq(personRole.id, id)); updated++; }
  }
  return { updated, unknown };
}
export async function loadPlans(db: PostgresJsDatabase<any>, cycleId: number) {
  return db.select().from(deptPlan).where(eq(deptPlan.cycleId, cycleId));
}

import { enrollmentLog } from "../schema";
export async function upsertEnrollmentLog(db: PostgresJsDatabase<any>, cycleId: number, rows: { email: string; courseUuid: string; userId: number | null; status: string }[]) {
  for (const r of rows) {
    await db.insert(enrollmentLog).values({ cycleId, lhCourseUuid: r.courseUuid, learnerEmail: r.email, lhUserId: r.userId, status: r.status })
      .onConflictDoUpdate({ target: [enrollmentLog.cycleId, enrollmentLog.lhCourseUuid, enrollmentLog.learnerEmail], set: { lhUserId: r.userId, status: r.status, updatedAt: sql`now()` } });
  }
}

export async function getCycleRow(db: PostgresJsDatabase<any>, label: string) {
  const [row] = await db.select().from(cycle).where(eq(cycle.label, label));
  return row ?? null;
}
