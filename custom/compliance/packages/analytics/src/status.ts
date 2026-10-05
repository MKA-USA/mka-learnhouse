import { addDays, diffDays, maxDay, dayMs } from "./dates";
import { DEFAULT_CONFIG, type AttentionConfig } from "./config";
import type { CourseProgress, CycleInfo, LearnerRecord, ScoredLearner, Stage } from "./types";

/** Due date: appointed_on + window for people appointed after the cycle started, else the cycle deadline. */
export function dueDate(r: { appointedOn?: string | null }, cycle: CycleInfo, cfg: AttentionConfig = DEFAULT_CONFIG): string {
  const a = r.appointedOn;
  if (a && dayMs(a) !== null && diffDays(a, cycle.startsOn) > 0) return addDays(a.slice(0, 10), cfg.appointeeWindowDays);
  return cycle.deadlineOn;
}

/** Day this learner's clock starts: cycle start, or appointment if later. */
export function windowStart(r: { appointedOn?: string | null }, cycle: CycleInfo): string {
  const a = r.appointedOn;
  return a && dayMs(a) !== null && diffDays(a, cycle.startsOn) > 0 ? a.slice(0, 10) : cycle.startsOn;
}

/** Expected share of attestation on `asOf` (0..target), linear from window start to due date. */
export function expectedAttested(asOf: string, start: string, due: string, cfg: AttentionConfig = DEFAULT_CONFIG): number {
  const span = diffDays(due, start);
  const elapsed = diffDays(asOf, start);
  if (span <= 0) return elapsed >= 0 ? cfg.targetAtDeadline : 0;
  return Math.min(1, Math.max(0, elapsed / span)) * cfg.targetAtDeadline;
}

export function stageOf(r: LearnerRecord, cfg: AttentionConfig = DEFAULT_CONFIG): Stage {
  // Executives (no department) only have the general course.
  const req = cfg.requiredCourses.filter((k) => !(k === "department" && r.departmentSlug === "")).map((k) => r[k]);
  const present = req.filter((c): c is CourseProgress => !!c && c.enrolled);
  const allPresent = req.length > 0 && present.length === req.length;
  if (allPresent && present.every((c) => !!c.attestedAt)) return "attested";
  const total = present.reduce((s, c) => s + c.lessonsTotal, 0);
  const done = present.reduce((s, c) => s + c.lessonsDone, 0);
  if (allPresent && total > 0 && done >= total) return "completed";
  const anyActivity = [r.general, r.department].some((c) => c && c.enrolled && (c.lessonsDone > 0 || !!c.attestedAt));
  return anyActivity ? "in_progress" : "not_started";
}

/** Score one learner as of `asOf` (YYYY-MM-DD). Pure. */
export function scoreLearner(r: LearnerRecord, cycle: CycleInfo, asOf: string, cfg: AttentionConfig = DEFAULT_CONFIG): ScoredLearner {
  const stage = stageOf(r, cfg);
  const due = dueDate(r, cycle, cfg);
  const start = windowStart(r, cycle);
  const overdue = stage !== "attested" && diffDays(asOf, due) > 0;
  const courses = [r.general, r.department].filter((c): c is CourseProgress => !!c && c.enrolled);
  const scores = courses.flatMap((c) => c.quizScores ?? []);
  const attestedAt = stage === "attested" ? maxDay(...courses.map((c) => c.attestedAt)) : null;
  const completedAt = stage === "attested" || stage === "completed" ? maxDay(...courses.map((c) => c.completedAt)) : null;
  return {
    rosterId: r.id, email: r.email, personName: r.personName ?? null,
    departmentSlug: r.departmentSlug, level: r.level, region: r.region, majlis: r.majlis, roleTitle: r.roleTitle,
    appointedOn: r.appointedOn ?? null,
    stage, status: overdue ? "overdue" : stage, overdue,
    lessonsDone: courses.reduce((s, c) => s + c.lessonsDone, 0),
    lessonsTotal: courses.reduce((s, c) => s + c.lessonsTotal, 0),
    quizAvg: scores.length ? Math.round(scores.reduce((a, b) => a + b, 0) / scores.length) : null,
    completedAt, attestedAt,
    lastActivityAt: maxDay(...courses.map((c) => c.lastActivityAt)),
    dueOn: due,
    daysOverdue: overdue ? diffDays(asOf, due) : 0,
    expectedAttested: expectedAttested(asOf, start, due, cfg),
    selfCheckAnswered: !!r.selfCheck?.answered,
    selfCheckMismatches: r.selfCheck?.mismatches.length ?? 0,
  };
}
