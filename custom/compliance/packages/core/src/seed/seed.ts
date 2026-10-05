import { sql } from "drizzle-orm";
import type { PostgresJsDatabase } from "drizzle-orm/postgres-js";
import { department } from "../schema";
import { DEPARTMENTS } from "./departments";

/** Idempotent upsert keyed on slug. */
export async function seedDepartments(db: PostgresJsDatabase<any>): Promise<number> {
  const rows = DEPARTMENTS.map((x, i) => ({ ...x, sortOrder: i }));
  await db
    .insert(department)
    .values(rows)
    .onConflictDoUpdate({
      target: department.slug,
      set: {
        name: sql`excluded.name`, translation: sql`excluded.translation`,
        mailboxPrefix: sql`excluded.mailbox_prefix`, sortOrder: sql`excluded.sort_order`,
        updatedAt: sql`now()`,
      },
    });
  return rows.length;
}
