import type { LhApi } from "../lh/api";
import { LhHttpError } from "../lh/errors";
import type { LhCourse } from "../lh/types";
import type { ActivitySpec, ChapterSpec, CourseSpec, TaskSpec } from "../templates/types";
import { sha, specHash } from "../templates/util";
import type { Action, CoursePlan, CourseStructure, MapRow, MapStore, PlanItem } from "./types";

const actHash = (a: ActivitySpec) => sha(JSON.stringify(a, (k, v) => (k === "abs" ? undefined : v)), 16);
const taskHash = (t: TaskSpec) => sha(JSON.stringify(t), 16);
const metaOf = (s: CourseSpec) => sha(JSON.stringify([s.name, s.description, s.about, s.learnings, s.tags]), 16);
const emptyStructure = (courseId: number, metaHash: string): CourseStructure => ({ courseId, metaHash, chapters: {}, activities: {} });

export class ConflictError extends Error { constructor(m: string) { super(m); this.name = "ConflictError"; } }

function countsOf(spec: CourseSpec) {
  const acts = spec.chapters.flatMap((c) => c.activities);
  return { chapters: spec.chapters.length, pages: acts.filter((a) => a.kind === "page").length, assignments: acts.filter((a) => a.kind === "assignment").length,
    tasks: acts.flatMap((a) => (a.kind === "assignment" ? a.tasks : [])).length, media: acts.filter((a) => a.kind === "video" || a.kind === "pdf").length };
}

/** Pure plan: no network. `existingByName` (uuid) detects a same-named course that is not in course_map. */
export function planCourse(spec: CourseSpec, row: MapRow | null, existingByName?: string | null): CoursePlan {
  const items: PlanItem[] = [];
  const base = { courseKey: spec.key, name: spec.name, counts: countsOf(spec), flags: spec.flags };
  if (!row) {
    if (existingByName) return { ...base, action: "conflict", items, conflict: `a course named "${spec.name}" already exists in LearnHouse (${existingByName}) but is not in course_map; refusing to create a duplicate` };
    items.push({ level: "course", key: spec.key, action: "create" });
    for (const ch of spec.chapters) { items.push({ level: "chapter", key: ch.key, action: "create" }); for (const a of ch.activities) { items.push({ level: "activity", key: a.key, action: "create", detail: a.kind }); } }
    return { ...base, action: "create", items };
  }
  const st = row.structure;
  let changed = false;
  const metaAction: Action = st.metaHash === metaOf(spec) ? "unchanged" : "update";
  if (metaAction === "update") changed = true;
  items.push({ level: "course", key: spec.key, action: metaAction });
  for (const ch of spec.chapters) {
    const exists = !!st.chapters[ch.key];
    if (!exists) changed = true;
    items.push({ level: "chapter", key: ch.key, action: exists ? "unchanged" : "create" });
    for (const a of ch.activities) {
      const rec = st.activities[a.key]; const h = actHash(a);
      const action: Action = !rec ? "create" : rec.hash === h ? "unchanged" : "update";
      if (action !== "unchanged") changed = true;
      const detail = a.kind === "video" || a.kind === "pdf" ? (action === "update" ? "media changed; not re-uploaded" : a.kind) : a.kind;
      items.push({ level: "activity", key: a.key, action, detail });
    }
  }
  return { ...base, action: changed ? "update" : "unchanged", items };
}

export interface ApplyEnv { api: LhApi; store: MapStore; orgId: number; log?: (s: string) => void }

async function saveRow(env: ApplyEnv, spec: CourseSpec, uuid: string, st: CourseStructure) {
  await env.store.save({ kind: spec.kind, departmentSlug: spec.departmentSlug, lhCourseUuid: uuid, lhCourseId: st.courseId, structure: st, contentHash: null });
}

