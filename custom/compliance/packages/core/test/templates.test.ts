import { describe, expect, test } from "bun:test";
import { existsSync } from "node:fs";
import {
  DEFAULT_THINKIFIC_DIR, DEPARTMENTS, STALE_NOTE, buildDepartmentCourse, buildGeneralCourse, buildMajlisPlanCourse, buildMajlisQuiz, countKeyResults, MULTI_OFFICE_NOTE, buildPlanQuiz, extractObjectives, foundationCourse,
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
  test("default roster contains no Atfal mailbox at all", () => {
    expect(roster.some((r) => r.departmentSlug === "atfal" || r.learnerEmail.endsWith("@atfalusa.org"))).toBe(false);
  });
  test("generated from roster: 52 local rows, regional dept officer + Qaid per region, names where known", () => {
    const d = renderDirectory({ cycle: "2026-27", dept: dept("tabligh"), roster });
    const tables = d.content.filter((n) => n.type === "table");
    expect(tables.map((t) => t.content!.length - 1)).toEqual([1, 20, 52]);
    expect(plainText(d)).toContain("tabligh.boston@mkausa.org");
    expect(plainText(d)).toContain("Test Person");
  });
  test("Atfal (only when switched on) lists nazim and murabbi on atfalusa.org", () => {
    const t = plainText(renderDirectory({ cycle: "2026-27", dept: dept("atfal"), roster: generateRoster({ excludedDepartments: [] }) }));
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
  test("per-level OKR sections are wrapped in mkaAudience blocks; `all` stays unwrapped; ids are stable", () => {
    const lv = (level: string, md: string) => plan("tabligh", { level, responsibilitiesDoc: null, okrsDoc: planDoc(md) });
    const plans = [plan("tabligh"), lv("majlis", "Local KR"), lv("region", "Regional KR"), lv("national", "National KR")];
    const page = (c: ReturnType<typeof build>) => { const a = c.chapters[1]!.activities[0]!; if (a.kind !== "page") throw new Error("page"); return a.doc.content; };
    const top = page(build(plans));
    const auds = top.filter((n) => n.type === "mkaAudience");
    expect(auds.map((n) => (n.attrs!.rule as any).label)).toEqual(["National team", "Regional officeholders", "Local officeholders"]);
    expect(auds.map((n) => (n.attrs!.rule as any).groups)).toEqual([
      [{ level: ["national"] }], [{ level: ["regional"] }, { level: ["national"] }], [{ level: ["local"] }, { level: ["national"] }],
    ]);
    for (const n of auds) {
      const r = n.attrs!.rule as any;
      expect(r.v).toBe(1); expect(r.mode).toBe("show");
      expect(n.attrs!.id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
      expect(n.content![0]!.type).toBe("heading");
    }
    expect(new Set(auds.map((n) => n.attrs!.id)).size).toBe(3);
    expect(top.filter((n) => n.type !== "mkaAudience").map((n) => plainText(n)).join("")).toContain("Objective 1: Grow attendance");
    expect(JSON.stringify(page(build(plans)))).toBe(JSON.stringify(top));
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
  test("v2 structure: 4 chapters, 5 activities, role page is author-owned, generated pages carry the note", () => {
    const c = build([plan("tabligh", { resourcesDoc: planDoc("- [A link](https://example.org)") })]);
    expect(c.chapters.map((x) => x.name)).toEqual(["Your role", "Your 2026-27 plan", "Contacts", "Finish"]);
    const acts = c.chapters.flatMap((x) => x.activities);
    expect(acts.map((x) => x.key)).toEqual(["role", "plan", "knowledge-check", "directory", "signoff"]);
    expect(Object.fromEntries(acts.map((x) => [x.key, x.owner ?? "generated"]))).toMatchObject({ role: "author", plan: "generated", directory: "generated", signoff: "generated" });
    const txt = (k: string) => { const a = acts.find((x) => x.key === k)!; return a.kind === "page" ? plainText(a.doc) : ""; };
    expect(txt("role")).toContain("do things"); expect(txt("role")).toContain("Resources"); expect(txt("role")).toContain("A link");
    expect(txt("role")).not.toContain("generated from");
    expect(txt("plan")).toContain("This page is generated from the 2026-27 Department Plan. To change it, update the plan with Aitmad, not this page.");
    expect(txt("directory")).toContain("generated from the 2026-27 officeholder roster");
  });
  test("sign-off: ungraded, 2 tasks (confirm + typed name)", () => {
    const so = build([plan("tabligh")]).chapters[3]!.activities[0]!;
    expect(so.kind === "assignment" && so.ungraded && so.tasks.map((t) => t.type)).toEqual(["QUIZ", "FORM"]);
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
  test("first page carries the multi-office note", () => {
    const first = spec.chapters.flatMap((c) => c.activities).find((a) => a.kind === "page")!;
    expect(first.kind === "page" && plainText(first.doc)).toContain("Hold more than one office?");
    expect(spec.chapters.flatMap((c) => c.activities).filter((a) => a.kind === "page" && plainText(a.doc).includes("Hold more than one office?")).length).toBe(1);
  });
  test("no inline styling survives; every quiz question has a correct answer", () => {
    expect(JSON.stringify(spec)).not.toMatch(/font-family|box-sizing|rgb\(/);
    for (const a of spec.chapters.flatMap((c) => c.activities)) if (a.kind === "assignment") for (const t of a.tasks) if (t.type === "QUIZ" && a.key.startsWith("quiz-")) for (const qq of t.contents.questions) expect(qq.options.some((o) => o.assigned_right_answer)).toBe(true);
  });
  test("stale-year callouts and content flags are produced", () => { expect(spec.flags.length).toBeGreaterThan(0); expect(Array.isArray(flags)).toBe(true); });
});

describe("Majlis Plan course", () => {
  const depts = DEPARTMENTS.filter((d) => d.slug !== "atfal");
  const lvl = (slug: string, level: string, kr: string[]) => plan(slug, { level, responsibilitiesDoc: null, okrsDoc: planDoc(`What this means at the ${level} level:\n\n${kr.map((k) => `- ${k}`).join("\n")}`) });
  const plansFor = (slug: string): PlanInput[] => slug === "ishaat" ? [] : [
    plan(slug, { responsibilitiesDoc: null, okrsDoc: planDoc(`Objective 1: ${slug} first goal\n\nObjective 2: ${slug} second goal`) }),
    lvl(slug, "majlis", ["Local one", "Local two"]), ...(slug === "maal" ? [lvl(slug, "region", ["Regional one"])] : []),
  ];
  const { spec } = buildMajlisPlanCourse({ cycle: "2026-27", deadline: "Dec 1, 2026", departments: depts, plansFor });
  const page = (k: string) => { const a = spec.chapters.flatMap((c) => c.activities).find((x) => x.key === k)!; if (a.kind !== "page") throw new Error("page"); return a.doc; };
  test("name, kind and shape: 3 chapters, overview + 20 department pages + knowledge check + sign-off", () => {
    expect(spec.name).toBe("MKA 2026-27 · Majlis Plan"); expect(spec.kind).toBe("majlis-plan"); expect(spec.departmentSlug).toBe("");
    expect(spec.chapters.map((c) => c.name)).toEqual(["Overview", "Department plans", "Finish"]);
    expect(spec.chapters[1]!.activities.map((a) => a.key)).toEqual(depts.map((d) => `dept-${d.slug}`));
    expect(spec.chapters[1]!.activities.length).toBe(20);
    expect(spec.chapters[2]!.activities.map((a) => a.key)).toEqual(["knowledge-check", "signoff"]);
    const so = spec.chapters[2]!.activities[1]!; expect(so.kind === "assignment" && so.tasks.map((t) => t.type)).toEqual(["QUIZ", "FORM"]);
    expect(spec.chapters.flatMap((c) => c.activities).every((a) => (a.owner ?? "generated") === "generated")).toBe(true);
    expect(spec.flags).toContain("Ishaat: no plan for this department");
  });
  test("overview table: one row per department with local/regional KR counts and the Mohtamim mailbox", () => {
    const t = plainText(page("overview"));
    expect(t).toContain("generated from the 2026-27 Department Plans");
    const row = (d: string, l: string, r: string, m: string) => expect(t).toContain(`${d}\n\n${l}\n\n${r}\n\n${m}`);
    row("Maal (Finance)", "2", "1", "maal@mkausa.org"); row("Tabligh (Preaching)", "2", "0", "tabligh@mkausa.org");
    row("Ishaat (Publications)", "0", "0", "ishaat@mkausa.org"); row("Aitmad (General Secretary)", "2", "0", "motamid@mkausa.org");
  });
  test("department page: objectives, then Local and Regional lists wrapped in mkaAudience", () => {
    const d = page("dept-maal"); const auds = d.content.filter((n) => n.type === "mkaAudience");
    expect(auds.map((n) => (n.attrs!.rule as any).groups)).toEqual([[{ level: ["local"] }, { level: ["national"] }], [{ level: ["regional"] }, { level: ["national"] }]]);
    expect(auds.map((n) => (n.attrs!.rule as any).label)).toEqual(["Local officeholders", "Regional officeholders"]);
    expect(new Set(auds.map((n) => n.attrs!.id)).size).toBe(2);
    expect(auds.every((n) => /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(n.attrs!.id as string))).toBe(true);
    const outside = d.content.filter((n) => n.type !== "mkaAudience").map((n) => plainText(n)).join("");
    expect(outside).toContain("maal first goal"); expect(outside).not.toContain("Local one");
    expect(plainText({ type: "doc", content: auds[0]!.content! })).toContain("Local two");
    expect(plainText({ type: "doc", content: auds[1]!.content! })).toContain("Regional one");
    expect(plainText(page("dept-ishaat"))).toContain("Content pending");
  });
  test("deterministic; knowledge check asks which department owns an objective (4 questions, pass 60%)", () => {
    expect(JSON.stringify(buildMajlisPlanCourse({ cycle: "2026-27", deadline: "Dec 1, 2026", departments: depts, plansFor }).spec)).toBe(JSON.stringify(spec));
    const kc = spec.chapters[2]!.activities[0]!; if (kc.kind !== "assignment") throw new Error("assignment");
    expect(kc.passThreshold).toBe(60); expect(kc.ungraded).toBe(false);
    const qs = kc.tasks[0]!.type === "QUIZ" ? kc.tasks[0]!.contents.questions : [];
    expect(qs.length).toBe(4);
    for (const q of qs) { expect(q.options.length).toBe(4); expect(q.options.filter((o) => o.assigned_right_answer).length).toBe(1); }
  });
  test("countKeyResults and the quiz fallback", () => {
    expect(countKeyResults(planDoc("lead\n\n- a\n- b\n- c"))).toBe(3); expect(countKeyResults(null)).toBe(0);
    expect(buildMajlisQuiz({ cycle: "2026-27", items: [{ slug: "a", name: "A", objectives: ["x"] }] }).basis).toBe("fallback");
  });
});

test("General multi-office note text", () => {
  expect(plainText({ type: "doc", content: [MULTI_OFFICE_NOTE] })).toContain("Hold more than one office? Sign in with each office's @mkausa.org account and complete that office's course. Each office signs off separately.");
});
