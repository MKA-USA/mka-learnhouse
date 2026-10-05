import postgres from "postgres";
import { drizzle, type PostgresJsDatabase } from "drizzle-orm/postgres-js";

export type Db = PostgresJsDatabase<any>;

export function defaultDatabaseUrl(env: Record<string, string | undefined> = process.env): string {
  if (env.DATABASE_URL) return env.DATABASE_URL;
  const pw = env.COMPLIANCE_DB_PASSWORD;
  if (!pw) throw new Error("Set DATABASE_URL or COMPLIANCE_DB_PASSWORD (see .env.example)");
  return `postgres://compliance:${encodeURIComponent(pw)}@127.0.0.1:5433/compliance`;
}

export function connect(url = defaultDatabaseUrl()) {
  const sql = postgres(url, { max: 4 });
  return { sql, db: drizzle(sql) };
}
