import { describe, expect, test } from "bun:test";
import {
  ConflictError, DEPARTMENTS, LhApi, LhClient, SafetyError, applyCourse, assertDraftOnly, assertStaging, buildDepartmentCourse, generateRoster, markdownToProseMirror,
  memoryMapStore, planCourse, carryForward, chooseSeed, readPageDoc, LhHttpError, type PMDoc, type CourseSpec, type PlanInput,
} from "../src";

const roster = generateRoster();
const plan = (md: string): PlanInput => ({ departmentSlug: "tabligh", level: "all", responsibilitiesDoc: markdownToProseMirror(md).doc, okrsDoc: markdownToProseMirror("Objective 1: Grow\n\nObjective 2: Pray").doc, resourcesDoc: null, stale: false, source: "csv" });
const spec = (md = "# Duties\n- a"): CourseSpec => buildDepartmentCourse({ cycle: "2026-27", dept: DEPARTMENTS.find((d) => d.slug === "tabligh")!, roster, plans: [plan(md)], otherPlans: [], deadline: "Dec 1, 2026" });

function fakeApi(opts: { existing?: { name: string; course_uuid: string }[]; failOn?: string; published?: boolean; chapters?: unknown; assignmentPublished?: boolean } = {}) {
  const calls: { fn: string; arg: unknown }[] = []; let n = 0;
  const rec = (fn: string, arg: unknown) => { calls.push({ fn, arg }); if (opts.failOn === fn) { opts.failOn = undefined; throw new Error("boom"); } };
  const api = {
    listCourses: async () => opts.existing ?? [],
    createCourse: async (_o: number, i: unknown) => { rec("createCourse", i); return { id: 100, course_uuid: "course_x", published: false }; },
    createChapter: async (i: unknown) => { rec("createChapter", i); n++; return { id: 200 + n, chapter_uuid: `chapter_${n}` }; },
    createActivity: async (i: unknown) => { rec("createActivity", i); n++; return { id: 300 + n, activity_uuid: `activity_${n}` }; },
    updateActivity: async (u: string, i: unknown) => { rec("updateActivity", { u, i }); },
    createAssignment: async (i: unknown) => { rec("createAssignment", i); n++; return { assignment_uuid: `assignment_${n}` }; },
    createAssignmentTask: async (_a: string, i: unknown) => { rec("createAssignmentTask", i); n++; return { assignment_task_uuid: `task_${n}` }; },
    getCourseMeta: async () => ({ published: "published" in opts ? opts.published : false, chapters: opts.chapters }),
    getAssignment: async (u: string) => ({ assignment_uuid: u, published: opts.assignmentPublished ?? true }),
    updateChapter: async (id: number, i: unknown) => { rec("updateChapter", { id, i }); },
    deleteActivity: async (u: string) => { rec("deleteActivity", u); },
    deleteAssignment: async (u: string) => { rec("deleteAssignment", u); },
    updateCourse: async (u: string, i: unknown) => { rec("updateCourse", { u, i }); },
    updateAssignment: async (u: string, i: unknown) => { rec("updateAssignment", { u, i }); },
    updateAssignmentTask: async (a: string, t: string, i: unknown) => { rec("updateAssignmentTask", { a, t, i }); },
  } as unknown as LhApi;
  return { api, calls };
}

