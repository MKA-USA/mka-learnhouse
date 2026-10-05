import { sql } from "drizzle-orm";
import type { PostgresJsDatabase } from "drizzle-orm/postgres-js";
import { department } from "../schema";
import { DEFAULT_EXCLUDED_DEPARTMENTS } from "../config";
import { DEPARTMENTS } from "./departments";

/** Idempotent upsert keyed on slug. */
export async function seedDepartments(db: PostgresJsDatabase<any>, excluded: readonly string[] = DEFAULT_EXCLUDED_DEPARTMENTS): Promise<number> {
  const rows = DEPARTMENTS.map((x, i) => ({ ...x, sortOrder: i, active: !excluded.includes(x.slug) }));
  await db
    .insert(department)
    .values(rows)
    .onConflictDoUpdate({
      target: department.slug,
      set: {
        name: sql`excluded.name`, translation: sql`excluded.translation`,
        mailboxPrefix: sql`excluded.mailbox_prefix`, active: sql`excluded.active`, sortOrder: sql`excluded.sort_order`,
        updatedAt: sql`now()`,
      },
    });
  return rows.length;
}
