import type { LhApi } from "../lh/api";
import { LhHttpError } from "../lh/errors";
import { SafetyError } from "../safety";
import type { LhCourse } from "../lh/types";
import type { ActivitySpec, ChapterSpec, CourseSpec, TaskSpec } from "../templates/types";
import { sha, specHash } from "../templates/util";
import type { Action, CoursePlan, CourseStructure, MapRow, MapStore, PlanItem } from "./types";

const actHash = (a: ActivitySpec) => sha(JSON.stringify(a, (k, v) => (k === "abs" ? undefined : v)), 16);
const taskHash = (t: TaskSpec) => sha(JSON.stringify(t), 16);
const chapterHash = (c: ChapterSpec) => sha(JSON.stringify([c.name, c.description]), 12);
const metaOf = (s: CourseSpec) => sha(JSON.stringify([s.name, s.description, s.about, s.learnings, s.tags]), 16);
const emptyStructure = (courseId: number, metaHash: string): CourseStructure => ({ courseId, metaHash, chapters: {}, activities: {} });

export class ConflictError extends Error { constructor(m: string) { super(m); this.name = "ConflictError"; } }

function countsOf(spec: CourseSpec) {
  const acts = spec.chapters.flatMap((c) => c.activities);
  return { chapters: spec.chapters.length, pages: acts.filter((a) => a.kind === "page").length, assignments: acts.filter((a) => a.kind === "assignment").length,
    tasks: acts.flatMap((a) => (a.kind === "assignment" ? a.tasks : [])).length, media: acts.filter((a) => a.kind === "video" || a.kind === "pdf").length };
}

/** Pure plan: no network. `existingByName` (uuid) detects a same-named course that is not in course_map. */
export function planCourse(spec: CourseSpec, row: MapRow | null, existingByName?: string | null, opts: { published?: boolean | null; /** keys of recorded activities that are live but unpublished (apply flips the flag only) */ unpublishedKeys?: readonly string[] } = {}): CoursePlan {
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
    const chRec = st.chapters[ch.key];
    if (!chRec) changed = true;
    const chAction: Action = !chRec ? "create" : chRec.metaHash === chapterHash(ch) ? "unchanged" : "update";
    if (chAction === "update") changed = true;
    items.push({ level: "chapter", key: ch.key, action: chAction });
    for (const a of ch.activities) {
      const rec = st.activities[a.key]; const h = actHash(a);
      let action: Action; let detail: string = a.kind;
      if (!rec) action = "create";
      else if ((a.owner ?? "generated") === "author") {
        if (rec.owner === "author") { action = "skip"; detail = "author-owned (skip)"; }
        else { action = "update"; detail = "one-time: content seeded from the spec, then author-owned"; }
      } else action = rec.hash === h ? "unchanged" : "update";
      if (action === "update" && (a.kind === "video" || a.kind === "pdf")) detail = "media changed; not re-uploaded";
      if (rec && opts.unpublishedKeys?.includes(a.key) && (action === "skip" || action === "unchanged")) { action = "update"; detail = "publish flag only (content untouched)"; }
      if (rec && rec.chapterKey !== ch.key) { detail = `move to chapter ${ch.key} (activity id and content kept)${action === "skip" || action === "unchanged" ? "" : `; ${detail}`}`; action = "update"; }
      if (action === "update" || action === "create") changed = true;
      items.push({ level: "activity", key: a.key, action, detail });
    }
  }
  // Activities recorded in course_map that the spec no longer has (drafts only; apply refuses on a published course).
  const specKeys = new Set(spec.chapters.flatMap((c) => c.activities.map((a) => a.key)));
  for (const [key, rec] of Object.entries(st.activities)) {
    if (specKeys.has(key)) continue;
    changed = true;
    items.push({ level: "activity", key, action: "remove", detail: opts.published === true ? `${rec.kind}; BLOCKED: course is published` : rec.kind });
  }
  return { ...base, action: changed ? "update" : "unchanged", items };
}

