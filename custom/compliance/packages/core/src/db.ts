import postgres from "postgres";
import { drizzle } from "drizzle-orm/postgres-js";

export const DEFAULT_DATABASE_URL = "postgres://compliance:compliance@localhost:5433/compliance";

export function connect(url = process.env.DATABASE_URL ?? DEFAULT_DATABASE_URL) {
  const sql = postgres(url, { max: 4 });
  return { sql, db: drizzle(sql) };
}
