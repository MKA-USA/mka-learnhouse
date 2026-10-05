import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { parse as parseYaml } from "yaml";
import { htmlToProseMirror } from "../content/html";
import { type ContentFlag, scanContent } from "../content/flags";
import { plainText, type PMDoc } from "../content/pm";
import type { DeptPlanInput } from "../importers/dept-plans";
import { resolveDepartment } from "../importers/resolve";

export const THINKIFIC_SOURCE = "thinkific-2025-26";
export const DEFAULT_THINKIFIC_DIR = "/Users/mamjed/Documents/mka-thinkific-migration/data";

export interface TkLesson { id: string; name: string; type: string; position: number; raw: string; file: string | null; video_file: string | null; chapterId: string; chapterName: string }
export interface TkChapter { id: string; name: string; lessons: TkLesson[] }
export interface TkCourse { dir: string; id: number; name: string; status: string; chapters: TkChapter[] }

export function loadTkCourse(dataDir: string, folder: string): TkCourse | null {
  const mf = join(dataDir, folder, "manifest.yaml");
  if (!existsSync(mf)) return null;
  const m = parseYaml(readFileSync(mf, "utf8")) as { course: { id: number; name: string; status: string }; chapters: { id: string | number; name: string; lessons: Record<string, unknown>[] }[] };
  return {
    dir: join(dataDir, folder), id: m.course.id, name: m.course.name, status: m.course.status,
    chapters: (m.chapters ?? []).map((c) => ({
      id: String(c.id), name: c.name,
      lessons: (c.lessons ?? []).map((l) => ({ id: String(l.id), name: String(l.name), type: String(l.type), position: Number(l.position), raw: String(l.raw), file: (l.file as string) ?? null, video_file: (l.video_file as string) ?? null, chapterId: String(c.id), chapterName: c.name })),
    })),
  };
}
export const allLessons = (c: TkCourse) => c.chapters.flatMap((ch) => ch.lessons);
export function lessonHtml(c: TkCourse, l: TkLesson): string {
  const j = JSON.parse(readFileSync(join(c.dir, l.raw), "utf8")) as { detail?: { htmlDescription?: string | null } };
  return j.detail?.htmlDescription ?? "";
}
export function listTkCourses(dataDir: string): TkCourse[] {
  if (!existsSync(dataDir)) return [];
  return readdirSync(dataDir).filter((f) => /^\d+_/.test(f)).map((f) => loadTkCourse(dataDir, f)).filter((c): c is TkCourse => !!c);
}

/** Department Training Courses by REAL title (folder slugs mislead: 3255556_course-2 is Aitmad). Template/draft excluded. */
export function departmentCourses(courses: TkCourse[]): { course: TkCourse; departmentSlug: string }[] {
  const out: { course: TkCourse; departmentSlug: string }[] = [];
  for (const c of courses) {
    if (!/training course$/i.test(c.name) || /template/i.test(c.name) || c.status !== "published") continue;
    const d = resolveDepartment(c.name);
    if (d) out.push({ course: c, departmentSlug: d });
  }
  return out;
}
export function foundationCourse(courses: TkCourse[]): TkCourse | null {
  return courses.find((c) => /^foundation course/i.test(c.name)) ?? null;
}

export interface ThinkificPlanSeed { plans: DeptPlanInput[]; flags: { department: string; lesson: string; flag: ContentFlag }[]; missing: string[] }

/** Slot 1 (Responsibilities...) and slot 3 (Annual Department Plan) per department course. Marked stale. */
export function seedPlansFromThinkific(courses: TkCourse[]): ThinkificPlanSeed {
  const plans: DeptPlanInput[] = []; const flags: ThinkificPlanSeed["flags"] = []; const missing: string[] = [];
  for (const { course, departmentSlug } of departmentCourses(courses)) {
    const lessons = allLessons(course).filter((l) => l.type === "Text");
    const resp = lessons.find((l) => /^responsibilities/i.test(l.name)) ?? lessons[0];
    const okr = lessons.find((l) => /annual department plan/i.test(l.name)) ?? lessons[1];
    if (!resp || !okr) { missing.push(`${departmentSlug}: expected Responsibilities + Annual Department Plan text lessons`); }
    const conv = (l?: TkLesson): PMDoc | null => {
      if (!l) return null;
      const r = htmlToProseMirror(lessonHtml(course, l));
      for (const f of scanContent({ text: plainText(r.doc), links: r.links, imagesDropped: r.imagesDropped })) flags.push({ department: departmentSlug, lesson: l.name, flag: f });
      return r.doc;
    };
    const rd = conv(resp), od = conv(okr);
    plans.push({ departmentSlug, level: "all", responsibilitiesMd: "", okrsMd: "", resourcesMd: "", responsibilitiesDoc: rd, okrsDoc: od, resourcesDoc: null, updatedBy: "thinkific-export", stale: true, source: THINKIFIC_SOURCE });
  }
  return { plans, flags, missing };
}

export interface ThinkificPlanRef { courseId: number; goals?: SourceRefLite; plan?: SourceRefLite }
type SourceRefLite = { system: "thinkific"; courseId: number; chapterId: string; lessonId: string; path: string };
/** Which Thinkific lessons fed each department's plan docs (for idmap traceability). */
export function thinkificPlanRefs(courses: TkCourse[]): Map<string, ThinkificPlanRef> {
  const out = new Map<string, ThinkificPlanRef>();
  for (const { course, departmentSlug } of departmentCourses(courses)) {
    const lessons = allLessons(course).filter((l) => l.type === "Text");
    const resp = lessons.find((l) => /^responsibilities/i.test(l.name)) ?? lessons[0];
    const okr = lessons.find((l) => /annual department plan/i.test(l.name)) ?? lessons[1];
    const ref = (l?: TkLesson): SourceRefLite | undefined => (l ? { system: "thinkific", courseId: course.id, chapterId: l.chapterId, lessonId: l.id, path: l.raw } : undefined);
    out.set(departmentSlug, { courseId: course.id, goals: ref(resp), plan: ref(okr) });
  }
  return out;
}
