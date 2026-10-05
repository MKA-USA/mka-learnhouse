import { describe, expect, test } from "bun:test";
import {
  ConflictError, DEPARTMENTS, LhApi, LhClient, SafetyError, applyCourse, assertDraftOnly, assertStaging, buildDepartmentCourse, generateRoster, markdownToProseMirror,
  memoryMapStore, planCourse, type CourseSpec, type PlanInput,
} from "../src";

const roster = generateRoster();
const plan = (md: string): PlanInput => ({ departmentSlug: "tabligh", level: "all", responsibilitiesDoc: markdownToProseMirror(md).doc, okrsDoc: markdownToProseMirror("Objective 1: Grow\n\nObjective 2: Pray").doc, resourcesDoc: null, stale: false, source: "csv" });
const spec = (md = "# Duties\n- a"): CourseSpec => buildDepartmentCourse({ cycle: "2026-27", dept: DEPARTMENTS.find((d) => d.slug === "tabligh")!, roster, plans: [plan(md)], otherPlans: [], deadline: "Dec 1, 2026" });

function fakeApi(opts: { existing?: { name: string; course_uuid: string }[]; failOn?: string } = {}) {
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
    expect(r.created).toBeGreaterThan(10);
    expect(planCourse(s, await store.get(s.kind, s.departmentSlug)).action).toBe("unchanged");
    const before = calls.length;
    const r2 = await applyCourse({ api, store, orgId: 1 }, s);
    expect(r2.created + r2.updated).toBe(0); expect(calls.length).toBe(before);
  });
  test("a content change updates only the changed activity, in place", async () => {
    const store = memoryMapStore(); const { api, calls } = fakeApi(); await applyCourse({ api, store, orgId: 1 }, spec());
    const s2 = spec("# Duties\n- a\n- b");
    const p = planCourse(s2, await store.get(s2.kind, s2.departmentSlug));
    expect(p.items.filter((i) => i.action === "update").map((i) => i.key)).toEqual(["goals"]);
    calls.length = 0; await applyCourse({ api, store, orgId: 1 }, s2);
    expect(calls.map((c) => c.fn)).toEqual(["updateActivity"]);
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
  test("records idmap for sourced lessons and never sends published=true", async () => {
    const store = memoryMapStore(); const { api, calls } = fakeApi(); const s = spec();
    (s.chapters[0]!.activities[0] as { source?: unknown }).source = { system: "thinkific", courseId: 1, chapterId: "c1", lessonId: "l1", path: "x.json" };
    await applyCourse({ api, store, orgId: 1 }, s, 3255556);
    expect(store.idmap.map((e) => `${e.sourceKind}:${e.sourceId}`).sort()).toEqual(["chapter:c1", "course:3255556", "lesson:l1"]);
    expect(JSON.stringify(calls)).not.toContain('"published":true');
    expect(calls.find((c) => c.fn === "createCourse")).toBeDefined();
  });
});

describe("safety guards", () => {
  test("assertStaging accepts only https ilm-dev.mkausa.org", () => {
    expect(assertStaging("https://ilm-dev.mkausa.org/api/v1").hostname).toBe("ilm-dev.mkausa.org");
    for (const bad of ["https://ilm.mkausa.org/api/v1", "http://ilm-dev.mkausa.org/api/v1", "https://ilm-dev.mkausa.org.evil.com/api/v1", "https://evil.com/ilm-dev.mkausa.org", "", "nonsense", undefined])
      expect(() => assertStaging(bad as string)).toThrow(SafetyError);
  });
  test("refuses to publish: guard and API wrappers", async () => {
    expect(() => assertDraftOnly({ published: true })).toThrow(SafetyError);
    const client = new LhClient({ baseUrl: "https://ilm-dev.mkausa.org/api/v1", token: "t", orgSlug: "o", fetch: (async () => { throw new Error("must not be called"); }) as unknown as typeof fetch });
    const api = new LhApi(client);
    expect(() => api.updateCourse("course_1", { published: true })).toThrow(SafetyError);
    expect(() => api.updateActivity("a", { published: true })).toThrow(SafetyError);
    expect(() => api.createActivity({ chapter_id: 1, name: "x", published: true })).toThrow(SafetyError);
    expect(() => api.createAssignment({ title: "t", description: "d", grading_type: "PERCENTAGE", org_id: 1, course_id: 1, chapter_id: 1, activity_id: 1, published: true })).toThrow(SafetyError);
  });
});
