/**
 * Daily snapshot sync: reads cycle courses through a narrow LearnHouse port, scores every roster entry and
 * writes one snapshot row per learner per day. READ-ONLY toward LearnHouse. The port is mockable; `lhPortFromApi`
 * adapts core's LhApi, `createFixturePort` simulates LearnHouse from the synthetic world.
 */
import { maxDay } from "./dates";
import { withConfig, type AttentionConfig, type DeepPartial } from "./config";
import { evaluateSelfCheck } from "./selfcheck";
import { scoreLearner } from "./status";
import type { CourseProgress, CycleInfo, LearnerRecord, RosterEntry, ScoredLearner, SelfCheckAnswers, SelfCheckExpected } from "./types";

// ---- port -----------------------------------------------------------------
export interface EnrollmentRow { userId: number; email: string; enrolledAt: string; status: string; lastLoginAt?: string | null }
export interface TrailCourse { courseUuid: string; lessonsDone: number; lessonsTotal: number; status: string; lastActivityAt: string | null; completedAt: string | null }
export type AssignmentKind = "signoff" | "selfcheck" | "quiz" | "other";
export interface AssignmentInfo { uuid: string; title: string; kind: AssignmentKind }
export interface SubmissionRow { userId: number; status: string; grade: number | null; percent: number | null; attempt: number; updatedAt: string | null }

export interface SyncLhPort {
  /** All enrollments of a course (the port pages internally). */
  listEnrollments(courseUuid: string): Promise<EnrollmentRow[]>;
  /** Every enrolled course of one user with lesson counts (one call per user). */
  getUserTrail(userId: number): Promise<TrailCourse[]>;
  listAssignments(courseUuid: string): Promise<AssignmentInfo[]>;
  listSubmissions(assignmentUuid: string): Promise<SubmissionRow[]>;
  /** Contact self-check FORM answers keyed by user id. Optional: absent = no self-check data. */
  listSelfCheckAnswers?(assignmentUuid: string): Promise<Map<number, SelfCheckAnswers>>;
}

export interface CourseRef { kind: "general" | "department"; departmentSlug: string; courseUuid: string }

export interface SnapshotStore {
  startRun(r: { cycleId: number; date: string; source: string }): Promise<number>;
  upsertSnapshots(cycleId: number, date: string, rows: ScoredLearner[]): Promise<void>;
  finishRun(id: number, r: { status: "ok" | "partial" | "failed"; learners: number; errors: number; note?: string }): Promise<void>;
}

export interface SyncOptions {
  cycle: CycleInfo & { id: number };
  roster: readonly RosterEntry[];
  courses: readonly CourseRef[];
  port: SyncLhPort;
  store: SnapshotStore;
  today: string;
  config?: DeepPartial<AttentionConfig>;
  expectedContacts?: (e: RosterEntry) => SelfCheckExpected;
  source?: string;
  /** Stop after N learners (dev/testing). */
  limit?: number;
  log?: (line: string) => void;
}

export interface SyncResult { runId: number; learners: number; errors: number; rows: ScoredLearner[] }

const lc = (s: string) => s.trim().toLowerCase();
export const rosterKeyOf = (e: Pick<RosterEntry, "departmentSlug" | "level" | "region" | "majlis">) => `${e.departmentSlug}|${e.level}|${e.region}|${e.majlis}`;

interface CourseData {
  enrolled: Map<string, EnrollmentRow>;
  signoff: Map<number, SubmissionRow>;
  quizPercents: Map<number, number[]>;
  selfCheck: Map<number, SelfCheckAnswers>;
}

async function loadCourse(port: SyncLhPort, uuid: string): Promise<CourseData> {
  const enrolled = new Map((await port.listEnrollments(uuid)).map((e) => [lc(e.email), e]));
  const signoff = new Map<number, SubmissionRow>(), quizPercents = new Map<number, number[]>(), selfCheck = new Map<number, SelfCheckAnswers>();
  for (const a of await port.listAssignments(uuid)) {
    if (a.kind === "signoff") {
      for (const s of await port.listSubmissions(a.uuid)) if (SUBMITTED.has(s.status)) signoff.set(s.userId, s);
    } else if (a.kind === "quiz") {
      for (const s of await port.listSubmissions(a.uuid)) {
        if (s.status !== "GRADED" || s.percent === null) continue;
        (quizPercents.get(s.userId) ?? quizPercents.set(s.userId, []).get(s.userId)!).push(s.percent);
      }
    } else if (a.kind === "selfcheck" && port.listSelfCheckAnswers) {
      for (const [u, ans] of await port.listSelfCheckAnswers(a.uuid)) selfCheck.set(u, ans);
    }
  }
  return { enrolled, signoff, quizPercents, selfCheck };
}
/** Statuses that count as "signed off". LATE = submitted after the assignment due date. */
const SUBMITTED = new Set(["SUBMITTED", "GRADED", "LATE"]);