export interface ApplyEnv { api: LhApi; store: MapStore; orgId: number; log?: (s: string) => void; /** Remove activities that left the spec (default true; drafts only). */ prune?: boolean; /** Allow writes (not removals) to a course that is published or whose state is unknown. Default false: apply refuses. */ allowPublished?: boolean }

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
export async function applyCourse(env: ApplyEnv, spec: CourseSpec, thinkificCourseId?: number): Promise<{ courseUuid: string; created: number; updated: number; removed: number; published: number }> {
  const { api, store } = env; const log = env.log ?? (() => {});
  let created = 0, updated = 0, removed = 0;
  let row = await store.get(spec.kind, spec.departmentSlug);
  let uuid: string; let st: CourseStructure;
  const liveActs = new Map<string, boolean | undefined>(); // existing course: the live published flag per activity (from the same meta read as the draft guard)
  let flipped = 0; let mustReorder = false;

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
    // Draft guard BEFORE any write: a published (or unknown-state) course is never modified, and activities are never removed from one.
    const specKeys0 = new Set(spec.chapters.flatMap((c) => c.activities.map((a) => a.key)));
    const gone0 = env.prune === false ? [] : Object.keys(st.activities).filter((k) => !specKeys0.has(k));
    const meta = (await api.getCourseMeta(uuid)) as { published?: boolean; chapters?: { activities?: { activity_uuid?: string; published?: boolean }[] }[] };
    for (const c of meta.chapters ?? []) for (const x of c.activities ?? []) if (x.activity_uuid) liveActs.set(x.activity_uuid, x.published);
    if (meta.published !== false) {
      if (gone0.length) throw new SafetyError(`refusing to remove activities from ${spec.name}: the course is published (or its state is unknown)`);
      if (!env.allowPublished) throw new SafetyError(`refusing to write to ${spec.name}: the course is published (or its state is unknown)`);
    }
    if (st.metaHash !== metaOf(spec)) {
      await api.updateCourse(uuid, { name: spec.name, description: spec.description, about: spec.about, learnings: spec.learnings, tags: spec.tags });
      st.metaHash = metaOf(spec); updated++; await saveRow(env, spec, uuid, st);
    }
  }

  for (const ch of spec.chapters) {
    if (!st.chapters[ch.key]) {
      const c = await api.createChapter({ name: ch.name, description: ch.description, org_id: env.orgId, course_id: st.courseId });
      st.chapters[ch.key] = { id: c.id, uuid: c.chapter_uuid, metaHash: chapterHash(ch) }; created++; await saveRow(env, spec, uuid, st);
      if (row) mustReorder = true; // a chapter added to an existing course lands at the end: restore the spec's order
      const src = sourceOfChapter(ch);
      if (src) await store.addIdmap({ sourceSystem: src.system, sourceKind: "chapter", sourceId: src.chapterId, lhKind: "chapter", lhUuid: c.chapter_uuid });
    }
    const chRec = st.chapters[ch.key]!;
    if (chRec.metaHash !== chapterHash(ch)) {
      await api.updateChapter(chRec.id, { name: ch.name, description: ch.description });
      chRec.metaHash = chapterHash(ch); updated++; await saveRow(env, spec, uuid, st);
      log(`  updated chapter ${ch.key}`);
    }
    for (const a of ch.activities) {
      const h = actHash(a); const rec = st.activities[a.key]; const owner = a.owner ?? "generated";
      if (rec && rec.chapterKey !== ch.key) mustReorder = true; // moved to another chapter in the spec: same activity, new chapter
      if (!rec) {
        const r = await createActivity(env, a, chRec.id, st.courseId, ch);
        st.activities[a.key] = { ...r, hash: h, chapterKey: ch.key, kind: a.kind, owner }; created++; await saveRow(env, spec, uuid, st);
        if (a.source?.lessonId) await store.addIdmap({ sourceSystem: "thinkific", sourceKind: "lesson", sourceId: a.source.lessonId, lhKind: "activity", lhUuid: r.uuid, sourcePath: a.source.path });
        log(`  created ${a.kind} ${a.key}`);
      } else if (owner === "author" && rec.owner === "author") {
        log(`  skipped ${a.kind} ${a.key} (author-owned)`);
      } else if (owner === "author" || rec.hash !== h) {
        // author-owned but not yet handed over (legacy record): seed once from the spec, then never touch it again.
        // Stamp ownership BEFORE the PUT so a failed save afterwards can never re-seed and wipe the author's edits; undo the stamp if the PUT itself fails.
        const before = { hash: rec.hash, owner: rec.owner };
        if (owner === "author") { rec.hash = h; rec.owner = owner; await saveRow(env, spec, uuid, st); }
        try { await updateActivity(env, a, rec); }
        catch (e) { if (owner === "author") { rec.hash = before.hash; if (before.owner) rec.owner = before.owner; else delete rec.owner; await saveRow(env, spec, uuid, st); } throw e; }
        rec.hash = h; rec.owner = owner; updated++; liveActs.set(rec.uuid, true); await saveRow(env, spec, uuid, st);
        log(`  updated ${a.kind} ${a.key}${owner === "author" ? " (one-time seed; author-owned from now on)" : ""}`);
      }
    }
  }
  if (mustReorder) {
    // One order call places every chapter and activity as the spec says. Activity ids (and so content, submissions and progress) are kept; activities that
    // are about to be pruned stay in their old chapter until the removal below so nothing is unlinked by accident.
    const specKeys1 = new Set(spec.chapters.flatMap((c) => c.activities.map((a) => a.key)));
    const byChapter = new Map<string, number[]>();
    for (const ch of spec.chapters) byChapter.set(ch.key, ch.activities.map((a) => st.activities[a.key]!.id));
    for (const [key, rec] of Object.entries(st.activities)) if (!specKeys1.has(key)) byChapter.set(rec.chapterKey, [...(byChapter.get(rec.chapterKey) ?? []), rec.id]);
    for (const k of Object.keys(st.chapters)) if (!byChapter.has(k)) byChapter.set(k, []); // retired chapters keep their place at the end
    const specChapterKeys = spec.chapters.map((c) => c.key);
    const orderKeys = [...specChapterKeys, ...[...byChapter.keys()].filter((k) => !specChapterKeys.includes(k))];
    await api.reorderCourse(uuid, { chapter_order_by_ids: orderKeys.filter((k) => st.chapters[k]).map((k) => ({ chapter_id: st.chapters[k]!.id, activities_order_by_ids: (byChapter.get(k) ?? []).map((id) => ({ activity_id: id })) })) });
    for (const ch of spec.chapters) for (const a of ch.activities) st.activities[a.key]!.chapterKey = ch.key;
    await saveRow(env, spec, uuid, st); updated++;
    log("  reordered chapters and activities (activity ids kept)");
  }
  // Lessons and assignments live PUBLISHED inside the unpublished course (LearnHouse hides unpublished activities from everyone who cannot edit the
  // course). Existing ones that are still unpublished get a FLAG-ONLY update ({published:true}): never name, never content, so author-owned pages are safe.
  for (const [key, rec] of Object.entries(st.activities)) {
    if (!spec.chapters.some((c) => c.activities.some((a) => a.key === key)) || liveActs.get(rec.uuid) !== false) continue;
    await api.updateActivity(rec.uuid, { published: true }); liveActs.set(rec.uuid, true); flipped++;
    if (rec.assignmentUuid) { const asg = await api.getAssignment(rec.assignmentUuid); if (asg.published === false) await api.updateAssignment(rec.assignmentUuid, { published: true }); }
    log(`  published ${rec.kind} ${key} (flag only)`);
  }
  if (env.prune !== false) {
    const specKeys = new Set(spec.chapters.flatMap((c) => c.activities.map((a) => a.key)));
    const gone = Object.entries(st.activities).filter(([k]) => !specKeys.has(k));
    if (gone.length) {
      for (const [key, rec] of gone) {
        if (rec.assignmentUuid) await ignore404(() => api.deleteAssignment(rec.assignmentUuid!));
        await ignore404(() => api.deleteActivity(rec.uuid));
        delete st.activities[key]; removed++; await saveRow(env, spec, uuid, st);
        log(`  removed ${rec.kind} ${key}`);
      }
    }
  }
  return { courseUuid: uuid, created, updated, removed, published: flipped };
}

