/**
 * Analytics tables. Own migration folder (./drizzle) so this never conflicts with packages/core.
 * `cycle` is referenced from core; person_role is NOT referenced (roster_key mirrors its natural key
 * `dept|level|region|majlis`) so snapshots survive roster edits and stay history.
 */
import { pgTable, serial, integer, text, boolean, date, timestamp, real, unique, index } from "drizzle-orm/pg-core";
import { cycle } from "../../core/src/schema/cycle";

export const progressSnapshot = pgTable(
  "progress_snapshot",
  {
    id: serial("id").primaryKey(),
    cycleId: integer("cycle_id").notNull().references(() => cycle.id, { onDelete: "cascade" }),
    snapshotDate: date("snapshot_date", { mode: "string" }).notNull(),
    rosterKey: text("roster_key").notNull(),
    departmentSlug: text("department_slug").notNull().default(""),
    level: text("level").notNull(),
    region: text("region").notNull().default(""),
    majlis: text("majlis").notNull().default(""),
    roleTitle: text("role_title").notNull().default(""),
    learnerEmail: text("learner_email").notNull(),
    personName: text("person_name"),
    appointedOn: date("appointed_on", { mode: "string" }),
    dueOn: date("due_on", { mode: "string" }).notNull(),
    stage: text("stage").notNull(),
    status: text("status").notNull(),
    overdue: boolean("overdue").notNull().default(false),
    daysOverdue: integer("days_overdue").notNull().default(0),
    lessonsDone: integer("lessons_done").notNull().default(0),
    lessonsTotal: integer("lessons_total").notNull().default(0),
    quizAvg: integer("quiz_avg"),
    completedAt: date("completed_at", { mode: "string" }),
    attestedAt: date("attested_at", { mode: "string" }),
    lastActivityAt: date("last_activity_at", { mode: "string" }),
    expectedAttested: real("expected_attested").notNull().default(0),
    selfCheckAnswered: boolean("self_check_answered").notNull().default(false),
    selfCheckMismatches: integer("self_check_mismatches").notNull().default(0),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (t) => [
    unique("progress_snapshot_key").on(t.cycleId, t.snapshotDate, t.rosterKey),
    index("progress_snapshot_dept_idx").on(t.cycleId, t.snapshotDate, t.departmentSlug),
    index("progress_snapshot_region_idx").on(t.cycleId, t.snapshotDate, t.region),
  ],
);

/** One row per sync attempt (observability + "data as of" on the dashboard). */
export const snapshotRun = pgTable(
  "snapshot_run",
  {
    id: serial("id").primaryKey(),
    cycleId: integer("cycle_id").notNull().references(() => cycle.id, { onDelete: "cascade" }),
    snapshotDate: date("snapshot_date", { mode: "string" }).notNull(),
    source: text("source").notNull(),                     // 'learnhouse' | 'fixtures'
    status: text("status").notNull(),                     // 'running' | 'ok' | 'partial' | 'failed'
    learners: integer("learners").notNull().default(0),
    errors: integer("errors").notNull().default(0),
    note: text("note"),
    startedAt: timestamp("started_at", { withTimezone: true }).notNull().defaultNow(),
    finishedAt: timestamp("finished_at", { withTimezone: true }),
  },
  (t) => [index("snapshot_run_date_idx").on(t.cycleId, t.snapshotDate)],
);

/** Extra dashboard access beyond what attributes grant (or an explicit deny). Managed by Aitmad/admin. */
export const dashboardAccessOverride = pgTable(
  "dashboard_access_override",
  {
    id: serial("id").primaryKey(),
    email: text("email").notNull(),
    scopeType: text("scope_type").notNull(),              // 'all' | 'department' | 'region' | 'majlis' | 'deny'
    scopeValue: text("scope_value").notNull().default(""),
    reason: text("reason"),
    createdBy: text("created_by"),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (t) => [unique("dashboard_access_override_key").on(t.email, t.scopeType, t.scopeValue)],
);