function sourceOfChapter(ch: ChapterSpec): { system: string; chapterId: string } | null {
  const ids = ch.activities.map((a) => a.source?.chapterId).filter((x): x is string => !!x);
  if (!ids.length) return null;
  const top = [...new Set(ids)].sort((a, b) => ids.filter((x) => x === b).length - ids.filter((x) => x === a).length)[0]!;
  return { system: "thinkific", chapterId: top };
}

/** Executes the plan. Every created uuid is persisted immediately (resumable). Never publishes. */
export async function applyCourse(env: ApplyEnv, spec: CourseSpec, thinkificCourseId?: number): Promise<{ courseUuid: string; created: number; updated: number }> {
  const { api, store } = env; const log = env.log ?? (() => {});
  let created = 0, updated = 0;
  let row = await store.get(spec.kind, spec.departmentSlug);
  let uuid: string; let st: CourseStructure;

  if (!row) {
    const clash = (await api.listCourses(1, 100, true)).find((c: LhCourse) => c.name === spec.name);
    if (clash) throw new ConflictError(`course "${spec.name}" already exists in LearnHouse (${clash.course_uuid}) but is not in course_map`);
    const c = await api.createCourse(env.orgId, { name: spec.name, description: spec.description, about: spec.about, learnings: spec.learnings, tags: spec.tags, public: false,
      extra_metadata: { mka: { cycle: spec.cycle, kind: spec.kind, department: spec.departmentSlug, specKey: spec.key } } });
    uuid = c.course_uuid; st = emptyStructure(c.id, metaOf(spec)); created++;
    await saveRow(env, spec, uuid, st);
    if (thinkificCourseId) await store.addIdmap({ sourceSystem: "thinkific", sourceKind: "course", sourceId: String(thinkificCourseId), lhKind: "course", lhUuid: uuid });
    log(`created course ${spec.name}`);
  } else {
    uuid = row.lhCourseUuid; st = row.structure;
    if (st.metaHash !== metaOf(spec)) {
      await api.updateCourse(uuid, { name: spec.name, description: spec.description, about: spec.about, learnings: spec.learnings, tags: spec.tags });
      st.metaHash = metaOf(spec); updated++; await saveRow(env, spec, uuid, st);
    }
  }

  for (const ch of spec.chapters) {
    if (!st.chapters[ch.key]) {
      const c = await api.createChapter({ name: ch.name, description: ch.description, org_id: env.orgId, course_id: st.courseId });
      st.chapters[ch.key] = { id: c.id, uuid: c.chapter_uuid }; created++; await saveRow(env, spec, uuid, st);
      const src = sourceOfChapter(ch);
      if (src) await store.addIdmap({ sourceSystem: src.system, sourceKind: "chapter", sourceId: src.chapterId, lhKind: "chapter", lhUuid: c.chapter_uuid });
    }
    const chRec = st.chapters[ch.key]!;
    for (const a of ch.activities) {
      const h = actHash(a); const rec = st.activities[a.key];
      if (!rec) {
        const r = await createActivity(env, a, chRec.id, st.courseId, ch);
        st.activities[a.key] = { ...r, hash: h, chapterKey: ch.key, kind: a.kind }; created++; await saveRow(env, spec, uuid, st);
        if (a.source?.lessonId) await store.addIdmap({ sourceSystem: "thinkific", sourceKind: "lesson", sourceId: a.source.lessonId, lhKind: "activity", lhUuid: r.uuid, sourcePath: a.source.path });
        log(`  created ${a.kind} ${a.key}`);
      } else if (rec.hash !== h) {
        await updateActivity(env, a, rec);
        rec.hash = h; updated++; await saveRow(env, spec, uuid, st);
        log(`  updated ${a.kind} ${a.key}`);
      }
    }
  }
  return { courseUuid: uuid, created, updated };
}

const taskBody = (t: TaskSpec) => ({ title: t.title, description: t.description, hint: t.hint, assignment_type: t.type, contents: t.contents as Record<string, unknown> });

