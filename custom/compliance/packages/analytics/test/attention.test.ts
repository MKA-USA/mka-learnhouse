import { describe, expect, test } from "bun:test";
import { withConfig } from "../src/config";
import { aggregate, aggregateBy, type Aggregate, crossTab, cellKey } from "../src/aggregate";
import { attention, compareAttention, type Attention } from "../src/attention";
import { evaluateSelfCheck, looseMatch } from "../src/selfcheck";
import { buildSeries, trendVs } from "../src/trend";
import { scoreLearner } from "../src/status";
import type { ScoredLearner } from "../src/types";
import { CYCLE, course, rec } from "./helpers";

const attestedRec = (id: string, extra = {}) => rec({ id, email: `${id}@example.invalid`, majlis: id, general: course({ lessonsDone: 3, lessonsTotal: 3, attestedAt: "2026-11-05", completedAt: "2026-11-04" }), department: course({ lessonsDone: 5, attestedAt: "2026-11-06", completedAt: "2026-11-05" }), ...extra });
const mk = (n: number, make: (i: number) => ReturnType<typeof rec>, asOf: string): ScoredLearner[] => Array.from({ length: n }, (_, i) => scoreLearner(make(i), CYCLE, asOf));

describe("attention", () => {
  test("no learners -> none, never a divide by zero", () => {
    const a = attention(aggregate("x", [], CYCLE), CYCLE, "2026-11-20");
    expect(a.rag).toBe("none"); expect(a.score).toBe(0); expect(a.summary).toContain("No officeholders");
  });
  test("everyone attested on time -> green, on track", () => {
    const a = attention(aggregate("x", mk(10, (i) => attestedRec(`m${i}`), "2026-11-16"), CYCLE), CYCLE, "2026-11-16");
    expect(a.rag).toBe("green"); expect(a.summary).toBe("On track");
  });
  test("before the cycle starts nothing is expected", () => {
    const a = attention(aggregate("x", mk(10, (i) => rec({ id: `m${i}` }), "2026-10-20"), CYCLE), CYCLE, "2026-10-20");
    expect(a.rag).toBe("green"); expect(a.reasons).toEqual([]);
  });
  test("mid-cycle behind curve: amber/red with human reasons", () => {
    const rows = mk(52, (i) => i < 6 ? attestedRec(`m${i}`) : i < 29 ? rec({ id: `p${i}`, general: course({ lessonsDone: 1, lessonsTotal: 3 }) }) : rec({ id: `n${i}` }), "2026-11-16");
    const a = attention(aggregate("x", rows, CYCLE), CYCLE, "2026-11-16");
    expect(["amber", "red"]).toContain(a.rag);
    expect(a.reasons.join(" | ")).toContain("23 of 52 haven't started");
    expect(a.reasons.join(" | ")).toMatch(/attested 12% vs 50% expected/);
  });
  test("deadline passed: overdue count in the reason and always red at high rate", () => {
    const rows = mk(20, (i) => i < 10 ? attestedRec(`m${i}`) : rec({ id: `n${i}` }), "2026-12-05");
    const a = attention(aggregate("x", rows, CYCLE), CYCLE, "2026-12-05");
    expect(a.rag).toBe("red"); expect(a.reasons[0]).toBe("10 of 20 overdue");
  });
  test("contact mismatches alone surface as amber", () => {
    const rows = mk(10, (i) => attestedRec(`m${i}`, i < 3 ? { selfCheck: { answered: true, mismatches: ["regionalQaid"] } } : {}), "2026-11-02");
    const a = attention(aggregate("x", rows, CYCLE), CYCLE, "2026-11-02");
    expect(a.rag).toBe("amber"); expect(a.reasons.join()).toContain("3 contact self-check mismatches");
  });
  test("thresholds are configurable", () => {
    const rows = mk(10, (i) => rec({ id: `n${i}` }), "2026-11-16");
    const agg = aggregate("x", rows, CYCLE);
    const lax = attention(agg, CYCLE, "2026-11-16", withConfig({ thresholds: { amber: 90, red: 95 } }));
    expect(lax.rag).toBe("green");
  });
  test("ranking puts red before amber, then by score", () => {
    const red: { att: Attention; agg: Aggregate } = { att: { score: 40, rag: "red", shortfall: 0, reasons: [], summary: "" }, agg: aggregate("a", [], CYCLE) };
    const amber: { att: Attention; agg: Aggregate } = { att: { score: 90, rag: "amber", shortfall: 0, reasons: [], summary: "" }, agg: aggregate("b", [], CYCLE) };
    expect([amber, red].sort(compareAttention)[0]).toBe(red);
  });
});

