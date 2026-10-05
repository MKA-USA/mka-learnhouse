import { connect } from "../db";
import { seedDepartments } from "./seed";

const { db, sql } = connect();
const n = await seedDepartments(db);
console.log(`seeded ${n} departments`);
await sql.end();
