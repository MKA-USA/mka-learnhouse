import { describe, expect, test } from "bun:test";
import { existsSync } from "node:fs";
import {
  DEFAULT_THINKIFIC_DIR, DEPARTMENTS, STALE_NOTE, buildDepartmentCourse, buildGeneralCourse, buildPlanQuiz, extractObjectives, foundationCourse,
  generateRoster, htmlToProseMirror, listTkCourses, loadFoundation, markdownToProseMirror, plainText, renderDirectory, specHash, type PlanInput,
} from "../src";

const dept = (slug: string) => DEPARTMENTS.find((d) => d.slug === slug)!;
const roster = generateRoster({ names: new Map([["tabligh.boston@mkausa.org", "Test Person"]]) });
const planDoc = (md: string) => markdownToProseMirror(md).doc;
const plan = (slug: string, o: Partial<PlanInput> = {}): PlanInput => ({ departmentSlug: slug, level: "all", responsibilitiesDoc: planDoc("# Duties\n- do things"), okrsDoc: planDoc("Objective 1: Grow attendance\n\nObjective 2: Run monthly drives\n\nObjective 3: Train nazims"), resourcesDoc: null, stale: false, source: "csv", ...o });
const others = ["maal", "taleem", "ishaat"].map((s, i) => plan(s, { okrsDoc: planDoc(`Objective 1: Other ${s} A\n\nObjective 2: Other ${s} B ${i}`) }));

describe("objectives + quiz", () => {
  test("extractObjectives from table text and markdown", () => {
    const d = htmlToProseMirror("<table><tr><td>Objective 1: Increase Engagement of Khuddam</td></tr><tr><td>Key Result</td></tr></table>").doc;
    expect(extractObjectives(d)).toEqual(["Increase Engagement of Khuddam"]);
  });
  test("plan-based quiz: one correct per question, distractors from other departments, deterministic", () => {
    const own = extractObjectives(plan("tabligh").okrsDoc); const other = others.flatMap((x) => extractObjectives(x.okrsDoc));
    const a = buildPlanQuiz({ cycle: "2026-27", deptSlug: "tabligh", deptName: "Tabligh", ownObjectives: own, otherObjectives: other });
    const b = buildPlanQuiz({ cycle: "2026-27", deptSlug: "tabligh", deptName: "Tabligh", ownObjectives: own, otherObjectives: other });
    expect(a.basis).toBe("plan"); expect(a).toEqual(b);
    for (const q of a.questions) { expect(q.options.filter((o) => o.assigned_right_answer).length).toBe(1); expect(q.options.length).toBe(4); expect(own).toContain(q.options.find((o) => o.assigned_right_answer)!.text); }
  });
  test("no usable objectives falls back to the generic question", () => {
    expect(buildPlanQuiz({ cycle: "c", deptSlug: "x", deptName: "X", ownObjectives: [], otherObjectives: [] }).basis).toBe("fallback");
    expect(buildPlanQuiz({ cycle: "c", deptSlug: "x", deptName: "X", ownObjectives: ["a"], otherObjectives: ["b"] }).basis).toBe("fallback");
  });
});

describe("directory", () => {
  test("generated from roster: 52 local rows, regional dept officer + Qaid per region, names where known", () => {
    const d = renderDirectory({ cycle: "2026-27", dept: dept("tabligh"), roster });
    const tables = d.content.filter((n) => n.type === "table");
    expect(tables.map((t) => t.content!.length - 1)).toEqual([1, 20, 52]);
    expect(plainText(d)).toContain("tabligh.boston@mkausa.org");
    expect(plainText(d)).toContain("Test Person");
  });
  test("Atfal lists nazim and murabbi on atfalusa.org", () => {
    const t = plainText(renderDirectory({ cycle: "2026-27", dept: dept("atfal"), roster }));
    expect(t).toContain("nazim.boston@atfalusa.org"); expect(t).toContain("murabbi.boston@atfalusa.org");
  });
});

