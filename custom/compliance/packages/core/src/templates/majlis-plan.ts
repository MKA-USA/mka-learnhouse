import { audience, audienceId, calloutWarning, doc, h, p, table, ul, type PMDoc, type PMNode } from "../content/pm";
import type { DepartmentSeed } from "../seed/departments";
import { signOffTasks } from "./attestation";
import { generatedNote } from "./department";
import { buildMajlisQuiz, extractObjectives } from "./quiz";
import type { ChapterSpec, CourseSpec, PlanInput, QuizQuestion } from "./types";
import { QUIZ_INSTRUCTION, SIGNOFF_INSTRUCTION, courseName, deptLabel } from "./util";

const MKA_DOMAIN = "mkausa.org";

/** Key results listed in a level row's doc (the "What this means at the X level" bullet list). */
export function countKeyResults(d: PMDoc | null | undefined): number {
  return (d?.content ?? []).filter((n) => n.type === "bulletList").reduce((n, l) => n + (l.content?.length ?? 0), 0);
}

/** Estimated time: 20 department pages (about 180 words each at 200 wpm, about 20 min), the overview (about 3 min), then 4 questions and sign-off (about 5 min), plus margin for reflecting on your own Majlis. */
export const MAJLIS_PLAN_MINUTES = 45;

/** Department pages are grouped into chapters by theme (display order within a group is this order). A department not listed here goes to the last group. */
export const MAJLIS_PLAN_GROUPS: { key: string; name: string; description: string; slugs: string[] }[] = [
  { key: "ch-depts", name: "Spiritual and moral training", description: "Tarbiyyat, Taleem, Tabligh, Wasiyyat, Waqf-e-Nau and Nau Mubaeen", slugs: ["tarbiyyat", "taleem", "tabligh", "wasiyyat", "waqf-e-nau", "nau-mubaeen"] },
  { key: "ch-group-admin", name: "Administration and finance", description: "Aitmad, Maal, Mohasib, Tajneed and Tahrik-e-Jadid", slugs: ["aitmad", "maal", "mohasib", "tajneed", "tahrik-e-jadid"] },
  { key: "ch-group-service", name: "Service and community", description: "Amoomi, Khidmat-e-Khalq, Waqar-e-Amal, Ishaat and New Immigrants", slugs: ["amoomi", "khidmat-e-khalq", "waqar-e-amal", "ishaat", "new-immigrants"] },
  { key: "ch-group-students", name: "Students, health and careers", description: "Amoor-e-Tuluba, Sehat-e-Jismani, Sanat-o-Tijarat and Rishta Nata", slugs: ["amoor-e-tuluba", "sehat-e-jismani", "sanat-o-tijarat", "rishta-nata"] },
];

export interface MajlisPlanInput {
  cycle: string; deadline: string;
  /** Active departments in display order. */
  departments: DepartmentSeed[];
  /** Plans for every department, all levels (own cycle, or carried over). */
  plansFor: (slug: string) => PlanInput[];
}

/**
 * "Majlis Plan" course for Qaideen and Naib Qaideen (Constitution cl. 145-146: the Qaid supervises all affairs and implements
 * all national instructions). Generated from the same dept_plans rows as the department courses; no new data.
 */
