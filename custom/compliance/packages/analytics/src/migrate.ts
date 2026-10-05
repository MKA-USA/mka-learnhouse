import { drizzle } from "drizzle-orm/postgres-js";
import { migrate } from "drizzle-orm/postgres-js/migrator";
import postgres from "postgres";

// Applies ./drizzle (analytics only). Run core's migrations first: progress_snapshot references core's `cycle`.
const url = process.env.DATABASE_URL ?? "postgres://compliance:compliance@localhost:5433/compliance";
const sql = postgres(url, { max: 1 });
await migrate(drizzle(sql), { migrationsFolder: new URL("../drizzle", import.meta.url).pathname, migrationsTable: "__drizzle_migrations_analytics" });
await sql.end();
console.log("analytics migrations applied");
