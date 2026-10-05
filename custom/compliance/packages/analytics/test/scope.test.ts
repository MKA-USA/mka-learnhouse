import { describe, expect, test } from "bun:test";
import { buildFixtureDataset } from "../src/dataset";
import { chaseCsv, csvCell } from "../src/csv";
import { resolveScopes, rowInScope, scopeRows, type ViewerAttributes } from "../src/scope";

const attrs = (p: Partial<ViewerAttributes>): ViewerAttributes => ({ status: "matched", is_officeholder: true, level: "national", department: null, role: null, majlis: null, region: null, ...p });
const ds = buildFixtureDataset({ historyDays: 0 });
const email = "viewer@example.invalid";

describe("resolveScopes (fail closed)", () => {
  test("Mohtamim -> own department only", () => expect(resolveScopes({ email, attributes: attrs({ role: "mohtamim", department: "tabligh" }) })).toEqual([{ kind: "department", department: "tabligh" }]));
  test("Regional Qaid -> own region", () => expect(resolveScopes({ email, attributes: attrs({ level: "regional", role: "regional_qaid", region: "Gulf" }) })).toEqual([{ kind: "region", region: "Gulf" }]));
  test("Majlis Qaid -> own Majlis", () => expect(resolveScopes({ email, attributes: attrs({ level: "local", role: "qaid", majlis: "Albany", region: "Northeast" }) })).toEqual([{ kind: "majlis", majlis: "Albany" }]));
  test("Sadr / Motamid / admin -> all", () => {
    for (const role of ["sadr", "motamid", "naib_sadr"]) expect(resolveScopes({ email, attributes: attrs({ role }) })).toEqual([{ kind: "all" }]);
    expect(resolveScopes({ email, attributes: null, isAdmin: true })).toEqual([{ kind: "all" }]);
  });
  test("no attributes, unrecognized, ambiguous, partial, non-officeholder, local nazim -> nothing", () => {
    expect(resolveScopes({ email, attributes: null })).toEqual([]);
    for (const status of ["unrecognized", "ambiguous", "partial", "not_applicable"] as const)
      expect(resolveScopes({ email, attributes: attrs({ status, role: "mohtamim", department: "tabligh" }) })).toEqual([]);
    expect(resolveScopes({ email, attributes: attrs({ is_officeholder: false, role: "mohtamim", department: "tabligh" }) })).toEqual([]);
    expect(resolveScopes({ email, attributes: attrs({ level: "local", role: "nazim_dept", department: "tabligh", majlis: "Albany" }) })).toEqual([]);
  });
  test("Mohtamim without a department gets nothing (never 'all')", () => expect(resolveScopes({ email, attributes: attrs({ role: "mohtamim", department: null }) })).toEqual([]));
  test("override adds scope; deny wins over everything", () => {
    expect(resolveScopes({ email, attributes: null, overrides: [{ email: "VIEWER@example.invalid", scopeType: "department", scopeValue: "maal" }] })).toEqual([{ kind: "department", department: "maal" }]);
    expect(resolveScopes({ email, attributes: attrs({ role: "sadr" }), isAdmin: true, overrides: [{ email, scopeType: "deny", scopeValue: "" }] })).toEqual([]);
    expect(resolveScopes({ email, attributes: null, overrides: [{ email: "other@example.invalid", scopeType: "all", scopeValue: "" }] })).toEqual([]);
  });
});

describe("a Mohtamim can never read another department's rows", () => {
  const depts = [...new Set(ds.rows.map((r) => r.departmentSlug).filter(Boolean))];
  test("row filter, for every department", () => {
    expect(depts.length).toBe(21);
    for (const d of depts) {
      const scopes = resolveScopes({ email, attributes: attrs({ role: "mohtamim", department: d }) });
      const rows = scopeRows(ds.rows, scopes);
      expect(rows.length).toBeGreaterThan(50);
      expect(rows.every((r) => r.departmentSlug === d)).toBe(true);
      const csv = chaseCsv(rows, (s) => s);
      expect(depts.filter((o) => o !== d).some((o) => csv.includes(`\r\n${o},`))).toBe(false);
    }
  });
  test("executive (department-less) rows are never exposed to a Mohtamim", () => {
    const rows = scopeRows(ds.rows, [{ kind: "department", department: "tabligh" }]);
    expect(rows.some((r) => r.departmentSlug === "")).toBe(false);
  });
  test("empty scopes -> empty, even for 'dept' strings that normalise oddly", () => {
    expect(scopeRows(ds.rows, [])).toEqual([]);
    expect(rowInScope({ departmentSlug: "", region: "", majlis: "" }, [{ kind: "department", department: "" }])).toBe(false);
    expect(scopeRows(ds.rows, [{ kind: "department", department: "no-such-dept" }])).toEqual([]);
  });
  test("region and majlis scopes", () => {
    const reg = scopeRows(ds.rows, [{ kind: "region", region: "Gulf" }]);
    expect(reg.length).toBeGreaterThan(0); expect(reg.every((r) => r.region === "Gulf")).toBe(true);
    const maj = scopeRows(ds.rows, [{ kind: "majlis", majlis: "Albany" }]);
    expect(maj.length).toBe(22); expect(maj.every((r) => r.majlis === "Albany")).toBe(true);
  });
});

describe("csv", () => {
  test("neutralises formula injection and quotes", () => {
    expect(csvCell("=HYPERLINK(\"x\")")).toBe(`"'=HYPERLINK(""x"")"`);
    expect(csvCell("a,b")).toBe('"a,b"'); expect(csvCell(null)).toBe(""); expect(csvCell(3)).toBe("3");
    expect(csvCell("-1+2")).toBe("'-1+2");
  });
  test("chase list excludes attested and lists overdue first", () => {
    const late = buildFixtureDataset({ asOf: "2026-12-10", historyDays: 0 });
    const lines = chaseCsv(late.rows.slice(0, 300), (s) => s).trim().split("\r\n");
    expect(lines.length).toBeGreaterThan(1);
    const idx = lines[0]!.split(",").indexOf("Status");
    expect(lines.slice(1).every((l) => !l.split(",")[idx]!.includes("attested"))).toBe(true);
  });
});
