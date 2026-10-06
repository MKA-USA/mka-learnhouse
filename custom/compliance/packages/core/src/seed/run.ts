import { resolveConfig } from "../config";
import { connect } from "../db";
import { seedDepartments } from "./seed";

const { db, sql } = connect();
const cfg = resolveConfig({ includeAtfal: process.argv.includes("--include-atfal") });
const n = await seedDepartments(db, cfg.excludedDepartments);
console.log(`seeded ${n} departments (inactive: ${cfg.excludedDepartments.join(", ") || "none"})`);
await sql.end();