describe("aggregates", () => {
  const rows = [
    ...mk(2, (i) => attestedRec(`a${i}`, { departmentSlug: "tabligh", region: "East" }), "2026-11-16"),
    ...mk(3, (i) => rec({ id: `b${i}`, departmentSlug: "maal", region: "East" }), "2026-11-16"),
    ...mk(1, (i) => rec({ id: `c${i}`, departmentSlug: "maal", region: "Gulf", general: course({ lessonsDone: 1, lessonsTotal: 3 }) }), "2026-11-16"),
  ];
  test("by department and cross-tab", () => {
    const by = aggregateBy(rows, "department", CYCLE);
    expect(by.map((a) => [a.key, a.expected])).toEqual([["maal", 4], ["tabligh", 2]]);
    const cells = crossTab(rows, "department", "region", CYCLE);
    expect(cells.get(cellKey("maal", "East"))!.notStarted).toBe(3);
    expect(cells.get(cellKey("maal", "Gulf"))!.inProgress).toBe(1);
    expect(cells.size).toBe(3);
  });
  test("median days to complete from each learner's own window start", () => {
    const a = aggregate("x", mk(3, (i) => attestedRec(`m${i}`, { general: course({ lessonsDone: 3, lessonsTotal: 3, attestedAt: "2026-11-05", completedAt: `2026-11-0${3 + i}` }), department: course({ lessonsDone: 5, attestedAt: "2026-11-06", completedAt: `2026-11-0${3 + i}` }) }), "2026-11-16"), CYCLE);
    expect(a.medianDaysToComplete).toBe(3);
  });
});

describe("contact self-check", () => {
  const exp = { majlis: "Albany", regionalQaid: "rqaid.northeast@example.invalid", deptHead: "tabligh@example.invalid" };
  test("correct answers", () => expect(evaluateSelfCheck({ majlis: "albany", regionalQaid: "RQAID.northeast@example.invalid", deptHead: "tabligh@example.invalid" }, exp)).toEqual({ answered: true, mismatches: [] }));
  test("mismatch is reported per field", () => expect(evaluateSelfCheck({ majlis: "Albany", regionalQaid: "qaid.east@example.invalid" }, exp).mismatches).toEqual(["regionalQaid"]));
  test("blank answers are skipped, no answers = not answered", () => {
    expect(evaluateSelfCheck({ majlis: "", regionalQaid: " " }, exp).answered).toBe(false);
    expect(evaluateSelfCheck(null, exp).answered).toBe(false);
    expect(evaluateSelfCheck({ majlis: "Albany", deptHead: "" }, exp)).toEqual({ answered: true, mismatches: [] });
  });
  test("titled names still match, short strings do not", () => { expect(looseMatch("Jane Doe", "Qaid Jane Doe")).toBe(true); expect(looseMatch("Jane Doe", "Jo")).toBe(false); });
});

describe("trend", () => {
  const day = (d: string, attested: number) => [d, mk(10, (i) => i < attested ? attestedRec(`m${i}`) : rec({ id: `n${i}` }), d)] as const;
  test("improving, worsening, unknown", () => {
    const up = buildSeries(Object.fromEntries([day("2026-11-10", 2), day("2026-11-11", 4)]), CYCLE);
    expect(trendVs(up, "2026-11-11").direction).toBe("improving");
    expect(trendVs(up, "2026-11-11").attestedDelta).toBeCloseTo(0.2, 5);
    const stuck = buildSeries(Object.fromEntries([day("2026-11-20", 2), day("2026-12-05", 2)]), CYCLE);
    expect(trendVs(stuck, "2026-12-05", 15).direction).toBe("worsening");
    expect(trendVs(up.slice(0, 1), "2026-11-10").direction).toBe("unknown");
    expect(trendVs([], "2026-11-10").direction).toBe("unknown");
  });
});
