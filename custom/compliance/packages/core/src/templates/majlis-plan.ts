import { audience, audienceId, calloutWarning, doc, h, p, table, ul, type PMDoc, type PMNode } from "../content/pm";
import type { DepartmentSeed } from "../seed/departments";
import { signOffTasks } from "./attestation";
import { generatedNote } from "./department";
import { buildMajlisQuiz, extractObjectives } from "./quiz";
import type { ChapterSpec, CourseSpec, PlanInput, QuizQuestion } from "./types";
import { courseName } from "./util";

const MKA_DOMAIN = "mkausa.org";

/** Key results listed in a level row's doc (the "What this means at the X level" bullet list). */
export function countKeyResults(d: PMDoc | null | undefined): number {
  return (d?.content ?? []).filter((n) => n.type === "bulletList").reduce((n, l) => n + (l.content?.length ?? 0), 0);
}

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
      per.map((x) => [`${x.d.name} (${x.d.translation})`, String(x.nLocal), String(x.nRegional), `${x.d.mailboxPrefix}@${MKA_DOMAIN}`])),
  ];

  const section = (slug: string, lvl: "majlis" | "region", title: string, d: PMDoc | null, groups: Record<string, string[]>[], label: string): PMNode[] => {
    const body: PMNode[] = [h(2, title), ...(d ? d.content : [p("This department has no key results at this level.")])];
    return [audience(audienceId(cycle, "majlis-plan", slug, lvl), groups, label, body)];
  };
  const deptPages = per.map((x) => ({
    kind: "page" as const, key: `dept-${x.d.slug}`, name: x.d.name,
    doc: doc(
      generatedNote(`${cycle} Department Plan`, "update the plan with Aitmad"),
      h(2, `${x.d.name} (${x.d.translation})`),
      ...(x.objectives.length ? [p("Objectives this year:"), ul(x.objectives)] : [calloutWarning(`Content pending: the ${cycle} ${x.d.name} plan has not been provided yet.`)]),
      ...section(x.d.slug, "majlis", "Local key results", x.local, [{ level: ["local"] }, { level: ["national"] }], "Local officeholders"),
      ...section(x.d.slug, "region", "Regional key results", x.regional, [{ level: ["regional"] }, { level: ["national"] }], "Regional officeholders"),
    ),
  }));

  const quiz = buildMajlisQuiz({ cycle, items: per.map((x) => ({ slug: x.d.slug, name: x.d.name, objectives: x.objectives })) });
  if (quiz.basis === "fallback") flags.push("knowledge check is the generic fallback (too few department objectives)");
  const chapters: ChapterSpec[] = [
    { key: "ch-overview", name: "Overview", description: "What the Majlis Plan is and who owns each department", activities: [{ kind: "page", key: "overview", name: "Majlis Plan overview", doc: doc(...overview) }] },
    { key: "ch-depts", name: "Department plans", description: "Every department's key results for your Majlis and region", activities: deptPages },
    { key: "ch-finish", name: "Finish", description: "Knowledge check and sign-off", activities: [
      { kind: "assignment", key: "knowledge-check", name: "Knowledge check: department plans", title: "Knowledge check: department plans", description: "Check that you know which department owns which objective.", ungraded: false, passThreshold: 60,
        tasks: [{ key: "plan-quiz", type: "QUIZ", title: "Department plans", description: "Choose the best answer.", hint: "Review the department pages if unsure.", contents: { grading_mode: "ALL_OR_NOTHING", questions: quiz.questions as QuizQuestion[] } }] },
      { kind: "assignment", key: "signoff", name: "Final sign-off", title: "Final sign-off", description: "Confirm and sign to complete this course.", ungraded: true, tasks: signOffTasks(cycle, "majlis-plan") },
    ] },
  ];
  return { spec: {
    key: `${cycle}|majlis-plan`, kind: "majlis-plan", departmentSlug: "", cycle, name: courseName(cycle, "Majlis Plan"),
    description: `Every department's key results for Qaideen and Naib Qaideen, ${cycle}. Complete by ${a.deadline}.`,
    about: "Required annual training for Qaideen and Naib Qaideen: all departments' Local and Regional key results, a knowledge check and a sign-off.",
    learnings: "Each department's objectives and key results, who owns them, what your Majlis and region must deliver", tags: `mka,compliance,${cycle},majlis-plan`, chapters, flags,
  } };
}
