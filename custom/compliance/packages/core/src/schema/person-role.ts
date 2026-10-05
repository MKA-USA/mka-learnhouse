import { pgTable, serial, integer, text, timestamp, unique, index } from "drizzle-orm/pg-core";
import { cycle } from "./cycle";

/**
 * One row per (cycle, department, level, region, majlis): generated from the
 * email formula for every Majlis x role. Missing names are data gaps, not
 * absent roles. region/majlis use '' (not NULL) so the unique key is idempotent.
 */
export const personRole = pgTable(
  "person_role",
  {
    id: serial("id").primaryKey(),
    cycleId: integer("cycle_id").notNull().references(() => cycle.id, { onDelete: "cascade" }),
    /** '' for roles outside any department (qaid, naib qaid, sadr, national staff). Not an FK on purpose. */
    departmentSlug: text("department_slug").notNull().default(""),
    /** nazim_dept | mohtamim | motamid | qaid | naib_qaid | regional_qaid | nazim_atfal | murabbi_atfal | sadr | national_staff */
    role: text("role").notNull().default("nazim_dept"),
    level: text("level").notNull(),
    region: text("region").notNull().default(""),
    majlis: text("majlis").notNull().default(""),
    roleTitle: text("role_title").notNull().default(""),
    learnerEmail: text("learner_email").notNull(),
    personName: text("person_name"),
    appointedOn: text("appointed_on"),
    /** 'formula' | 'import' | 'override' */
    source: text("source").notNull().default("formula"),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (t) => [
    unique("person_role_key").on(t.cycleId, t.role, t.departmentSlug, t.level, t.region, t.majlis),
    index("person_role_email_idx").on(t.cycleId, t.learnerEmail),
  ],
);
