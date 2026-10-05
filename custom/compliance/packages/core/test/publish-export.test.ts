import { describe, expect, test } from "bun:test";
import { LhApi, LhClient, buildCycleCourses, executePublish, publishPlan, selectLearners, type MapRow } from "../src";

const row: MapRow = { cycleId: 1, kind: "department", departmentSlug: "tabligh", lhCourseUuid: "course_t", lhCourseId: 1, contentHash: null, structure: { courseId: 1, metaHash: "m", chapters: {}, activities: {
  goals: { id: 1, uuid: "activity_1", hash: "h", chapterKey: "c", kind: "page" },
  "contact-selfcheck": { id: 2, uuid: "activity_2", hash: "h", chapterKey: "c", kind: "assignment", assignmentUuid: "assignment_2", tasks: { "select-majlis": { uuid: "task_a", hash: "x" }, "name-contacts": { uuid: "task_b", hash: "x" } } },
  signoff: { id: 3, uuid: "activity_3", hash: "h", chapterKey: "c", kind: "assignment", assignmentUuid: "assignment_3", tasks: { confirm: { uuid: "task_c", hash: "x" }, "full-name": { uuid: "task_d", hash: "x" } } } } } };

describe("publish (explicit command only)", () => {
  const items = publishPlan({ courseUuid: "course_t", name: "T", activities: [{ key: "goals", uuid: "activity_1" }, { key: "signoff", uuid: "activity_3", assignmentUuid: "assignment_3" }] });
  test("plan order: activities, assignments, course last", () => { expect(items.map((i) => `${i.level}:${i.uuid}`)).toEqual(["activity:activity_1", "activity:activity_3", "assignment:assignment_3", "course:course_t"]); });
  test("execute flips each item via PUT published=true; dry run (not calling execute) writes nothing", async () => {
    const puts: string[] = [];
    const client = new LhClient({ baseUrl: "https://ilm-dev.mkausa.org/api/v1", token: "t", orgSlug: "o", delayMs: 0, sleep: async () => {},
      fetch: (async (u: string, i: RequestInit) => { puts.push(`${i.method} ${new URL(u).pathname} ${i.body}`); return new Response("{}", { status: 200 }); }) as unknown as typeof fetch });
    expect(puts.length).toBe(0);
    await executePublish(new LhApi(client), items);
    expect(puts).toEqual([
      'PUT /api/v1/activities/activity_1 {"published":true}', 'PUT /api/v1/activities/activity_3 {"published":true}',
      'PUT /api/v1/assignments/assignment_3 {"published":true}', 'PUT /api/v1/courses/course_t {"published":true}']);
  });
});

describe("cycle-courses.json", () => {
  test("lists courses with signoff and contact-check assignment/task ids", () => {
    const f = buildCycleCourses("2026-27", "2026-12-01", [row], new Date("2026-10-05T00:00:00Z"));
    expect(f.cycle).toBe("2026-27"); expect(f.deadline).toBe("2026-12-01");
    const c = f.courses[0]!;
    expect(c).toMatchObject({ kind: "department", department: "tabligh", course_uuid: "course_t" });
    expect(c.signoff).toEqual({ activity_uuid: "activity_3", assignment_uuid: "assignment_3", task_uuids: { confirm: "task_c", "full-name": "task_d" } });
    expect(c.contact_check?.assignment_uuid).toBe("assignment_2");
    expect(c.activities.length).toBe(3);
  });
});

describe("reconcile scope", () => {
  const roster = [{ departmentSlug: "tabligh" }, { departmentSlug: "" }, { departmentSlug: "maal" }];
  test("--only restricts to departments; --all (undefined) includes roles without a department", () => {
    expect(selectLearners(roster, ["tabligh"]).length).toBe(1);
    expect(selectLearners(roster).length).toBe(3);
  });
});