function progressFor(c: CourseData | undefined, uuid: string, email: string, trailByUser: Map<number, TrailCourse[]>): { p: CourseProgress | null; userId: number | null } {
  const enr = c?.enrolled.get(lc(email));
  if (!c || !enr) return { p: null, userId: null };
  const t = trailByUser.get(enr.userId)?.find((x) => x.courseUuid === uuid);
  const sign = c.signoff.get(enr.userId);
  return {
    userId: enr.userId,
    p: {
      enrolled: true, lessonsDone: t?.lessonsDone ?? 0, lessonsTotal: t?.lessonsTotal ?? 0,
      completedAt: t?.completedAt ?? null, attestedAt: sign ? (sign.updatedAt ?? "").slice(0, 10) || null : null,
      quizScores: c.quizPercents.get(enr.userId) ?? [],
      lastActivityAt: maxDay(t?.lastActivityAt, sign?.updatedAt),
    },
  };
}

export async function runSnapshotSync(o: SyncOptions): Promise<SyncResult> {
  const cfg = withConfig(o.config);
  const log = o.log ?? (() => {});
  const runId = await o.store.startRun({ cycleId: o.cycle.id, date: o.today, source: o.source ?? "learnhouse" });
  let errors = 0;
  const rows: ScoredLearner[] = [];
  try {
    const general = o.courses.find((c) => c.kind === "general");
    const deptCourse = new Map(o.courses.filter((c) => c.kind === "department").map((c) => [c.departmentSlug, c]));
    const data = new Map<string, CourseData>();
    for (const c of o.courses) {
      try { data.set(c.courseUuid, await loadCourse(o.port, c.courseUuid)); } catch { errors++; log(`course load failed: ${c.kind} ${c.departmentSlug}`); }
    }
    const trailByUser = new Map<number, TrailCourse[]>();
    const roster = o.limit ? o.roster.slice(0, o.limit) : o.roster;
    for (const e of roster) {
      const dc = e.departmentSlug ? deptCourse.get(e.departmentSlug) : undefined;
      const g = progressFor(general ? data.get(general.courseUuid) : undefined, general?.courseUuid ?? "", e.email, trailByUser);
      const d = progressFor(dc ? data.get(dc.courseUuid) : undefined, dc?.courseUuid ?? "", e.email, trailByUser);
      // Fetch trails lazily, once per user, then recompute progress with the lesson counts.
      let failed = false;
      for (const uid of new Set([g.userId, d.userId])) {
        if (uid === null || trailByUser.has(uid)) continue;
        try { trailByUser.set(uid, await o.port.getUserTrail(uid)); } catch { errors++; failed = true; log("trail fetch failed for one learner"); }
      }
      if (failed) continue;                                     // keep yesterday's row rather than write a wrong one
      const gp = progressFor(general ? data.get(general.courseUuid) : undefined, general?.courseUuid ?? "", e.email, trailByUser);
      const dp = progressFor(dc ? data.get(dc.courseUuid) : undefined, dc?.courseUuid ?? "", e.email, trailByUser);
      const answers = dp.userId !== null ? data.get(dc!.courseUuid)?.selfCheck.get(dp.userId) : undefined;
      const rec: LearnerRecord = {
        ...e, general: gp.p, department: dp.p,
        selfCheck: answers && o.expectedContacts ? evaluateSelfCheck(answers, o.expectedContacts(e)) : undefined,
      };
      rows.push({ ...scoreLearner(rec, o.cycle, o.today, cfg), rosterId: rosterKeyOf(e) });
    }
    await o.store.upsertSnapshots(o.cycle.id, o.today, rows);
    await o.store.finishRun(runId, { status: errors ? "partial" : "ok", learners: rows.length, errors });
  } catch (e) {
    await o.store.finishRun(runId, { status: "failed", learners: rows.length, errors: errors + 1, note: e instanceof Error ? e.message.slice(0, 200) : "error" });
    throw e;
  }
  return { runId, learners: rows.length, errors, rows };
}

// ---- stores -----------------------------------------------------------------
export function memoryStore() {
  const snapshots = new Map<string, ScoredLearner[]>();   // `${cycleId}:${date}`
  const runs: { id: number; cycleId: number; date: string; source: string; status: string; learners: number; errors: number; note?: string }[] = [];
  const store: SnapshotStore = {
    async startRun(r) { runs.push({ id: runs.length + 1, cycleId: r.cycleId, date: r.date, source: r.source, status: "running", learners: 0, errors: 0 }); return runs.length; },
    async upsertSnapshots(cycleId, date, rows) {
      const k = `${cycleId}:${date}`;
      const cur = new Map((snapshots.get(k) ?? []).map((r) => [r.rosterId, r]));
      for (const r of rows) cur.set(r.rosterId, r);
      snapshots.set(k, [...cur.values()]);
    },
    async finishRun(id, r) { Object.assign(runs[id - 1]!, r); },
  };
  return { store, snapshots, runs };
}
