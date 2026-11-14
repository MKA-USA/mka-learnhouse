import {
  audience, audienceId, calloutInfo, calloutWarning, doc, h, p, table, text, ul, bold, type PMDoc, type PMNode,
} from "../content/pm";
import type { RosterRow } from "../roster/generate";
import { MAJLIS_TO_REGION, REGION_NAMES } from "../roster/generate";
import type { DepartmentSeed } from "../seed/departments";
import { signOffTasks } from "./attestation";
import { buildPlanQuiz, extractObjectives } from "./quiz";
import type { ActivitySpec, ChapterSpec, CourseSpec, PlanInput, QuizQuestion, SourceRef } from "./types";
import { QUIZ_INSTRUCTION, SIGNOFF_INSTRUCTION, courseName, deptLabel } from "./util";

/** Estimated time for a department course: ~4 short pages (about 1,500 words at 200 wpm, about 8 min), 3 quiz questions (about 2 min), contacts lookup and sign-off (about 5 min), plus margin. */
export const DEPT_COURSE_MINUTES = 20;

export const STALE_NOTE = "Last year's content — update pending";
const LEVEL_ORDER = ["all", "national", "region", "majlis"];
/** Audience rule per CSV level: national officeholders see every level; `all` stays unwrapped. */
const LEVEL_AUDIENCE: Record<string, { groups: Record<string, string[]>[]; label: string }> = {
  national: { groups: [{ level: ["national"] }], label: "National team" },
  region: { groups: [{ level: ["regional"] }, { level: ["national"] }], label: "Regional officeholders" },
  majlis: { groups: [{ level: ["local"] }, { level: ["national"] }], label: "Local officeholders" },
};
const LEVEL_TITLE: Record<string, string> = { all: "", national: "National level", region: "Regional level", majlis: "Local (Majlis) level" };

function pendingCallout(deptName: string, cycle: string): PMNode {
  return calloutWarning(`Content pending: the ${cycle} ${deptName} plan has not been provided yet. Your Mohtamim will add it; check back before the deadline.`);
}

/** Render a plan section across levels; stale content gets a visible callout. */
export function renderPlanSection(plans: PlanInput[], pick: (p: PlanInput) => PMDoc | null, deptName: string, cycle: string): PMNode[] {
  const rows = plans.filter((x) => pick(x)).sort((a, b) => LEVEL_ORDER.indexOf(a.level) - LEVEL_ORDER.indexOf(b.level));
  if (!rows.length) return [pendingCallout(deptName, cycle)];
  const out: PMNode[] = [];
  if (rows.some((r) => r.stale)) out.push(calloutWarning(STALE_NOTE));
  for (const r of rows) {
    const title = LEVEL_TITLE[r.level];
    const section: PMNode[] = [...(title ? [h(2, title)] : []), ...pick(r)!.content];
    const aud = LEVEL_AUDIENCE[r.level];
    out.push(...(aud ? [audience(audienceId(cycle, r.departmentSlug, r.level), aud.groups, aud.label, section)] : section));
  }
  return out;
}

/** Small notice at the top of every GENERATED page: edits belong in the source, not here (apply overwrites them). */
export const generatedNote = (source: string, how: string): PMNode =>
  calloutInfo(`This page is generated from the ${source}. To change it, ${how}, not this page.`);

const dash = (s: string | null | undefined) => s || "—";

export function renderDirectory(args: { cycle: string; dept: DepartmentSeed; roster: RosterRow[] }): PMDoc {
  const { dept, roster } = args;
  const mine = roster.filter((r) => r.departmentSlug === dept.slug);
  const nat = mine.filter((r) => r.level === "national");
  const local = mine.filter((r) => r.level === "majlis");
  const qaids = new Map(roster.filter((r) => r.role === "qaid").map((r) => [r.majlis, r]));
  const regionalQaids = roster.filter((r) => r.role === "regional_qaid");
  const regionalDept = mine.filter((r) => r.level === "region");
  const blocks: PMNode[] = [
    p([text("Find your counterparts below. Mailboxes are role mailboxes: they pass to the next officeholder. A dash means the name has not been recorded yet.")]),
    h(2, "National"),
    table(["Role", "Mailbox", "Name"], nat.map((r) => [r.roleTitle, r.learnerEmail, dash(r.personName)])),
    h(2, "Regional"),
    table(["Region", "Role", "Mailbox", "Name"], REGION_NAMES.flatMap((rg) => {
      const rd = regionalDept.find((x) => x.region === rg); const q = regionalQaids.find((x) => x.region === rg);
      return [[rg, rd?.roleTitle ?? `Regional ${dept.name}`, dash(rd?.learnerEmail), dash(rd?.personName)], [rg, "Regional Qaid", dash(q?.learnerEmail), dash(q?.personName)]];
    })),
    h(2, `Local: ${dept.name}`),
    table(["Region", "Majlis", "Role", "Mailbox", "Name", "Majlis Qaid mailbox"],
      local.sort((a, b) => a.region.localeCompare(b.region) || a.majlis.localeCompare(b.majlis) || a.role.localeCompare(b.role))
        .map((r) => [r.region, r.majlis, r.roleTitle, r.learnerEmail, dash(r.personName), dash(qaids.get(r.majlis)?.learnerEmail)])),
  ];
  return doc(...blocks);
}