describe("provision idempotency", () => {
  test("apply creates; replan is unchanged; second apply issues zero calls", async () => {
    const store = memoryMapStore(); const { api, calls } = fakeApi(); const s = spec();
    expect(planCourse(s, await store.get(s.kind, s.departmentSlug)).action).toBe("create");
    const r = await applyCourse({ api, store, orgId: 1 }, s);
    expect(r.created).toBe(10); expect(r.removed).toBe(0);
    expect(planCourse(s, await store.get(s.kind, s.departmentSlug)).action).toBe("unchanged");
    const before = calls.length;
    const r2 = await applyCourse({ api, store, orgId: 1 }, s);
    expect(r2.created + r2.updated).toBe(0); expect(calls.length).toBe(before);
  });
  test("a content change updates only the changed activity, in place", async () => {
    const store = memoryMapStore(); const { api, calls } = fakeApi(); await applyCourse({ api, store, orgId: 1 }, spec());
    const s2 = spec(); const plan2 = s2.chapters[1]!.activities[0]; if (plan2?.kind !== "page") throw new Error("page");
    plan2.doc = { type: "doc", content: [...plan2.doc.content, { type: "paragraph", content: [{ type: "text", text: "changed" }] }] };
    const p = planCourse(s2, await store.get(s2.kind, s2.departmentSlug));
    expect(p.items.filter((i) => i.action === "update").map((i) => i.key)).toEqual(["plan"]);
    calls.length = 0; await applyCourse({ api, store, orgId: 1 }, s2);
    expect(calls.map((c) => c.fn)).toEqual(["updateActivity"]);
  });
  test("author-owned page: created once, then never updated even when the source changes; plan shows skip", async () => {
    const store = memoryMapStore(); const { api, calls } = fakeApi(); await applyCourse({ api, store, orgId: 1 }, spec());
    expect((await store.get("department", "tabligh"))!.structure.activities.role!.owner).toBe("author");
    const s2 = spec("# Duties\n- a\n- b");
    const p = planCourse(s2, await store.get(s2.kind, s2.departmentSlug));
    expect(p.action).toBe("unchanged");
    expect(p.items.find((i) => i.key === "role")).toMatchObject({ action: "skip", detail: "author-owned (skip)" });
    calls.length = 0; const r = await applyCourse({ api, store, orgId: 1 }, s2);
    expect(r.updated).toBe(0); expect(calls.length).toBe(0);
  });
  test("legacy page record (no owner) is handed over once, then skipped", async () => {
    const store = memoryMapStore(); const { api, calls } = fakeApi(); const s = spec(); await applyCourse({ api, store, orgId: 1 }, s);
    const row = (await store.get("department", "tabligh"))!; delete row.structure.activities.role!.owner; row.structure.activities.role!.hash = "old"; await store.save(row);
    expect(planCourse(s, await store.get("department", "tabligh")).items.find((i) => i.key === "role")?.action).toBe("update");
    calls.length = 0; await applyCourse({ api, store, orgId: 1 }, s);
    expect(calls.map((c) => c.fn)).toEqual(["updateActivity"]);
    expect(planCourse(s, await store.get("department", "tabligh")).items.find((i) => i.key === "role")?.action).toBe("skip");
  });
  test("activities that left the spec are planned as remove and deleted (assignment first), drafts only", async () => {
    const store = memoryMapStore(); const { api, calls } = fakeApi(); const s = spec(); await applyCourse({ api, store, orgId: 1 }, s);
    const row = (await store.get("department", "tabligh"))!;
    row.structure.activities.old = { id: 9, uuid: "activity_old", hash: "h", chapterKey: "ch-role", kind: "assignment", assignmentUuid: "assignment_old" };
    row.structure.activities.oldpage = { id: 10, uuid: "activity_oldpage", hash: "h", chapterKey: "ch-role", kind: "page" };
    await store.save(row);
    const p = planCourse(s, await store.get("department", "tabligh"));
    expect(p.action).toBe("update"); expect(p.items.filter((i) => i.action === "remove").map((i) => i.key)).toEqual(["old", "oldpage"]);
    expect(planCourse(s, await store.get("department", "tabligh"), null, { published: true }).items.find((i) => i.key === "old")?.detail).toContain("BLOCKED");
    calls.length = 0;
    const r = await applyCourse({ api, store, orgId: 1, prune: false }, s); expect(r.removed).toBe(0); expect(calls.length).toBe(0);
    const r2 = await applyCourse({ api, store, orgId: 1 }, s);
    expect(r2.removed).toBe(2); expect(calls.map((c) => `${c.fn}:${c.arg}`)).toEqual(["deleteAssignment:assignment_old", "deleteActivity:activity_old", "deleteActivity:activity_oldpage"]);
    expect(Object.keys((await store.get("department", "tabligh"))!.structure.activities).sort()).toEqual(["directory", "knowledge-check", "plan", "role", "signoff"]);
    expect(planCourse(s, await store.get("department", "tabligh")).action).toBe("unchanged");
  });
  test("a published (or unknown-state) course is never written to: zero write calls, even with a concurrent spec change and a pending removal", async () => {
    const store = memoryMapStore(); const s = spec(); await applyCourse({ api: fakeApi().api, store, orgId: 1 }, s);
    const row = (await store.get("department", "tabligh"))!; row.structure.activities.old = { id: 9, uuid: "activity_old", hash: "h", chapterKey: "ch-role", kind: "page" }; await store.save(row);
    const s2 = spec("# Duties\n- changed"); s2.description = "changed description"; s2.chapters[1]!.name = "Renamed chapter";
    const plan2 = s2.chapters[1]!.activities[0]; if (plan2?.kind !== "page") throw new Error("page"); plan2.doc = { type: "doc", content: [...plan2.doc.content, { type: "paragraph", content: [{ type: "text", text: "changed" }] }] };
    for (const published of [true, undefined as unknown as boolean]) {
      const f = fakeApi({ published });
      await expect(applyCourse({ api: f.api, store, orgId: 1 }, s2)).rejects.toBeInstanceOf(SafetyError);
      expect(f.calls.length).toBe(0);
      await expect(applyCourse({ api: f.api, store, orgId: 1, allowPublished: true }, s2)).rejects.toBeInstanceOf(SafetyError); // removal pending: still refused
      expect(f.calls.length).toBe(0);
    }
    const after = (await store.get("department", "tabligh"))!;
    expect(after.structure.activities.old).toBeDefined(); expect(after.structure.metaHash).toBe(row.structure.metaHash);
  });
  test("allowPublished lets writes through a published course, but only when nothing is being removed", async () => {
    const store = memoryMapStore(); const s = spec(); await applyCourse({ api: fakeApi().api, store, orgId: 1 }, s);
    const s2 = spec(); s2.description = "changed";
    const f = fakeApi({ published: true });
    await expect(applyCourse({ api: f.api, store, orgId: 1 }, s2)).rejects.toBeInstanceOf(SafetyError);
    const r = await applyCourse({ api: f.api, store, orgId: 1, allowPublished: true }, s2);
    expect(r.updated).toBe(1); expect(f.calls.map((c) => c.fn)).toEqual(["updateCourse"]);
  });
  test("one-time seed: ownership is saved BEFORE the PUT, and undone if the PUT fails", async () => {
    const store = memoryMapStore(); const events: string[] = []; const s = spec(); await applyCourse({ api: fakeApi().api, store, orgId: 1 }, s);
    const row = (await store.get("department", "tabligh"))!; delete row.structure.activities.role!.owner; row.structure.activities.role!.hash = "old"; await store.save(row);
    const origSave = store.save.bind(store);
    store.save = async (r) => { events.push(`save:${r.structure.activities.role?.owner ?? "none"}`); return origSave(r); };
    const f = fakeApi(); const upd = f.api.updateActivity;
    f.api.updateActivity = async (u: string, i: unknown) => { events.push("put"); return upd(u, i as never); };
    await applyCourse({ api: f.api, store, orgId: 1 }, s);
    expect(events.slice(0, 2)).toEqual(["save:author", "put"]);
    // failure path: stamp is rolled back so the next run can still seed
    const store2 = memoryMapStore(); await applyCourse({ api: fakeApi().api, store: store2, orgId: 1 }, s);
    const r2 = (await store2.get("department", "tabligh"))!; delete r2.structure.activities.role!.owner; r2.structure.activities.role!.hash = "old"; await store2.save(r2);
    await expect(applyCourse({ api: fakeApi({ failOn: "updateActivity" }).api, store: store2, orgId: 1 }, s)).rejects.toThrow("boom");
    const back = (await store2.get("department", "tabligh"))!.structure.activities.role!;
    expect(back.owner).toBeUndefined(); expect(back.hash).toBe("old");
  });
  test("chapter renames update in place", async () => {
    const store = memoryMapStore(); const { api, calls } = fakeApi(); const s = spec(); await applyCourse({ api, store, orgId: 1 }, s);
    const row = (await store.get("department", "tabligh"))!; delete row.structure.chapters["ch-plan"]!.metaHash; await store.save(row);
    calls.length = 0; await applyCourse({ api, store, orgId: 1 }, s);
    expect(calls.map((c) => c.fn)).toEqual(["updateChapter"]);
  });
  test("same-named course not in course_map is a conflict; nothing is written", async () => {
    const store = memoryMapStore(); const s = spec();
    const { api, calls } = fakeApi({ existing: [{ name: s.name, course_uuid: "course_old" }] });
    expect(planCourse(s, null, "course_old").action).toBe("conflict");
    await expect(applyCourse({ api, store, orgId: 1 }, s)).rejects.toBeInstanceOf(ConflictError);
    expect(calls.length).toBe(0);
  });
  test("resumes after a mid-run failure without duplicating the course", async () => {
    const store = memoryMapStore(); const f = fakeApi({ failOn: "createAssignment" }); const s = spec();
    await expect(applyCourse({ api: f.api, store, orgId: 1 }, s)).rejects.toThrow("boom");
    expect(f.calls.filter((c) => c.fn === "createCourse").length).toBe(1);
    await applyCourse({ api: f.api, store, orgId: 1 }, s);
    expect(f.calls.filter((c) => c.fn === "createCourse").length).toBe(1);
    expect(planCourse(s, await store.get(s.kind, s.departmentSlug)).action).toBe("unchanged");
  });
  test("lessons and assignments are created published; the course is never published by apply", async () => {
    const store = memoryMapStore(); const { api, calls } = fakeApi(); await applyCourse({ api, store, orgId: 1 }, spec());
    const of = (fn: string) => calls.filter((c) => c.fn === fn).map((c) => c.arg as { published?: boolean });
    expect(of("createActivity").length).toBe(5); expect(of("createActivity").every((x) => x.published === true)).toBe(true);
    expect(of("createAssignment").length).toBe(2); expect(of("createAssignment").every((x) => x.published === true)).toBe(true);
    expect(JSON.stringify(of("createCourse"))).not.toContain("published");
    expect(calls.filter((c) => c.fn === "updateCourse").length).toBe(0);
    // a later metadata change still never publishes the course
    const s2 = spec(); s2.description = "changed"; calls.length = 0; await applyCourse({ api, store, orgId: 1 }, s2);
    expect(JSON.stringify(calls.filter((c) => c.fn === "updateCourse"))).not.toContain("published");
  });
  async function appliedWithLiveState(published: boolean) {
    const store = memoryMapStore(); const first = fakeApi(); const s = spec(); await applyCourse({ api: first.api, store, orgId: 1 }, s);
    const row = (await store.get("department", "tabligh"))!;
    const chapters = [{ activities: Object.values(row.structure.activities).map((r) => ({ activity_uuid: r.uuid, published })) }];
    return { store, s, row, chapters };
  }
  test("existing unpublished lessons and assignments get a FLAG-ONLY update, author-owned page included, and its content is never sent", async () => {
    const { store, s, row, chapters } = await appliedWithLiveState(false);
    const plan = planCourse(s, row, null, { published: false, unpublishedKeys: Object.keys(row.structure.activities) });
    expect(plan.action).toBe("update");
    expect(plan.items.find((i) => i.key === "role")).toMatchObject({ action: "update", detail: "publish flag only (content untouched)" }); // author-owned: flag only, not "skip"
    const f = fakeApi({ chapters, assignmentPublished: false });
    const r = await applyCourse({ api: f.api, store, orgId: 1 }, s);
    expect(r.published).toBe(5); expect(r.updated).toBe(0);
    const acts = f.calls.filter((c) => c.fn === "updateActivity").map((c) => (c.arg as { u: string; i: Record<string, unknown> }).i);
    expect(acts.length).toBe(5); for (const i of acts) expect(i).toEqual({ published: true }); // no name, no content
    const asg = f.calls.filter((c) => c.fn === "updateAssignment").map((c) => (c.arg as { i: unknown }).i);
    expect(asg).toEqual([{ published: true }, { published: true }]);
    expect(JSON.stringify(f.calls)).not.toContain('"content"');
    expect(f.calls.filter((c) => c.fn === "updateCourse" || c.fn === "createCourse").length).toBe(0);
    // already published: nothing to do
    const g = fakeApi({ chapters: (await appliedWithLiveState(true)).chapters.map((c) => c) , assignmentPublished: true });
    expect(g.calls.length).toBe(0);
  });
  test("the flag flip still goes through the published-course refusal: zero calls", async () => {
    const { store, s, chapters } = await appliedWithLiveState(false);
    for (const published of [true, undefined as unknown as boolean]) {
      const f = fakeApi({ published, chapters, assignmentPublished: false });
      await expect(applyCourse({ api: f.api, store, orgId: 1 }, s)).rejects.toBeInstanceOf(SafetyError);
      expect(f.calls.length).toBe(0);
    }
  });
  test("a lesson update (content change) is sent published, name and content together", async () => {
    const store = memoryMapStore(); const { api } = fakeApi(); await applyCourse({ api, store, orgId: 1 }, spec());
    const s2 = spec(); const plan2 = s2.chapters[1]!.activities[0]; if (plan2?.kind !== "page") throw new Error("page");
    plan2.doc = { type: "doc", content: [...plan2.doc.content, { type: "paragraph", content: [{ type: "text", text: "changed" }] }] };
    const f = fakeApi(); await applyCourse({ api: f.api, store, orgId: 1 }, s2);
    const put = f.calls.find((c) => c.fn === "updateActivity")!.arg as { i: Record<string, unknown> };
    expect(put.i.published).toBe(true); expect(put.i.content).toBeDefined();
  });
  test("records idmap for sourced lessons and never publishes the course", async () => {
    const store = memoryMapStore(); const { api, calls } = fakeApi(); const s = spec();
    (s.chapters[0]!.activities[0] as { source?: unknown }).source = { system: "thinkific", courseId: 1, chapterId: "c1", lessonId: "l1", path: "x.json" };
    await applyCourse({ api, store, orgId: 1 }, s, 3255556);
    expect(store.idmap.map((e) => `${e.sourceKind}:${e.sourceId}`).sort()).toEqual(["chapter:c1", "course:3255556", "lesson:l1"]);
    expect(JSON.stringify(calls.filter((c) => c.fn === "createCourse" || c.fn === "updateCourse"))).not.toContain("published");
    expect(calls.find((c) => c.fn === "createCourse")).toBeDefined();
  });
});

