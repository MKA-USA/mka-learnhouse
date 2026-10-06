import { pgTable, serial, integer, text, jsonb, timestamp, unique } from "drizzle-orm/pg-core";
import { cycle } from "./cycle";

/** Maps generated courses to LearnHouse uuids. kind: 'general' | 'department'. */
export const courseMap = pgTable(
  "course_map",
  {
    id: serial("id").primaryKey(),
    cycleId: integer("cycle_id").notNull().references(() => cycle.id, { onDelete: "cascade" }),
    kind: text("kind").notNull(),
    /** department slug, or '' for the general course */
    departmentSlug: text("department_slug").notNull().default(""),
    lhCourseUuid: text("lh_course_uuid").notNull(),
    lhCourseId: integer("lh_course_id"),
    /** deterministic key -> {chapter/activity/assignment uuids} */
    structure: jsonb("structure").$type<Record<string, unknown>>().notNull().default({}),
    contentHash: text("content_hash"),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (t) => [
    unique("course_map_key").on(t.cycleId, t.kind, t.departmentSlug),
    unique("course_map_uuid").on(t.lhCourseUuid),
  ],
);