export interface DepartmentCourseInput {
  cycle: string; dept: DepartmentSeed; roster: RosterRow[];
  plans: PlanInput[];          // plans for THIS department
  otherPlans: PlanInput[];     // other departments (quiz distractors)
  deadline: string;
  /** Thinkific lessons the plan text came from (only when plans are thinkific-sourced). */
  sources?: { goals?: SourceRef; plan?: SourceRef };
}

export function buildDepartmentCourse(a: DepartmentCourseInput): CourseSpec {
  const { cycle, dept } = a;
  const flags: string[] = [];
  const allStale = a.plans.length > 0 && a.plans.every((x) => x.stale);
  if (!a.plans.length) flags.push("no plan for this department");
  else if (allStale) flags.push("plan is stale (carried over)");

  const roleTitle = dept.slug === "aitmad" ? "Motamid" : `Nazim ${dept.name}`;
  const goals = renderPlanSection(a.plans, (x) => x.responsibilitiesDoc, dept.name, cycle);
  const okrs = renderPlanSection(a.plans, (x) => x.okrsDoc, dept.name, cycle);
  const resources = a.plans.map((x) => x.resourcesDoc).filter((d): d is PMDoc => !!d);

  // ONE author-owned page: role at a glance, responsibilities, resources. Apply seeds it once; Mohtamims edit it from then on.
  const rolePage: PMNode[] = [
    h(2, "Your role at a glance"),
    ul([[bold("Role: "), text(roleTitle)], `Department: ${deptLabel(dept.name, dept.translation)}`, `Local mailbox format: ${dept.mailboxPrefix}.<majlis>@${dept.slug === "atfal" ? "atfalusa.org (nazim / murabbi)" : "mkausa.org"}`]),
    ...goals,
    ...(resources.length ? [h(2, "Resources"), ...resources.flatMap((d) => d.content)] : []),
  ];

  const ownObjectives = a.plans.flatMap((x) => extractObjectives(x.okrsDoc));
  const otherObjectives = a.otherPlans.flatMap((x) => extractObjectives(x.okrsDoc));
  const quiz = buildPlanQuiz({ cycle, deptSlug: dept.slug, deptName: dept.name, ownObjectives, otherObjectives });
  if (quiz.basis === "plan" && allStale) flags.push("knowledge check is built from last year's (stale) objectives");
  if (quiz.basis === "fallback") flags.push("knowledge check is the generic fallback (no usable plan objectives)");

  const chapters: ChapterSpec[] = [
    { key: "ch-role", name: "Your role", description: "Your responsibilities and resources", activities: [
      { kind: "page", key: "role", name: "Your role and resources", doc: doc(...rolePage), owner: "author", ...(a.sources?.goals ? { source: a.sources.goals } : {}) },
    ] },
    { key: "ch-plan", name: `Your ${cycle} plan`, description: "This cycle's plan and objectives", activities: [
      { kind: "page", key: "plan", name: "Annual department plan and OKRs", doc: doc(generatedNote(`${cycle} Department Plan`, "update the plan with Aitmad"), ...okrs), ...(a.sources?.plan ? { source: a.sources.plan } : {}) },
      { kind: "assignment", key: "knowledge-check", name: "Knowledge check: department plan", title: "Knowledge check: department plan", description: `Check your understanding of the ${dept.name} plan. ${QUIZ_INSTRUCTION}`, ungraded: false, passThreshold: 60,
        tasks: [{ key: "plan-quiz", type: "QUIZ", title: "Department plan", description: "Choose the best answer.", hint: "Review the plan lesson if unsure.", contents: { grading_mode: "ALL_OR_NOTHING", questions: quiz.questions as QuizQuestion[] } }] },
    ] },
    { key: "ch-contacts", name: "Contacts", description: "Your national, regional and local counterparts", activities: [
      { kind: "page", key: "directory", name: "Contacts directory", doc: doc(generatedNote(`${cycle} officeholder roster`, "contact Aitmad"), ...renderDirectory({ cycle, dept, roster: a.roster }).content) },
    ] },
    { key: "ch-attest", name: "Finish", description: "Final sign-off", activities: [
      { kind: "assignment", key: "signoff", name: "Final sign-off", title: "Final sign-off", description: `Confirm and sign to complete this course. ${SIGNOFF_INSTRUCTION}`, ungraded: true, tasks: signOffTasks(cycle, dept.slug) },
    ] },
  ];

  return {
    key: `${cycle}|dept:${dept.slug}`, kind: "department", departmentSlug: dept.slug, cycle,
    name: courseName(cycle, dept.name),
    description: `Your role, this year's ${dept.name} plan and the people to contact, then a short knowledge check and sign-off. About ${DEPT_COURSE_MINUTES} minutes. Complete by ${a.deadline}.`,
    about: `Required annual training for ${roleTitle} and counterparts: goals, the annual plan, your contacts and a final sign-off.`,
    learnings: "Your responsibilities, this year's plan, who to contact, attestation",
    tags: `mka,compliance,${cycle},${dept.slug}`, chapters, flags,
  };
}
export type { ActivitySpec };