describe("safety guards", () => {
  test("assertStaging accepts only https ilm-dev.mkausa.org", () => {
    expect(assertStaging("https://ilm-dev.mkausa.org/api/v1").hostname).toBe("ilm-dev.mkausa.org");
    for (const bad of ["https://ilm.mkausa.org/api/v1", "http://ilm-dev.mkausa.org/api/v1", "https://ilm-dev.mkausa.org.evil.com/api/v1", "https://evil.com/ilm-dev.mkausa.org", "", "nonsense", undefined])
      expect(() => assertStaging(bad as string)).toThrow(SafetyError);
  });
  test("course-level guard: a course is never published through the API wrappers; lessons and assignments may be", async () => {
    expect(() => assertDraftOnly({ published: true })).toThrow(SafetyError);
    const client = new LhClient({ baseUrl: "https://ilm-dev.mkausa.org/api/v1", token: "t", orgSlug: "o", fetch: (async () => { throw new Error("network disabled in test"); }) as unknown as typeof fetch, maxRetries: 0 });
    const api = new LhApi(client);
    expect(() => api.updateCourse("course_1", { published: true })).toThrow(SafetyError);
    // not refused by the guard: they reach the (failing) client instead
    const reason = async (f: () => Promise<unknown>) => f().then(() => null, (e: unknown) => e);
    for (const r of [
      await reason(() => api.updateActivity("a", { published: true })),
      await reason(() => api.createActivity({ chapter_id: 1, name: "x", published: true })),
      await reason(() => api.updateAssignment("a", { published: true })),
      await reason(() => api.createAssignment({ title: "t", description: "d", grading_type: "PERCENTAGE", org_id: 1, course_id: 1, chapter_id: 1, activity_id: 1, published: true })),
    ]) { expect(r).not.toBeNull(); expect(r).not.toBeInstanceOf(SafetyError); } // reached the (failing) client: the guard let them through
  });
});

