import { migrate } from "drizzle-orm/postgres-js/migrator";
import postgres from "postgres";
import { drizzle } from "drizzle-orm/postgres-js";
import { fileURLToPath } from "node:url";
import { DEFAULT_DATABASE_URL } from "./db";

const url = process.env.DATABASE_URL ?? DEFAULT_DATABASE_URL;
const sql = postgres(url, { max: 1 });
await migrate(drizzle(sql), { migrationsFolder: fileURLToPath(new URL("../drizzle", import.meta.url)) });
await sql.end();
console.log("migrations applied");
