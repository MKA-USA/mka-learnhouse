import { and, eq, inArray, like, sql } from "drizzle-orm";
import type { PostgresJsDatabase } from "drizzle-orm/postgres-js";
import { personRole } from "../schema";
import type { RosterRow } from "./generate";

/** Idempotent upsert. Never overwrites rows whose source does not start with 'formula' (imports/overrides win). */
export async function upsertRoster(db: PostgresJsDatabase<any>, cycleId: number, rows: RosterRow[]): Promise<number> {
  for (let i = 0; i < rows.length; i += 500) {
    await db.insert(personRole).values(rows.slice(i, i + 500).map((r) => ({
      cycleId, departmentSlug: r.departmentSlug, role: r.role, slot: r.slot ?? "", level: r.level, region: r.region, majlis: r.majlis,
      roleTitle: r.roleTitle, learnerEmail: r.learnerEmail, personName: r.personName ?? null, source: r.source,
    }))).onConflictDoUpdate({
      target: [personRole.cycleId, personRole.role, personRole.departmentSlug, personRole.level, personRole.slot, personRole.region, personRole.majlis],
      set: { roleTitle: sql`excluded.role_title`, source: sql`excluded.source`, learnerEmail: sql`excluded.learner_email`,
        personName: sql`coalesce(excluded.person_name, person_role.person_name)`, updatedAt: sql`now()` },
      setWhere: sql`${personRole.source} like 'formula%'`,
    });
  }
  return rows.length;
}

/** Removes generated (`formula%`) roster rows of excluded departments left over from an earlier run, so stale Atfal rows cannot linger in person_role.
 *  Rows from imports/overrides are never touched. Returns the number of deleted rows. */
export async function pruneExcludedRoster(db: PostgresJsDatabase<any>, cycleId: number, excluded: readonly string[]): Promise<number> {
  if (!excluded.length) return 0;
  const gone = await db.delete(personRole).where(and(eq(personRole.cycleId, cycleId), inArray(personRole.departmentSlug, [...excluded]), like(personRole.source, "formula%"))).returning({ id: personRole.id });
  return gone.length;
}