describe("carry-forward of author-owned pages", () => {
  const D = (t: string): PMDoc => ({ type: "doc", content: [{ type: "paragraph", content: [{ type: "text", text: t }] }] });
  test("chooseSeed: previous cycle wins when it has content, else the CSV", () => {
    expect(chooseSeed(D("csv"), D("prev"))).toMatchObject({ source: "previous-cycle" });
    expect(chooseSeed(D("csv"), null)).toMatchObject({ source: "csv" });
    expect(chooseSeed(D("csv"), { type: "doc", content: [{ type: "paragraph" }] })).toMatchObject({ source: "csv" });
  });
  const rowWith = (uuid: string, owner?: "author") => ({ cycleId: 1, kind: "department", departmentSlug: "tabligh", lhCourseUuid: "c", lhCourseId: 1, contentHash: null,
    structure: { courseId: 1, metaHash: "m", chapters: {}, activities: { role: { id: 1, uuid, hash: "h", chapterKey: "ch-role", kind: "page", ...(owner ? { owner } : {}) } } } });
  const pageText = (s: CourseSpec) => { const a = s.chapters[0]!.activities[0]!; return a.kind === "page" ? JSON.stringify(a.doc) : ""; };
  test("owner gating: a previous record without owner=author (v1 generated page) is never carried forward", async () => {
    const s = spec(); const csv = pageText(s);
    const r = await carryForward(s, { row: null, prev: rowWith("prev_role"), readDoc: async () => D("V1 GENERATED PAGE") });
    expect(pageText(r.spec)).toBe(csv); expect(r.sources).toEqual({ role: "csv" });
  });
  test("readDoc failures propagate (the run fails instead of silently seeding from the CSV)", async () => {
    await expect(carryForward(spec(), { row: null, prev: rowWith("prev_role", "author"), readDoc: async () => { throw new Error("HTTP 500"); } })).rejects.toThrow("HTTP 500");
  });
  test("readPageDoc: null only on 404; other errors re-throw", async () => {
    const http = (status: number) => ({ getActivity: async () => { throw new LhHttpError("GET", "/activities/x", status); } });
    expect(await readPageDoc(http(404), "x")).toBeNull();
    await expect(readPageDoc(http(500), "x")).rejects.toBeInstanceOf(LhHttpError);
    await expect(readPageDoc(http(403), "x")).rejects.toBeInstanceOf(LhHttpError);
    expect(await readPageDoc({ getActivity: async () => ({ content: D("hi") }) }, "x")).toEqual(D("hi"));
  });
  test("carryForward swaps in last cycle's page, falls back to CSV, and leaves already-author pages alone", async () => {
    const s = spec(); const csv = pageText(s);
    const read = async (u: string) => (u === "prev_role" ? D("PREVIOUS PAGE") : null);
    const withPrev = await carryForward(s, { row: null, prev: rowWith("prev_role", "author"), readDoc: read });
    expect(pageText(withPrev.spec)).toContain("PREVIOUS PAGE"); expect(withPrev.sources).toEqual({ role: "previous-cycle" });
    const none = await carryForward(s, { row: null, prev: null, readDoc: read });
    expect(pageText(none.spec)).toBe(csv); expect(none.sources).toEqual({ role: "csv" });
    const missing = await carryForward(s, { row: null, prev: rowWith("gone"), readDoc: read });
    expect(missing.sources).toEqual({ role: "csv" });
    const owned = await carryForward(s, { row: rowWith("cur", "author"), prev: rowWith("prev_role"), readDoc: read });
    expect(pageText(owned.spec)).toBe(csv); expect(owned.sources).toEqual({});
    expect(pageText(s)).toBe(csv);
  });
});
