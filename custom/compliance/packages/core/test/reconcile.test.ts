import { describe, expect, test } from "bun:test";
import { LhHttpError, reconcileEnrollments, type LhApi } from "../src";

function fake(existing: Record<string, number>, enrolled: Record<string, number[]>) {
  const calls: string[] = [];
  const api = {
    getUserByEmail: async (e: string) => { calls.push("getUserByEmail"); if (existing[e] === undefined) throw new LhHttpError("GET", "/x", 404, "User not found in this organization"); return { id: existing[e] }; },
    listCourseEnrollments: async (c: string) => { calls.push("listCourseEnrollments"); return (enrolled[c] ?? []).map((id) => ({ user: { id }, enrolled_at: "", status: "" })); },
    bulkEnroll: async (c: string, ids: number[]) => { calls.push(`bulkEnroll:${c}:${ids.join(",")}`); return { enrolled: ids, already_enrolled: [], skipped: [] }; },
    provisionUser: async () => { calls.push("provisionUser"); throw new Error("must never provision"); },
  } as unknown as LhApi;
  return { api, calls };
}
const targets = [
  { email: "a@x.org", courseUuids: ["g", "d"] }, { email: "b@x.org", courseUuids: ["g", "d"] }, { email: "c@x.org", courseUuids: ["g"] },
];

describe("reconcile", () => {
  test("dry run: no writes, reports not-signed-up, never provisions", async () => {
    const { api, calls } = fake({ "a@x.org": 1, "b@x.org": 2 }, { g: [2] });
    const r = await reconcileEnrollments(api, targets, { apply: false });
    expect(r.notSignedUp).toEqual(["c@x.org"]);
    expect(calls.some((c) => c.startsWith("bulkEnroll") || c === "provisionUser")).toBe(false);
    const g = r.perCourse.find((c) => c.courseUuid === "g")!;
    expect(g).toMatchObject({ wanted: 2, alreadyEnrolled: 1, toEnroll: 1, enrolled: 0 });
  });
  test("apply: enrolls only existing, not-yet-enrolled users; skips the rest", async () => {
    const { api, calls } = fake({ "a@x.org": 1, "b@x.org": 2 }, { g: [2] });
    const r = await reconcileEnrollments(api, targets, { apply: true });
    expect(calls.filter((c) => c.startsWith("bulkEnroll"))).toEqual(["bulkEnroll:g:1", "bulkEnroll:d:1,2"]);
    expect(r.enrollmentRows.filter((x) => x.status === "not_signed_up").length).toBe(2);
    expect(calls).not.toContain("provisionUser");
  });
  test("idempotent: second run enrolls nobody", async () => {
    const { api, calls } = fake({ "a@x.org": 1, "b@x.org": 2 }, { g: [1, 2], d: [1, 2] });
    const r = await reconcileEnrollments(api, targets, { apply: true });
    expect(calls.some((c) => c.startsWith("bulkEnroll"))).toBe(false);
    expect(r.perCourse.every((c) => c.toEnroll === 0)).toBe(true);
  });
});
