import { defineConfig } from "drizzle-kit";
// Separate migration folder from packages/core so the two never conflict.
export default defineConfig({
  dialect: "postgresql",
  schema: "./src/schema.ts",
  out: "./drizzle",
  migrations: { table: "__drizzle_migrations_analytics" },
  dbCredentials: { url: process.env.DATABASE_URL ?? "postgres://compliance:compliance@localhost:5433/compliance" },
});