describe("department course", () => {
  const build = (plans: PlanInput[]) => buildDepartmentCourse({ cycle: "2026-27", dept: dept("tabligh"), roster, plans, otherPlans: others, deadline: "Dec 1, 2026" });
  test("deterministic names, keys and hash", () => {
    const a = build([plan("tabligh")]); const b = build([plan("tabligh")]);
    expect(a.name).toBe("MKA 2026-27 · Tabligh");
    expect(specHash(a)).toBe(specHash(b));
    expect(a.chapters.map((c) => `${c.key}:${c.activities.map((x) => `${x.kind}/${x.key}`).join("+")}`)).toMatchSnapshot();
  });
  test("stale plan shows the visible callout and flags the quiz basis", () => {
    const c = build([plan("tabligh", { stale: true })]);
    const goals = c.chapters[0]!.activities[0]!;
    expect(goals.kind === "page" && plainText(goals.doc)).toContain(STALE_NOTE);
    expect(c.flags.join()).toContain("stale");
  });
  test("missing plan shows pending notice, never throws", () => {
    const c = build([]);
    const goals = c.chapters[0]!.activities[0]!;
    expect(goals.kind === "page" && plainText(goals.doc)).toContain("Content pending");
    expect(c.flags).toContain("no plan for this department");
  });
  test("attestation: ungraded contact self-check with 52-Majlis select + sign-off with typed name", () => {
    const c = build([plan("tabligh")]);
    const sc = c.chapters[2]!.activities[1]!; const so = c.chapters[3]!.activities[0]!;
    expect(sc.kind === "assignment" && sc.ungraded && sc.tasks.map((t) => t.type)).toEqual(["QUIZ", "FORM"]);
    if (sc.kind === "assignment" && sc.tasks[0]!.type === "QUIZ") expect(sc.tasks[0]!.contents.questions[0]!.options.length).toBe(52);
    expect(so.kind === "assignment" && so.tasks.map((t) => t.type)).toEqual(["QUIZ", "FORM"]);
  });
});

describe.skipIf(!existsSync(DEFAULT_THINKIFIC_DIR))("general course from Foundation export", () => {
  const F = loadFoundation(foundationCourse(listTkCourses(DEFAULT_THINKIFIC_DIR))!);
  const { spec, flags } = buildGeneralCourse({ cycle: "2026-27", deadline: "Dec 1, 2026", foundation: F });
  test("structure and quiz sizes preserved from source (10, 12, 2 questions)", () => {
    expect(spec.name).toBe("MKA 2026-27 · General");
    expect(spec.chapters.map((c) => c.key)).toEqual(["ch-intro", "ch-structures", "ch-resources", "ch-rules", "ch-message", "ch-signoff"]);
    const q = (k: string) => { const a = spec.chapters.flatMap((c) => c.activities).find((x) => x.key === k)!; return a.kind === "assignment" && a.tasks[0]!.type === "QUIZ" ? a.tasks[0]!.contents.questions.length : -1; };
    expect([q("quiz-jamaat"), q("quiz-khuddam"), q("quiz-rules")]).toEqual([10, 12, 2]);
    expect(spec.chapters[4]!.activities.filter((a) => a.kind === "pdf").length).toBe(2);
  });
  test("no inline styling survives; every quiz question has a correct answer", () => {
    expect(JSON.stringify(spec)).not.toMatch(/font-family|box-sizing|rgb\(/);
    for (const a of spec.chapters.flatMap((c) => c.activities)) if (a.kind === "assignment") for (const t of a.tasks) if (t.type === "QUIZ" && a.key.startsWith("quiz-")) for (const qq of t.contents.questions) expect(qq.options.some((o) => o.assigned_right_answer)).toBe(true);
  });
  test("stale-year callouts and content flags are produced", () => { expect(spec.flags.length).toBeGreaterThan(0); expect(Array.isArray(flags)).toBe(true); });
});
