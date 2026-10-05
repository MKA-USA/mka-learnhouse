import { sql } from "drizzle-orm";
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
      set: { roleTitle: sql`excluded.role_title`, learnerEmail: sql`excluded.learner_email`,
        personName: sql`coalesce(excluded.person_name, person_role.person_name)`, updatedAt: sql`now()` },
      setWhere: sql`${personRole.source} like 'formula%'`,
    });
  }
  return rows.length;
}
