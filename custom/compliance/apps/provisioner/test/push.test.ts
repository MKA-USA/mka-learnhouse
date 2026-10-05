import { describe, expect, test } from "bun:test";
import {
  LhApi, LhClient, MAX_EXPECTED_ROWS, assignAuthors, buildCyclePayload, buildCycleCourses, chunk, forkDepartment, generateRoster, pushCycle, pushExpected, toExpectedRow,
  validateCyclePayload, validateExpected, validateExpectedRow, type MapRow, type RosterRow,
} from "@mka/compliance-core";
import { SafetyError, LhHttpError } from "@mka/compliance-core";
import { parseArgs } from "../src/args";
import { cmdPushCycle, cmdPushRoster, cmdAssignAuthors } from "../src/commands-push";
import { resolveDates } from "../src/cycles";

/** Contract mock: ports services/mka/compliance_import.py validation + response shapes. */
function forkMock() {
  const seen: { method: string; path: string; query: string; auth: string | null; body: any }[] = [];
  const fetchFn = (async (url: string, init: RequestInit) => {
    const u = new URL(url); const body = init.body ? JSON.parse(String(init.body)) : null;
    seen.push({ method: String(init.method), path: u.pathname, query: u.search, auth: (init.headers as Record<string, string>).Authorization ?? null, body });
    if (u.pathname.endsWith("/mka/compliance/cycles")) {
      if (!u.searchParams.get("org_slug")) return new Response(JSON.stringify({ detail: "org_slug is required for API-token access" }), { status: 422 });
      if (!Array.isArray(body.courses) || !(body.cycle || body.label) || !(body.deadline || body.deadline_on)) return new Response("{}", { status: 422 });
      const courses = body.courses.map((c: any, i: number) => ({ row: i, course_uuid: c.course_uuid, ok: ["general", "department"].includes(c.kind) && (c.kind === "general" || !!c.department), action: "created" }));
      return new Response(JSON.stringify({ cycle: { id: 1, label: body.cycle, starts_on: body.starts_on, deadline_on: body.deadline_on ?? body.deadline, action: "created" }, courses, ok: courses.filter((c: any) => c.ok).length, failed: courses.filter((c: any) => !c.ok).length }), { status: 200 });
    }
    if (u.pathname.endsWith("/mka/compliance/expected/import")) {
      if (body.rows.length > 2000) return new Response("{}", { status: 422 });
      const errors: { row: number; error: string }[] = [];
      body.rows.forEach((r: ExpectedLike, i: number) => { const e = validateExpectedRow(r as any); if (e) errors.push({ row: i, error: e }); });
      const extraKeys = Object.keys(body).filter((k) => !["cycle_id", "cycle", "rows", "dry_run"].includes(k)); // extra="forbid"
      if (extraKeys.length) return new Response("{}", { status: 422 });
      return new Response(JSON.stringify({ cycle_id: 1, received: body.rows.length, created: body.rows.length - errors.length, updated: 0, unchanged: 0, failed: errors.length, errors, dry_run: body.dry_run, departments_without_course: [] }), { status: 200 });
    }
    return new Response("{}", { status: 404 });
  }) as unknown as typeof fetch;
  return { seen, client: new LhClient({ baseUrl: "https://ilm-dev.mkausa.org/api/v1", token: "tok", orgSlug: "default", delayMs: 0, sleep: async () => {}, fetch: fetchFn }) };
}
type ExpectedLike = Record<string, unknown>;

const row = (kind: string, dept: string, withAssignments = true): MapRow => ({ cycleId: 1, kind, departmentSlug: dept, lhCourseUuid: `course_${dept || "g"}`, lhCourseId: 1, contentHash: null,
  structure: { courseId: 1, metaHash: "m", chapters: {}, activities: withAssignments ? { signoff: { id: 1, uuid: "a1", hash: "h", chapterKey: "c", kind: "assignment", assignmentUuid: "assignment_s", tasks: {} } } : {} } });