async function createActivity(env: ApplyEnv, a: ActivitySpec, chapterId: number, courseId: number, ch: ChapterSpec) {
  const { api } = env;
  if (a.kind === "page") {
    const act = await api.createActivity({ chapter_id: chapterId, name: a.name, activity_type: "TYPE_DYNAMIC", activity_sub_type: "SUBTYPE_DYNAMIC_PAGE" });
    await api.updateActivity(act.activity_uuid, { content: a.doc as unknown as Record<string, unknown> });
    return { id: act.id, uuid: act.activity_uuid };
  }
  if (a.kind === "video") { const act = await api.createVideoActivity(chapterId, a.name, a.file.abs); return { id: act.id, uuid: act.activity_uuid }; }
  if (a.kind === "pdf") { const act = await api.createPdfActivity(chapterId, a.name, a.file.abs); return { id: act.id, uuid: act.activity_uuid }; }
  const act = await api.createActivity({ chapter_id: chapterId, name: a.name, activity_type: "TYPE_ASSIGNMENT", activity_sub_type: "SUBTYPE_ASSIGNMENT_ANY" });
  const asg = await api.createAssignment({ title: a.title, description: a.description, grading_type: "PERCENTAGE", org_id: env.orgId, course_id: courseId, chapter_id: chapterId, activity_id: act.id,
    ungraded: a.ungraded, auto_grading: !a.ungraded, pass_threshold_percentage: a.passThreshold ?? null, published: false });
  const tasks: Record<string, { uuid: string; hash: string }> = {};
  for (const t of a.tasks) { const r = await api.createAssignmentTask(asg.assignment_uuid, taskBody(t)); tasks[t.key] = { uuid: r.assignment_task_uuid, hash: taskHash(t) }; }
  void ch;
  return { id: act.id, uuid: act.activity_uuid, assignmentUuid: asg.assignment_uuid, tasks };
}

async function updateActivity(env: ApplyEnv, a: ActivitySpec, rec: import("./types").ActivityRecord) {
  const { api } = env;
  if (a.kind === "page") { await api.updateActivity(rec.uuid, { name: a.name, content: a.doc as unknown as Record<string, unknown> }); return; }
  if (a.kind === "assignment" && rec.assignmentUuid) {
    await api.updateAssignment(rec.assignmentUuid, { title: a.title, description: a.description, ungraded: a.ungraded, pass_threshold_percentage: a.passThreshold ?? null });
    rec.tasks ??= {};
    for (const t of a.tasks) {
      const ex = rec.tasks[t.key];
      if (!ex) { const r = await api.createAssignmentTask(rec.assignmentUuid, taskBody(t)); rec.tasks[t.key] = { uuid: r.assignment_task_uuid, hash: taskHash(t) }; }
      else if (ex.hash !== taskHash(t)) { await api.updateAssignmentTask(rec.assignmentUuid, ex.uuid, taskBody(t)); ex.hash = taskHash(t); }
    }
  }
  // media: not re-uploaded (reported by planCourse)
}

/** Read back one course and compare structure counts with the spec. */
export async function verifyCourse(api: LhApi, uuid: string, spec: CourseSpec): Promise<{ ok: boolean; detail: string }> {
  try {
    const meta = (await api.getCourseMeta(uuid)) as { published?: boolean; chapters?: { activities?: unknown[] }[] };
    const ch = meta.chapters ?? []; const acts = ch.reduce((n, c) => n + (c.activities?.length ?? 0), 0);
    const want = spec.chapters.reduce((n, c) => n + c.activities.length, 0);
    const ok = meta.published === false && ch.length === spec.chapters.length && acts === want;
    return { ok, detail: `published=${meta.published} chapters ${ch.length}/${spec.chapters.length} activities ${acts}/${want}` };
  } catch (e) { return { ok: false, detail: e instanceof LhHttpError ? `HTTP ${e.status}` : "error" }; }
}
export { specHash };
