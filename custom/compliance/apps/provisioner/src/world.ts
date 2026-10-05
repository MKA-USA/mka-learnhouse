import {
  DEFAULT_THINKIFIC_DIR, DEPARTMENTS, THINKIFIC_SOURCE, buildDepartmentCourse, buildGeneralCourse, foundationCourse, getCycleId, listTkCourses, loadFoundation, loadPlans, loadRoster,
  thinkificPlanRefs, type Db, type CourseSpec, type PlanInput, type RosterRow,
} from "@mka/compliance-core";
import { loadCycleDef } from "./cycles";

export const PILOT = ["aitmad", "tabligh"];
export interface WorldSpec { spec: CourseSpec; thinkificCourseId?: number }

const toPlan = (p: any): PlanInput => ({ departmentSlug: p.departmentSlug, level: p.level, responsibilitiesDoc: p.responsibilitiesDoc, okrsDoc: p.okrsDoc, resourcesDoc: p.resourcesDoc, stale: p.stale, source: p.source });

export async function buildWorld(db: Db, o: { cycle: string; only?: string[]; includeGeneral: boolean; thinkificDir?: string; carryOver?: string }): Promise<{ cycleId: number; specs: WorldSpec[]; warnings: string[] }> {
  const cycleId = await getCycleId(db, o.cycle);
  if (cycleId === null) throw new Error(`cycle ${o.cycle} not found; run roster/import first`);
  const def = await loadCycleDef(db, o.cycle); const warnings: string[] = [];
  const deadline = new Date(def.deadlineOn + "T00:00:00Z").toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
  const roster = (await loadRoster(db, cycleId)).map((r) => ({ ...r, level: r.level as RosterRow["level"] })) as RosterRow[];
  if (!roster.length) throw new Error("roster is empty; run `roster` first");
  const own = (await loadPlans(db, cycleId)).map(toPlan);
  const carryId = await getCycleId(db, o.carryOver ?? "2025-26");
  const carried = carryId === null ? [] : (await loadPlans(db, carryId)).map(toPlan);
  const plansFor = (slug: string) => { const x = own.filter((p) => p.departmentSlug === slug); return x.length ? x : carried.filter((p) => p.departmentSlug === slug); };

  const tkDir = o.thinkificDir ?? process.env.THINKIFIC_DIR ?? DEFAULT_THINKIFIC_DIR;
  const tk = listTkCourses(tkDir);
  if (!tk.length) warnings.push(`Thinkific data not found at ${tkDir}; no media/General content`);
  const refs = tk.length ? thinkificPlanRefs(tk) : new Map();
  const specs: WorldSpec[] = [];

  if (o.includeGeneral) {
    const f = foundationCourse(tk);
    if (!f) throw new Error("Foundation course not found in Thinkific export");
    const g = buildGeneralCourse({ cycle: o.cycle, deadline, foundation: loadFoundation(f) });
    specs.push({ spec: g.spec, thinkificCourseId: f.id });
  }
  const depts = DEPARTMENTS.filter((d) => !o.only || o.only.includes(d.slug));
  for (const dept of depts) {
    const plans = plansFor(dept.slug); const ref = refs.get(dept.slug);
    const fromTk = plans.length > 0 && plans.every((p) => p.source === THINKIFIC_SOURCE);
    const otherPlans = DEPARTMENTS.filter((d) => d.slug !== dept.slug).flatMap((d) => plansFor(d.slug));
    specs.push({ thinkificCourseId: fromTk ? ref?.courseId : undefined, spec: buildDepartmentCourse({ cycle: o.cycle, dept, roster, plans, otherPlans, deadline,
      sources: fromTk && ref ? { goals: ref.goals, plan: ref.plan } : undefined }) });
  }
  return { cycleId, specs, warnings };
}
