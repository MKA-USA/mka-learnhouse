import { describe, expect, test } from "bun:test";
import { dueDate, expectedAttested, scoreLearner, stageOf, windowStart } from "../src/status";
import { DEFAULT_CONFIG } from "../src/config";
import { CYCLE, course, rec } from "./helpers";

describe("due dates", () => {
  test("cycle deadline when no appointment date", () => expect(dueDate({}, CYCLE)).toBe("2026-12-01"));
  test("appointed before the cycle starts keeps the deadline", () => expect(dueDate({ appointedOn: "2026-10-15" }, CYCLE)).toBe("2026-12-01"));
  test("mid-year appointee: appointed_on + 30d", () => {
    expect(dueDate({ appointedOn: "2026-11-20" }, CYCLE)).toBe("2026-12-20");
    expect(windowStart({ appointedOn: "2026-11-20" }, CYCLE)).toBe("2026-11-20");
  });
  test("garbage appointment date is ignored", () => expect(dueDate({ appointedOn: "soon" }, CYCLE)).toBe("2026-12-01"));
});

describe("expected curve", () => {
  const f = (d: string) => expectedAttested(d, "2026-11-01", "2026-12-01");
  test("linear", () => { expect(f("2026-11-01")).toBe(0); expect(f("2026-11-16")).toBeCloseTo(0.5, 2); expect(f("2026-12-01")).toBe(1); });
  test("clamped before start and after deadline", () => { expect(f("2026-10-01")).toBe(0); expect(f("2027-01-01")).toBe(1); });
  test("target at deadline is configurable", () => expect(expectedAttested("2026-12-01", "2026-11-01", "2026-12-01", { ...DEFAULT_CONFIG, targetAtDeadline: 0.9 })).toBe(0.9));
  test("zero-length window", () => { expect(expectedAttested("2026-11-01", "2026-11-01", "2026-11-01")).toBe(1); });
});

describe("stage and status", () => {
  test("not started", () => expect(stageOf(rec())).toBe("not_started"));
  test("in progress shows n/m", () => {
    const s = scoreLearner(rec({ general: course({ lessonsDone: 2, lessonsTotal: 3 }) }), CYCLE, "2026-11-10");
    expect(s.stage).toBe("in_progress"); expect(`${s.lessonsDone}/${s.lessonsTotal}`).toBe("2/8");
  });
  test("completed needs every lesson of every required course", () => {
    const done = rec({ general: course({ lessonsDone: 3, lessonsTotal: 3 }), department: course({ lessonsDone: 5 }) });
    expect(stageOf(done)).toBe("completed");
    expect(stageOf({ ...done, department: course({ lessonsDone: 4 }) })).toBe("in_progress");
  });
  test("attested needs sign-off on both courses", () => {
    const g = course({ lessonsDone: 3, lessonsTotal: 3, attestedAt: "2026-11-05" }), d = course({ lessonsDone: 5, attestedAt: "2026-11-06" });
    expect(stageOf(rec({ general: g, department: d }))).toBe("attested");
    expect(stageOf(rec({ general: g, department: { ...d, attestedAt: null } }))).toBe("completed");
  });
  test("a course the learner is not enrolled in blocks completion", () => {
    expect(stageOf(rec({ general: course({ lessonsDone: 3, lessonsTotal: 3 }), department: null }))).toBe("in_progress");
  });
  test("executives only need the general course", () => {
    const g = course({ lessonsDone: 3, lessonsTotal: 3, attestedAt: "2026-11-05" });
    expect(stageOf(rec({ departmentSlug: "", general: g, department: null }))).toBe("attested");
  });
  test("overdue after the deadline unless attested; stage is preserved", () => {
    const s = scoreLearner(rec({ general: course({ lessonsDone: 1, lessonsTotal: 3 }) }), CYCLE, "2026-12-05");
    expect(s.status).toBe("overdue"); expect(s.stage).toBe("in_progress"); expect(s.daysOverdue).toBe(4);
  });
  test("not overdue on the deadline day itself", () => expect(scoreLearner(rec(), CYCLE, "2026-12-01").overdue).toBe(false));
  test("attested learners are never overdue", () => {
    const g = course({ lessonsDone: 3, lessonsTotal: 3, attestedAt: "2026-11-05" }), d = course({ lessonsDone: 5, attestedAt: "2026-11-06" });
    const s = scoreLearner(rec({ general: g, department: d }), CYCLE, "2027-02-01");
    expect(s.status).toBe("attested"); expect(s.attestedAt).toBe("2026-11-06");
  });
  test("mid-year appointee is judged against their own due date", () => {
    const r = rec({ appointedOn: "2026-11-20" });
    expect(scoreLearner(r, CYCLE, "2026-12-10").overdue).toBe(false);   // past the cycle deadline, inside their 30 days
    expect(scoreLearner(r, CYCLE, "2026-12-21").overdue).toBe(true);
    expect(scoreLearner(r, CYCLE, "2026-11-20").expectedAttested).toBe(0);
  });
  test("quiz average and last activity", () => {
    const s = scoreLearner(rec({ general: course({ lessonsDone: 1, lessonsTotal: 3, quizScores: [80], lastActivityAt: "2026-11-03T10:00:00" }), department: course({ quizScores: [90], lastActivityAt: "2026-11-07" }) }), CYCLE, "2026-11-10");
    expect(s.quizAvg).toBe(85); expect(s.lastActivityAt).toBe("2026-11-07");
  });
});