describe("push-cycle payload", () => {
  const file = buildCycleCourses("2026-27", "2026-11-01", "2026-12-01", [row("general", ""), row("department", "sanat-o-tijarat")]);
  const p = buildCyclePayload(file, "2026-11-01", "2026-12-01");
  test("fork department keys, dates from config, signoff refs", () => {
    expect(p.courses.map((c) => c.department).sort()).toEqual(["sanat_o_tijarat", null].sort());
    const dept = p.courses.find((c) => c.kind === "department")!;
    expect(p).toMatchObject({ cycle: "2026-27", starts_on: "2026-11-01", deadline: "2026-12-01", deadline_on: "2026-12-01" });
    expect(dept.signoff).toEqual({ assignment_uuid: "assignment_s" }); expect(dept.contact_check).toBeNull();
    expect(validateCyclePayload(p)).toEqual([]);
  });
  test("validation mirrors the API (dates, kinds)", () => {
    expect(validateCyclePayload({ ...p, starts_on: "2027-01-01" })).toContain("starts_on must not be after the deadline");
    expect(validateCyclePayload({ ...p, deadline: "12/01/2026" }).length).toBeGreaterThan(0);
    expect(validateCyclePayload({ ...p, courses: [{ ...p.courses.find((c) => c.kind === "department")!, department: null }] }).join()).toContain("department is required");
  });
  test("sent with Bearer token and org_slug query", async () => {
    const { client, seen } = forkMock(); const r = await pushCycle(client, p);
    expect(r.ok).toBe(2); expect(seen[0]).toMatchObject({ method: "POST", path: "/api/v1/mka/compliance/cycles", query: "?org_slug=default", auth: "Bearer tok" });
  });
  test("cycle dates: flags > table row > defaults; unknown label needs flags", () => {
    expect(resolveDates("2026-27", {}, null)).toEqual({ startsOn: "2026-11-01", deadlineOn: "2026-12-01" });
    expect(resolveDates("2026-27", {}, { startsOn: "2026-11-05", deadlineOn: "2026-12-10" })).toEqual({ startsOn: "2026-11-05", deadlineOn: "2026-12-10" });
    expect(resolveDates("2026-27", { deadlineOn: "2026-12-15" }, { startsOn: "2026-11-05", deadlineOn: "2026-12-10" }).deadlineOn).toBe("2026-12-15");
    expect(resolveDates("2030-31", {}, null).startsOn).toBeUndefined();
  });
});

describe("push-roster payload", () => {
  const roster = generateRoster({ names: new Map([["tabligh.boston@mkausa.org", "Known Name"]]) });
  const rows = roster.map(toExpectedRow);
  test("every generated row is accepted by the contract validator", () => {
    const v = validateExpected(rows);
    expect(v.errors).toEqual([]); expect(v.duplicates).toBe(0); expect(rows.length).toBe(roster.length);
  });
  test("levels, department keys, unconfirmed flag, person_name", () => {
    expect(new Set(rows.map((r) => r.level))).toEqual(new Set(["national", "regional", "local"]));
    expect(rows.find((r) => r.email === "tabligh.boston@mkausa.org")).toMatchObject({ level: "local", majlis: "Boston", region: "Northeast", department: "tabligh", person_name: "Known Name", formula_unconfirmed: false });
    expect(rows.find((r) => r.email === "sanat-o-tijarat.east@mkausa.org")).toMatchObject({ level: "regional", department: "sanat_o_tijarat", majlis: null, formula_unconfirmed: true });
    expect(rows.find((r) => r.email === "qaid.east@mkausa.org")).toMatchObject({ level: "regional", department: "" });
    expect(rows.filter((r) => r.formula_unconfirmed).length).toBe(200);
  });
  test("bad rows are refused locally", () => {
    const bad = [{ ...rows[0]!, email: "nope" }, { ...rows[1]!, level: "region" }, { ...rows[2]!, role_title: "x".repeat(201) }];
    expect(validateExpected(bad).errors.map((e) => e.row)).toEqual([0, 1, 2]);
  });
  test("batches never exceed the API limit; idempotent re-send is just the same payload", async () => {
    expect(chunk(rows, 1000).every((b) => b.length <= 1000)).toBe(true);
    expect(() => chunk(rows, MAX_EXPECTED_ROWS + 1)).toThrow();
    const { client, seen } = forkMock();
    const r = await pushExpected(client, "2026-27", rows.slice(0, 5), true);
    expect(r.dry_run).toBe(true); expect(seen[0]!.body).toEqual({ cycle: "2026-27", rows: rows.slice(0, 5), dry_run: true });
    expect(seen[0]!.query).toBe("?org_slug=default");
  });
  test("forkDepartment", () => { expect(forkDepartment("new-immigrants")).toBe("new_immigrants"); expect(forkDepartment("")).toBe(""); });
});

