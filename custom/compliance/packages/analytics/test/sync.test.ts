import { describe, expect, test } from "bun:test";
import { buildFixtureDataset } from "../src/dataset";
import { expectedContacts, generateRoster, generateWorld, snapshotAt, FIXTURE_CYCLE } from "../src/fixtures";
import { aggregateBy } from "../src/aggregate";
import { attention } from "../src/attention";
import { memoryStore, rosterKeyOf, runSnapshotSync, type SyncLhPort } from "../src/sync";
import { classifyAssignment, createFixturePort, fixtureCourses } from "../src/sync-adapters";

const cycle = { id: 1, ...FIXTURE_CYCLE };

describe("fixture world", () => {
  test("~1,200 learners, 22 courses, deterministic", () => {
    const r = generateRoster();
    expect(r.length).toBe(1176);
    expect(fixtureCourses().length).toBe(22);
    expect(new Set(r.map((e) => e.email)).size).toBe(r.length);
    expect(r.every((e) => e.email.endsWith("@example.invalid"))).toBe(true);
    const a = snapshotAt(generateWorld({ seed: 1 }), "2026-11-18"), b = snapshotAt(generateWorld({ seed: 1 }), "2026-11-18");
    expect(a).toEqual(b);
  });
  test("deliberate problem departments surface as red on the demo date", () => {
    const ds = buildFixtureDataset({ historyDays: 0 });
    const by = new Map(aggregateBy(ds.rows, "department", ds.cycle).map((a) => [a.key, attention(a, ds.cycle, ds.asOf)]));
    for (const d of ["tarbiyyat", "waqf-e-nau"]) expect(["amber", "red"]).toContain(by.get(d)!.rag);
    expect(by.get("tarbiyyat")!.reasons.join()).toContain("haven't started");
    expect(by.get("ishaat")!.reasons.join()).toContain("mismatch");
    expect(by.get("tajneed")!.rag).toBe("green");
  });
  test("history is monotone: attested never decreases over time", () => {
    const ds = buildFixtureDataset({ historyDays: 10 });
    const counts = Object.keys(ds.history).sort().map((d) => ds.history[d]!.filter((r) => r.stage === "attested").length);
    expect(counts.every((c, i) => i === 0 || c >= counts[i - 1]!)).toBe(true);
    expect(counts.at(-1)!).toBeGreaterThan(counts[0]!);
  });
});

describe("snapshot sync", () => {
  test("fixture-simulated LearnHouse reproduces the direct snapshot exactly", async () => {
    const world = generateWorld(), day = "2026-11-20";
    const { store, snapshots, runs } = memoryStore();
    const res = await runSnapshotSync({ cycle, roster: world.roster, courses: fixtureCourses(), port: createFixturePort(world, day), store, today: day, expectedContacts, source: "fixtures" });
    expect(res.errors).toBe(0); expect(res.learners).toBe(1176); expect(runs[0]!.status).toBe("ok");
    const direct = new Map(snapshotAt(world, day).map((r) => [r.email, r]));
    const synced = snapshots.get(`1:${day}`)!;
    for (const s of synced) {
      const d = direct.get(s.email)!;
      expect({ ...s, rosterId: "" }).toEqual({ ...d, rosterId: "" });
    }
    expect(synced[0]!.rosterId).toBe(rosterKeyOf(world.roster[0]!));
  });

  test("re-running the same day is idempotent (upsert)", async () => {
    const world = generateWorld(), day = "2026-11-12", { store, snapshots } = memoryStore();
    for (let i = 0; i < 2; i++) await runSnapshotSync({ cycle, roster: world.roster, courses: fixtureCourses(), port: createFixturePort(world, day), store, today: day, limit: 100 });
    expect(snapshots.get(`1:${day}`)!.length).toBe(100);
  });

  const tiny = generateWorld();
  const mocked = (over: Partial<SyncLhPort>): SyncLhPort => ({ ...createFixturePort(tiny, "2026-11-20"), ...over });
  test("a failing trail fetch yields a partial run and keeps other learners", async () => {
    const { store, runs } = memoryStore();
    let n = 0;
    const base = createFixturePort(tiny, "2026-11-20");
    const res = await runSnapshotSync({ cycle, roster: tiny.roster, courses: fixtureCourses(), today: "2026-11-20", store, limit: 20,
      port: mocked({ getUserTrail: async (u) => { if (++n === 3) throw new Error("boom"); return base.getUserTrail(u); } }) });
    expect(res.errors).toBe(1); expect(res.learners).toBe(19); expect(runs[0]!.status).toBe("partial");
  });
  test("a failing course load is counted, run still completes", async () => {
    const { store, runs } = memoryStore();
    const res = await runSnapshotSync({ cycle, roster: tiny.roster, courses: fixtureCourses(), today: "2026-11-20", store, limit: 5,
      port: mocked({ listEnrollments: async () => { throw new Error("500"); } }) });
    expect(res.errors).toBeGreaterThan(0); expect(runs[0]!.status).toBe("partial");
    expect(res.rows.every((r) => r.stage === "not_started")).toBe(true);
  });
  test("a store failure marks the run failed and rethrows", async () => {
    const { store, runs } = memoryStore();
    store.upsertSnapshots = async () => { throw new Error("db down"); };
    await expect(runSnapshotSync({ cycle, roster: tiny.roster, courses: fixtureCourses(), today: "2026-11-20", store, limit: 3, port: createFixturePort(tiny, "2026-11-20") })).rejects.toThrow("db down");
    expect(runs[0]!.status).toBe("failed");
  });
  test("sign-off: LATE and GRADED count, PENDING does not", async () => {
    const e = tiny.roster.find((r) => r.departmentSlug === "tabligh" && r.level === "majlis")!;
    const mk = (status: string): SyncLhPort => ({
      listEnrollments: async () => [{ userId: 7, email: e.email, enrolledAt: "2026-11-01", status: "STATUS_COMPLETED" }],
      getUserTrail: async () => [{ courseUuid: "course_fx_general", lessonsDone: 7, lessonsTotal: 7, status: "STATUS_COMPLETED", lastActivityAt: "2026-11-05", completedAt: "2026-11-05" },
        { courseUuid: "course_fx_tabligh", lessonsDone: 5, lessonsTotal: 5, status: "STATUS_COMPLETED", lastActivityAt: "2026-11-06", completedAt: "2026-11-06" }],
      listAssignments: async (u) => [{ uuid: `${u}:s`, title: "Final sign-off", kind: "signoff" }],
      listSubmissions: async () => [{ userId: 7, status, grade: null, percent: null, attempt: 1, updatedAt: "2026-11-07 10:00:00" }],
    });
    const run = async (st: string) => (await runSnapshotSync({ cycle, roster: [e], courses: fixtureCourses(), today: "2026-11-10", store: memoryStore().store, port: mk(st) })).rows[0]!;
    for (const ok of ["SUBMITTED", "GRADED", "LATE"]) expect((await run(ok)).stage).toBe("attested");
    expect((await run("PENDING")).stage).toBe("completed");
  });
  test("assignment classification", () => {
    expect(classifyAssignment("Final sign-off")).toBe("signoff"); expect(classifyAssignment("Contact self-check")).toBe("selfcheck");
    expect(classifyAssignment("Nizam knowledge quiz")).toBe("quiz"); expect(classifyAssignment("Reflection")).toBe("other");
  });
});
