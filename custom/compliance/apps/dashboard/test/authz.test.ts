import "./setup";
import { beforeAll, describe, expect, test } from "bun:test";
import { buildFixtureDataset } from "@mka/analytics/pure";
import { PERSONAS } from "@/lib/personas";
import { actAs } from "./helpers";

const ds = buildFixtureDataset({ historyDays: 3 });
const depts = [...new Set(ds.rows.map((r) => r.departmentSlug).filter(Boolean))];

describe("scopeDataset (page data)", () => {
  test("Mohtamim sees only their department, in rows AND in every history snapshot", async () => {
    const { scopeDataset } = await import("@/lib/access");
    const p = PERSONAS.find((x) => x.key === "mohtamim-tarbiyyat")!;
    const s = scopeDataset(ds, { email: p.email, name: null }, p.attributes, [], false);
    expect(s.rows.length).toBeGreaterThan(50);
    expect(s.rows.every((r) => r.departmentSlug === "tarbiyyat")).toBe(true);
    for (const rows of Object.values(s.history)) expect(rows.every((r) => r.departmentSlug === "tarbiyyat")).toBe(true);
  });
  test("every persona gets exactly its scope; unrecognised and local Nazim get nothing", async () => {
    const { scopeDataset } = await import("@/lib/access");
    const run = (k: string) => { const p = PERSONAS.find((x) => x.key === k)!; return scopeDataset(ds, { email: p.email, name: null }, p.attributes, [], !!p.isAdmin); };
    expect(run("admin").rows.length).toBe(ds.rows.length);
    expect(run("motamid").rows.length).toBe(ds.rows.length);
    expect(run("regional-gulf").rows.every((r) => r.region === "Gulf")).toBe(true);
    expect(run("majlis-albany").rows.every((r) => r.majlis === "Albany")).toBe(true);
    expect(run("nazim-albany").rows).toEqual([]);
    expect(run("unknown").rows).toEqual([]);
  });
  test("a deny override beats an admin flag", async () => {
    const { scopeDataset } = await import("@/lib/access");
    const p = PERSONAS.find((x) => x.key === "admin")!;
    expect(scopeDataset(ds, { email: p.email, name: null }, null, [{ email: p.email, scopeType: "deny", scopeValue: "" }], true).rows).toEqual([]);
  });
});

describe("CSV and JSON routes never leak another department (acting as a Mohtamim)", () => {
  let chase: (r: Request) => Promise<Response>, rowsRoute: (r: Request) => Promise<Response>;
  beforeAll(async () => {
    actAs("mohtamim-tarbiyyat");
    chase = (await import("../app/api/chase/route")).GET;
    rowsRoute = (await import("../app/api/rows/route")).GET;
  });
  const others = depts.filter((d) => d !== "tarbiyyat");

  test("CSV contains only Tarbiyyat rows, whatever the query asks for", async () => {
    for (const q of ["", "?dept=maal", "?dept=tajneed&region=Gulf", "?majlis=Albany", "?q=maal", "?status=attention&dept=ishaat"]) {
      const res = await chase(new Request(`http://x/api/chase${q}`));
      expect(res.status).toBe(200);
      const lines = (await res.text()).trim().split("\r\n").slice(1);
      for (const l of lines) {
        expect(l.startsWith("Tarbiyyat,")).toBe(true);
        for (const o of others) expect(l.toLowerCase()).not.toContain(`${o.replace(/-/g, "")}.`);
      }
    }
  });
  test("JSON rows only Tarbiyyat, including dept override attempts", async () => {
    for (const q of ["", "?dept=maal", "?dept=executive", "?region=_national"]) {
      const body = await (await rowsRoute(new Request(`http://x/api/rows${q}`))).json() as { rows: { departmentSlug: string }[] };
      expect(body.rows.every((r) => r.departmentSlug === "tarbiyyat")).toBe(true);
    }
  });
});

describe("routes reject unauthenticated and unscoped viewers", () => {
  test("401 with no session", async () => {
    actAs(null);
    const { GET } = await import("../app/api/chase/route");
    expect((await GET(new Request("http://x/api/chase"))).status).toBe(401);
    expect((await (await import("../app/api/rows/route")).GET(new Request("http://x/api/rows"))).status).toBe(401);
  });
  test("403 for a viewer with no scope", async () => {
    actAs("nazim-albany");
    const { GET } = await import("../app/api/chase/route");
    expect((await GET(new Request("http://x/api/chase"))).status).toBe(403);
    expect((await (await import("../app/api/rows/route")).GET(new Request("http://x/api/rows"))).status).toBe(403);
  });
});
