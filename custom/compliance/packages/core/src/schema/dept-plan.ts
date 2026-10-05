import { pgTable, serial, integer, text, timestamp, boolean, jsonb, unique } from "drizzle-orm/pg-core";
import { cycle } from "./cycle";
import { department } from "./department";

/** Yearly department content (goals, OKRs, resources) per level. */
export const deptPlan = pgTable(
  "dept_plan",
  {
    id: serial("id").primaryKey(),
    cycleId: integer("cycle_id").notNull().references(() => cycle.id, { onDelete: "cascade" }),
    departmentSlug: text("department_slug").notNull().references(() => department.slug),
    level: text("level").notNull(),
    responsibilitiesMd: text("responsibilities_md").notNull().default(""),
    okrsMd: text("okrs_md").notNull().default(""),
    resourcesMd: text("resources_md").notNull().default(""),
    /** ProseMirror docs derived from the md/HTML source; the renderer reads these. */
    responsibilitiesDoc: jsonb("responsibilities_doc").$type<Record<string, unknown> | null>(),
    okrsDoc: jsonb("okrs_doc").$type<Record<string, unknown> | null>(),
    resourcesDoc: jsonb("resources_doc").$type<Record<string, unknown> | null>(),
    /** e.g. 'csv', 'thinkific-2025-26' */
    source: text("source").notNull().default("csv"),
    /** true when carried over from a previous cycle and not yet refreshed */
    stale: boolean("stale").notNull().default(false),
    updatedBy: text("updated_by"),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (t) => [unique("dept_plan_key").on(t.cycleId, t.departmentSlug, t.level)],
);