describe("assign-authors", () => {
  function fake(state: { existing?: { user_id: number; authorship: string; authorship_status: string }[]; users: Record<string, { id: number; username: string }> }) {
    const calls: string[] = [];
    const api = {
      getUserByEmail: async (e: string) => { const u = state.users[e]; if (!u) throw new LhHttpError("GET", "/x", 404, "nf"); return u; },
      getCourseContributors: async () => state.existing ?? [],
      addContributors: async (_c: string, names: string[]) => { calls.push(`add:${names.join(",")}`); return { successful: names, failed: [] }; },
      setContributor: async (_c: string, id: number, au: string, st: string) => { calls.push(`set:${id}:${au}:${st}`); },
    } as unknown as LhApi;
    return { api, calls };
  }
  const rows = [{ department: "tabligh", email: "a@x.org", courseUuid: "c1" }, { department: "maal", email: "ghost@x.org", courseUuid: "c2" }];
  test("dry run writes nothing; reports not-signed-in", async () => {
    const f = fake({ users: { "a@x.org": { id: 5, username: "ann" } } });
    const r = await assignAuthors(f.api, rows, false);
    expect(r.map((x) => x.status)).toEqual(["planned_add", "not_signed_in"]); expect(f.calls).toEqual([]);
  });
  test("apply: add as CONTRIBUTOR then set ACTIVE; pending -> active; active unchanged; creator untouched", async () => {
    let f = fake({ users: { "a@x.org": { id: 5, username: "ann" } } });
    expect((await assignAuthors(f.api, [rows[0]!], true))[0]!.status).toBe("added"); expect(f.calls).toEqual(["add:ann", "set:5:CONTRIBUTOR:ACTIVE"]);
    f = fake({ users: { "a@x.org": { id: 5, username: "ann" } }, existing: [{ user_id: 5, authorship: "CONTRIBUTOR", authorship_status: "PENDING" }] });
    expect((await assignAuthors(f.api, [rows[0]!], true))[0]!.status).toBe("activated"); expect(f.calls).toEqual(["set:5:CONTRIBUTOR:ACTIVE"]);
    f = fake({ users: { "a@x.org": { id: 5, username: "ann" } }, existing: [{ user_id: 5, authorship: "MAINTAINER", authorship_status: "ACTIVE" }] });
    expect((await assignAuthors(f.api, [rows[0]!], true))[0]!.status).toBe("unchanged"); expect(f.calls).toEqual([]);
    f = fake({ users: { "a@x.org": { id: 5, username: "ann" } }, existing: [{ user_id: 5, authorship: "CREATOR", authorship_status: "ACTIVE" }] });
    expect((await assignAuthors(f.api, [rows[0]!], true))[0]!.status).toBe("skipped_creator");
  });
});

describe("guards", () => {
  const env = { ...process.env };
  test("--apply requires --confirm-staging for all three commands", async () => {
    for (const fn of [cmdPushCycle, cmdPushRoster, cmdAssignAuthors]) await expect(fn(parseArgs(["x", "--apply", "--all", "--map", "m.csv"]))).rejects.toBeInstanceOf(SafetyError);
  });
  test("push-roster needs a selection and a legal batch size", async () => {
    await expect(cmdPushRoster(parseArgs(["push-roster"]))).rejects.toBeInstanceOf(SafetyError);
    await expect(cmdPushRoster(parseArgs(["push-roster", "--all", "--batch-size", "5000"]))).rejects.toBeInstanceOf(SafetyError);
  });
  test("non-staging host is refused before any request", async () => {
    process.env.LH_API_BASE = "https://ilm.mkausa.org/api/v1"; process.env.LH_API_TOKEN = "t";
    try { const { assertStaging } = await import("@mka/compliance-core"); expect(() => assertStaging(process.env.LH_API_BASE)).toThrow(SafetyError); } finally { process.env = { ...env }; }
  });
});
void ({} as RosterRow);

import { explainHttp } from "../src/commands-push";
describe("early, clear failures", () => {
  test("403/401/409/404 messages are actionable and PII-free", () => {
    expect(explainHttp(new LhHttpError("POST", "/x", 403, "API token lacks organizations.action_update"))).toContain("organizations.action_update");
    expect(explainHttp(new LhHttpError("POST", "/x", 403, "no bob@x.org"))).not.toContain("bob@x.org");
    expect(explainHttp(new LhHttpError("POST", "/x", 401))).toContain("rejected");
    expect(explainHttp(new LhHttpError("POST", "/x", 409))).toContain("re-run");
    expect(explainHttp(new LhHttpError("POST", "/x", 404, "Cycle not found"))).toContain("push-cycle");
  });
});

describe("appointed_on", () => {
  test("rows with an appointment date carry it; bad dates are refused locally", () => {
    const base = generateRoster()[0]!;
    expect(toExpectedRow({ ...base, appointedOn: "2027-03-15" }).appointed_on).toBe("2027-03-15");
    expect("appointed_on" in toExpectedRow(base)).toBe(false);
    expect(validateExpectedRow({ ...toExpectedRow(base), appointed_on: "03/15/2027" })).toContain("appointed_on");
  });
});