export function buildMajlisPlanCourse(a: MajlisPlanInput): { spec: CourseSpec } {
  const { cycle } = a; const flags: string[] = [];
  const per = a.departments.map((d) => {
    const plans = a.plansFor(d.slug); const at = (lvl: string) => plans.find((x) => x.level === lvl)?.okrsDoc ?? null;
    const objectives = [...new Set(plans.flatMap((x) => extractObjectives(x.okrsDoc)))];
    return { d, plans, objectives, local: at("majlis"), regional: at("region"), nLocal: countKeyResults(at("majlis")), nRegional: countKeyResults(at("region")) };
  });
  for (const x of per) if (!x.plans.length) flags.push(`${x.d.name}: no plan for this department`); else if (x.plans.every((pl) => pl.stale)) flags.push(`${x.d.name}: plan is stale (carried over)`);

  const overview: PMNode[] = [
    generatedNote(`${cycle} Department Plans`, "update the plans with Aitmad"),
    p("As Qaid or Naib Qaid you supervise all affairs of your Majlis and implement every national instruction. This course lists each department's key results for you: the Local ones you carry out in your Majlis and the Regional ones your region carries out. Each department's own officeholders get a separate course for their detailed plan."),
    h(2, "Departments at a glance"),
    table(["Department", "Local key results", "Regional key results", "Mohtamim mailbox"],
      per.map((x) => [deptLabel(x.d.name, x.d.translation), String(x.nLocal), String(x.nRegional), `${x.d.mailboxPrefix}@${MKA_DOMAIN}`])),
  ];

  const section = (slug: string, lvl: "majlis" | "region", title: string, d: PMDoc | null, groups: Record<string, string[]>[], label: string): PMNode[] => {
    const body: PMNode[] = [h(2, title), ...(d ? d.content : [p("This department has no key results at this level.")])];
    return [audience(audienceId(cycle, "majlis-plan", slug, lvl), groups, label, body)];
  };
  const deptPages = per.map((x) => ({
    kind: "page" as const, key: `dept-${x.d.slug}`, name: x.d.name,
    doc: doc(
      generatedNote(`${cycle} Department Plan`, "update the plan with Aitmad"),
      h(2, deptLabel(x.d.name, x.d.translation)),
      ...(x.objectives.length ? [p("Objectives this year:"), ul(x.objectives)] : [calloutWarning(`Content pending: the ${cycle} ${x.d.name} plan has not been provided yet.`)]),
      ...section(x.d.slug, "majlis", "Local key results", x.local, [{ level: ["local"] }, { level: ["national"] }], "Local officeholders"),
      ...section(x.d.slug, "region", "Regional key results", x.regional, [{ level: ["regional"] }, { level: ["national"] }], "Regional officeholders"),
    ),
  }));

  const quiz = buildMajlisQuiz({ cycle, items: per.map((x) => ({ slug: x.d.slug, name: x.d.name, objectives: x.objectives })) });
  if (quiz.basis === "fallback") flags.push("knowledge check is the generic fallback (too few department objectives)");
  const groupChapters = (pages: typeof deptPages): ChapterSpec[] => {
    const known = new Set(MAJLIS_PLAN_GROUPS.flatMap((g) => g.slugs));
    const out = MAJLIS_PLAN_GROUPS.map((g) => ({ g, acts: g.slugs.map((s) => pages.find((p) => p.key === `dept-${s}`)).filter((p): p is (typeof pages)[number] => !!p) }));
    const strays = pages.filter((p) => !known.has(p.key.slice("dept-".length)));
    if (strays.length) out[out.length - 1]!.acts.push(...strays);
    return out.filter((x) => x.acts.length).map((x): ChapterSpec => ({ key: x.g.key, name: x.g.name, description: x.g.description, activities: x.acts }));
  };
  const chapters: ChapterSpec[] = [
    { key: "ch-overview", name: "Overview", description: "What the Majlis Plan is and who owns each department", activities: [{ kind: "page", key: "overview", name: "Majlis Plan overview", doc: doc(...overview) }] },
    ...groupChapters(deptPages),
    { key: "ch-finish", name: "Finish", description: "Knowledge check and sign-off", activities: [
      { kind: "assignment", key: "knowledge-check", name: "Knowledge check: department plans", title: "Knowledge check: department plans", description: `Check that you know which department owns which objective. ${QUIZ_INSTRUCTION}`, ungraded: false, passThreshold: 60,
        tasks: [{ key: "plan-quiz", type: "QUIZ", title: "Department plans", description: "Choose the best answer.", hint: "Review the department pages if unsure.", contents: { grading_mode: "ALL_OR_NOTHING", questions: quiz.questions as QuizQuestion[] } }] },
      { kind: "assignment", key: "signoff", name: "Final sign-off", title: "Final sign-off", description: `Confirm and sign to complete this course. ${SIGNOFF_INSTRUCTION}`, ungraded: true, tasks: signOffTasks(cycle, "majlis-plan") },
    ] },
  ];
  return { spec: {
    key: `${cycle}|majlis-plan`, kind: "majlis-plan", departmentSlug: "", cycle, name: courseName(cycle, "Majlis Plan"),
    description: `Every department's Local and Regional key results for your Majlis and region, then a knowledge check and sign-off. About ${MAJLIS_PLAN_MINUTES} minutes. Complete by ${a.deadline}.`,
    about: "Required annual training for Qaideen and Naib Qaideen: all departments' Local and Regional key results, a knowledge check and a sign-off.",
    learnings: "Each department's objectives and key results, who owns them, what your Majlis and region must deliver", tags: `mka,compliance,${cycle},majlis-plan`, chapters, flags,
  } };
}
