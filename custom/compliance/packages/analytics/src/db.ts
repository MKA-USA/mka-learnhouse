import { and, asc, eq, gte, sql } from "drizzle-orm";
import type { PostgresJsDatabase } from "drizzle-orm/postgres-js";
import { cycle as cycleTable } from "../../core/src/schema/cycle";
import { DEPARTMENTS } from "../../core/src/seed/departments";
import { addDays } from "./dates";
import { EXECUTIVE, type Dataset } from "./dataset";
import { dashboardAccessOverride, progressSnapshot, snapshotRun } from "./schema";
import type { SnapshotStore } from "./sync";
import type { ScopeOverride } from "./scope";
import type { Level, ScoredLearner, Stage, Status } from "./types";

type Db = PostgresJsDatabase<Record<string, unknown>>;

// camelCase property -> SQL column, for ON CONFLICT ... SET col = excluded.col
const COLS = {
  departmentSlug: "department_slug", level: "level", region: "region", majlis: "majlis", roleTitle: "role_title", learnerEmail: "learner_email",
  personName: "person_name", appointedOn: "appointed_on", dueOn: "due_on", stage: "stage", status: "status", overdue: "overdue", daysOverdue: "days_overdue",
  lessonsDone: "lessons_done", lessonsTotal: "lessons_total", quizAvg: "quiz_avg", completedAt: "completed_at", attestedAt: "attested_at",
  lastActivityAt: "last_activity_at", expectedAttested: "expected_attested", selfCheckAnswered: "self_check_answered", selfCheckMismatches: "self_check_mismatches",
} as const;
const UPDATE_COLS = Object.keys(COLS) as (keyof typeof COLS)[];

export function drizzleStore(db: Db): SnapshotStore {
  return {
    async startRun(r) {
      const [row] = await db.insert(snapshotRun).values({ cycleId: r.cycleId, snapshotDate: r.date, source: r.source, status: "running" }).returning({ id: snapshotRun.id });
      return row!.id;
    },
    async upsertSnapshots(cycleId, date, rows) {
      for (let i = 0; i < rows.length; i += 500) {
        await db.insert(progressSnapshot).values(rows.slice(i, i + 500).map((r) => ({
          cycleId, snapshotDate: date, rosterKey: r.rosterId, departmentSlug: r.departmentSlug, level: r.level, region: r.region, majlis: r.majlis,
          roleTitle: r.roleTitle, learnerEmail: r.email, personName: r.personName, appointedOn: r.appointedOn, dueOn: r.dueOn, stage: r.stage, status: r.status,
          overdue: r.overdue, daysOverdue: r.daysOverdue, lessonsDone: r.lessonsDone, lessonsTotal: r.lessonsTotal, quizAvg: r.quizAvg,
          completedAt: r.completedAt, attestedAt: r.attestedAt, lastActivityAt: r.lastActivityAt, expectedAttested: r.expectedAttested,
          selfCheckAnswered: r.selfCheckAnswered, selfCheckMismatches: r.selfCheckMismatches,
        }))).onConflictDoUpdate({
          target: [progressSnapshot.cycleId, progressSnapshot.snapshotDate, progressSnapshot.rosterKey],
          set: Object.fromEntries(UPDATE_COLS.map((c) => [c, sql.raw(`excluded."${COLS[c]}"`)])) as Record<string, ReturnType<typeof sql.raw>>,
        });
      }
    },
    async finishRun(id, r) {
      await db.update(snapshotRun).set({ status: r.status, learners: r.learners, errors: r.errors, note: r.note ?? null, finishedAt: new Date() }).where(eq(snapshotRun.id, id));
    },
  };
}

/** Dataset from stored snapshots (UNVERIFIED against a live DB in this workstream: written to the schema, covered by typecheck only). */
export async function loadDatasetFromDb(db: Db, opts: { cycleLabel: string; asOf: string; historyDays?: number }): Promise<Dataset> {
  const [cyc] = await db.select().from(cycleTable).where(eq(cycleTable.label, opts.cycleLabel));
  if (!cyc) throw new Error(`cycle ${opts.cycleLabel} not found`);
  const from = addDays(opts.asOf, -(opts.historyDays ?? 14));
  const rows = await db.select().from(progressSnapshot)
    .where(and(eq(progressSnapshot.cycleId, cyc.id), gte(progressSnapshot.snapshotDate, from))).orderBy(asc(progressSnapshot.snapshotDate));
  const history: Record<string, ScoredLearner[]> = {};
  for (const r of rows) {
    (history[r.snapshotDate] ??= []).push({
      rosterId: r.rosterKey, email: r.learnerEmail, personName: r.personName, departmentSlug: r.departmentSlug, level: r.level as Level, region: r.region,
      majlis: r.majlis, roleTitle: r.roleTitle, appointedOn: r.appointedOn, stage: r.stage as Stage, status: r.status as Status, overdue: r.overdue,
      lessonsDone: r.lessonsDone, lessonsTotal: r.lessonsTotal, quizAvg: r.quizAvg, completedAt: r.completedAt, attestedAt: r.attestedAt,
      lastActivityAt: r.lastActivityAt, dueOn: r.dueOn, daysOverdue: r.daysOverdue, expectedAttested: r.expectedAttested,
      selfCheckAnswered: r.selfCheckAnswered, selfCheckMismatches: r.selfCheckMismatches,
    });
  }
  const dates = Object.keys(history).sort();
  const asOf = [...dates].reverse().find((d) => d <= opts.asOf) ?? opts.asOf;
  return {
    source: "snapshots", cycle: { label: cyc.label, startsOn: cyc.startsOn, deadlineOn: cyc.deadlineOn }, asOf, rows: history[asOf] ?? [], history,
    departments: [...DEPARTMENTS.map((d) => ({ slug: d.slug, name: d.name })), EXECUTIVE],
  };
}

export async function loadOverrides(db: Db): Promise<ScopeOverride[]> {
  return (await db.select().from(dashboardAccessOverride)).map((o) => ({ email: o.email, scopeType: o.scopeType as ScopeOverride["scopeType"], scopeValue: o.scopeValue }));
}