async function ignore404(f: () => Promise<unknown>) { try { await f(); } catch (e) { if (!(e instanceof LhHttpError && e.status === 404)) throw e; } }

const taskBody = (t: TaskSpec) => ({ title: t.title, description: t.description, hint: t.hint, assignment_type: t.type, contents: t.contents as Record<string, unknown> });

async function createActivity(env: ApplyEnv, a: ActivitySpec, chapterId: number, courseId: number, ch: ChapterSpec) {
  const { api } = env;
  if (a.kind === "page") {
    const act = await api.createActivity({ chapter_id: chapterId, name: a.name, activity_type: "TYPE_DYNAMIC", activity_sub_type: "SUBTYPE_DYNAMIC_PAGE", published: true });
    await api.updateActivity(act.activity_uuid, { content: a.doc as unknown as Record<string, unknown>, published: true });
    return { id: act.id, uuid: act.activity_uuid };
  }
  if (a.kind === "video") { const act = await api.createVideoActivity(chapterId, a.name, a.file.abs); await api.updateActivity(act.activity_uuid, { published: true }); return { id: act.id, uuid: act.activity_uuid }; }
  if (a.kind === "pdf") { const act = await api.createPdfActivity(chapterId, a.name, a.file.abs); await api.updateActivity(act.activity_uuid, { published: true }); return { id: act.id, uuid: act.activity_uuid }; }
  const act = await api.createActivity({ chapter_id: chapterId, name: a.name, activity_type: "TYPE_ASSIGNMENT", activity_sub_type: "SUBTYPE_ASSIGNMENT_ANY", published: true });
  const asg = await api.createAssignment({ title: a.title, description: a.description, grading_type: "PERCENTAGE", org_id: env.orgId, course_id: courseId, chapter_id: chapterId, activity_id: act.id,
    ungraded: a.ungraded, auto_grading: !a.ungraded, pass_threshold_percentage: a.passThreshold ?? null, published: true });
  const tasks: Record<string, { uuid: string; hash: string }> = {};
  for (const t of a.tasks) { const r = await api.createAssignmentTask(asg.assignment_uuid, taskBody(t)); tasks[t.key] = { uuid: r.assignment_task_uuid, hash: taskHash(t) }; }
  void ch;
  return { id: act.id, uuid: act.activity_uuid, assignmentUuid: asg.assignment_uuid, tasks };
}

async function updateActivity(env: ApplyEnv, a: ActivitySpec, rec: import("./types").ActivityRecord) {
  const { api } = env;
  if (a.kind === "page") { await api.updateActivity(rec.uuid, { name: a.name, content: a.doc as unknown as Record<string, unknown>, published: true }); return; }
  if (a.kind === "assignment" && rec.assignmentUuid) {
    await api.updateAssignment(rec.assignmentUuid, { title: a.title, description: a.description, ungraded: a.ungraded, pass_threshold_percentage: a.passThreshold ?? null, published: true });
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
