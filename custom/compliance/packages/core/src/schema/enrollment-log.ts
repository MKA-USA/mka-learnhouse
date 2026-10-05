import { pgTable, serial, integer, text, timestamp, unique } from "drizzle-orm/pg-core";
import { cycle } from "./cycle";

/** One row per (cycle, course, learner); status updated in place for idempotency. */
export const enrollmentLog = pgTable(
  "enrollment_log",
  {
    id: serial("id").primaryKey(),
    cycleId: integer("cycle_id").notNull().references(() => cycle.id, { onDelete: "cascade" }),
    lhCourseUuid: text("lh_course_uuid").notNull(),
    learnerEmail: text("learner_email").notNull(),
    lhUserId: integer("lh_user_id"),
    /** 'planned' | 'enrolled' | 'already_enrolled' | 'skipped_not_in_org' | 'failed' */
    status: text("status").notNull().default("planned"),
    detail: text("detail"),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (t) => [unique("enrollment_log_key").on(t.cycleId, t.lhCourseUuid, t.learnerEmail)],
);
