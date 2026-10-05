import { pgTable, serial, integer, text, timestamp, unique } from "drizzle-orm/pg-core";
import { cycle } from "./cycle";

/** Manual corrections to the generated directory (name, email, notes). */
export const directoryOverride = pgTable(
  "directory_override",
  {
    id: serial("id").primaryKey(),
    cycleId: integer("cycle_id").notNull().references(() => cycle.id, { onDelete: "cascade" }),
    departmentSlug: text("department_slug").notNull().default(""),
    level: text("level").notNull(),
    role: text("role").notNull().default(""),
    region: text("region").notNull().default(""),
    majlis: text("majlis").notNull().default(""),
    learnerEmail: text("learner_email"),
    personName: text("person_name"),
    note: text("note"),
    createdBy: text("created_by"),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (t) => [unique("directory_override_key").on(t.cycleId, t.departmentSlug, t.level, t.role, t.region, t.majlis)],
);
