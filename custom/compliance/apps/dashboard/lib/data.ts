import { buildFixtureDataset, type Dataset } from "@mka/analytics/pure";
import type { ScopeOverride } from "@mka/analytics/scope";
import { env } from "@/lib/env";

const g = globalThis as unknown as { __mkaFixture?: Dataset };

/** Whole dataset (unscoped). NEVER hand this to a page: go through lib/access.ts. */
export async function getDataset(): Promise<Dataset> {
  if (env.fixtureMode() || !process.env.DATABASE_URL) {
    if (!env.fixtureMode() && process.env.NODE_ENV === "production") throw new Error("DATABASE_URL is required in production");
    return (g.__mkaFixture ??= buildFixtureDataset({ asOf: env.asOf(), historyDays: 14 }));
  }
  const [{ default: postgres }, { drizzle }, { loadDatasetFromDb }] = await Promise.all([import("postgres"), import("drizzle-orm/postgres-js"), import("@mka/analytics/db")]);
  const sql = postgres(process.env.DATABASE_URL, { max: 2 });
  try { return await loadDatasetFromDb(drizzle(sql), { cycleLabel: process.env.CYCLE_LABEL || "2026-27", asOf: new Date().toISOString().slice(0, 10) }); }
  finally { await sql.end(); }
}

export async function getOverrides(): Promise<ScopeOverride[]> {
  if (env.fixtureMode() || !process.env.DATABASE_URL) return [];
  const [{ default: postgres }, { drizzle }, { loadOverrides }] = await Promise.all([import("postgres"), import("drizzle-orm/postgres-js"), import("@mka/analytics/db")]);
  const sql = postgres(process.env.DATABASE_URL, { max: 1 });
  try { return await loadOverrides(drizzle(sql)); } finally { await sql.end(); }
}
