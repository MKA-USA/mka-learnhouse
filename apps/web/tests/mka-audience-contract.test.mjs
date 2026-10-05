// MKA fork: API <-> UI contract for the audience block. The fixtures in tests/fixtures/mka-audience/*.json are REAL responses dumped
// by the API test world (apps/api/src/tests/routers/test_mka_audience_contract_dump.py). Here they are shape-checked against
// components/mka/audience/types.ts by a small runtime validator that mirrors those types (plus the extra invariants the UI relies on).
import { describe, expect, test } from "bun:test";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

const DIR = join(import.meta.dir, "fixtures", "mka-audience");
const fx = Object.fromEntries(readdirSync(DIR).filter((f) => f.endsWith(".json")).map((f) => [f.replace(/\.json$/, ""), JSON.parse(readFileSync(join(DIR, f), "utf8"))]));
const ok = (name) => { expect(fx[name].status).toBe(200); return fx[name].body; };

// ---- mini shape language: "string" | "number" | "boolean" | "string?" (nullable) | [shape] | {k: shape} | {enum:[..]} ; "k?" = optional key ----
const problems = [];
function check(path, shape, v) {
  if (typeof shape === "string") {
    const nullable = shape.endsWith("?");
    const t = nullable ? shape.slice(0, -1) : shape;
    if (v === null || v === undefined) { if (!nullable) problems.push(`${path}: null/undefined, want ${t}`); return; }
    if (typeof v !== t) problems.push(`${path}: ${typeof v}, want ${t}`);
  } else if (Array.isArray(shape)) {
    if (!Array.isArray(v)) return problems.push(`${path}: not an array`);
    v.forEach((x, i) => check(`${path}[${i}]`, shape[0], x));
  } else if (shape.enum) {
    if (!shape.enum.includes(v)) problems.push(`${path}: ${JSON.stringify(v)} not in ${shape.enum}`);
  } else if (shape.exact) {
    check(path, shape.exact, v);
    if (v && typeof v === "object") for (const k of Object.keys(v)) if (!(k in shape.exact) && !(`${k}?` in shape.exact)) problems.push(`${path}.${k}: unexpected key`);
  } else {
    if (v === null || typeof v !== "object" || Array.isArray(v)) return problems.push(`${path}: not an object`);
    for (const [k, s] of Object.entries(shape)) {
      if (k.endsWith("?")) { if (k.slice(0, -1) in v) check(`${path}.${k.slice(0, -1)}`, s, v[k.slice(0, -1)]); }
      else if (!(k in v)) problems.push(`${path}.${k}: missing`);
      else check(`${path}.${k}`, s, v[k]);
    }
  }
}
const validate = (shape, v, name) => { problems.length = 0; check(name, shape, v); return [...problems]; };
const exact = (shape) => ({ exact: shape });

const LEVELS = ["national", "regional", "local"];
const level = { enum: LEVELS };
// types.ts: MkaViewerAttributes (status is `MkaStatus | string`, department/role/... are `string | null`)
const viewerAttrs = exact({ status: "string", is_officeholder: "boolean?", level: "string?", department: "string?", role: "string?", role_title: "string?", majlis: "string?", region: "string?" });
// types.ts: Group / Rule. The API ships raw preset rules; unknown keys would be tolerated by the UI but presets must not carry any.
const group = exact({ "officeholder?": "boolean", "level?": ["string"], "department?": ["string"], "role?": ["string"], "region?": ["string"], "majlis?": ["string"] });
const rule = exact({ v: "number", mode: { enum: ["show", "hide"] }, groups: [group], "label?": "string" });
const SHAPES = {
  me: exact({ attributes: viewerAttrs, stale: "boolean", can_view_all: "boolean", rules_version: "string" }),
  options: exact({
    rules_version: "string",
    levels: [exact({ key: level, label: "string" })],
    departments: [exact({ key: "string", name: "string", aka: ["string"] })],
    roles: [exact({ key: "string", title: "string", plural: "string" })],
    regions: [exact({ name: "string" })],
    majlis: [exact({ name: "string", region: "string" })],
    presets: [exact({ id: "string", label: "string", rule, "needs_author_department?": "boolean" })],
    personas: [exact({ id: "string", label: "string", attributes: viewerAttrs })],
    copy: exact({ not_secret: "string", unrecognized_note: "string", empty_lesson: "string", count_tooltip: "string" }),
  }),
  count: exact({
    count: "number", total_officeholders: "number", unrecognized: "number",
    by_level: exact({ national: "number", regional: "number", local: "number" }),
    expected: "object?",
  }),
  counterparts: exact({
    counterparts: [exact({ level, role_title: "string", email: "string", name: "string?", department: "string?" })],
    reason: "string?",
  }),
};
const expectedShape = exact({ matching: "number", total: "number", cycle_id: "number" });

describe("shapes: API fixtures satisfy components/mka/audience/types.ts", () => {
  test("fixtures exist", () => {
    for (const n of ["me", "options", "count", "counterparts"]) expect(fx[n]).toBeDefined();
    expect(Object.keys(fx).length).toBeGreaterThanOrEqual(10);
  });
  for (const n of ["me", "me_author", "me_unrecognized"]) test(n, () => expect(validate(SHAPES.me, ok(n), n)).toEqual([]));
  test("options", () => expect(validate(SHAPES.options, ok("options"), "options")).toEqual([]));
  test("count (with an expected roster)", () => {
    const b = ok("count");
    expect(validate(SHAPES.count, b, "count")).toEqual([]);
    expect(validate(expectedShape, b.expected, "count.expected")).toEqual([]);
  });
  test("count without a cycle: expected is null", () => {
    const b = ok("count_no_cycle");
    expect(validate(SHAPES.count, b, "count_no_cycle")).toEqual([]);
    expect(b.expected).toBeNull();
  });
  for (const n of ["counterparts", "counterparts_atfal", "counterparts_unrecognized", "counterparts_no_department"])
    test(n, () => expect(validate(SHAPES.counterparts, ok(n), n)).toEqual([]));
});

describe("invariants the UI relies on", () => {
  test("me: unrecognized viewer reads as unknown, never as 'not an officeholder'", () => {
    const b = ok("me_unrecognized");
    expect(b.attributes.status).toBe("unrecognized");
    expect(b.attributes.is_officeholder).toBeNull();
    expect(b.can_view_all).toBe(false);
  });
  test("me: course author is elevated for that course only", () => {
    expect(ok("me_author").can_view_all).toBe(true);
    expect(ok("me").can_view_all).toBe(false);
  });
  test("options: presets and personas are internally consistent with the vocabulary", () => {
    const o = ok("options");
    const depts = new Set(o.departments.map((d) => d.key));
    const roles = new Set(o.roles.map((r) => r.key));
    const regions = new Set(o.regions.map((r) => r.name));
    const majlis = new Map(o.majlis.map((m) => [m.name, m.region]));
    expect(o.levels.map((l) => l.key)).toEqual(LEVELS);
    expect(o.departments.length).toBe(21);
    for (const r of o.roles) expect(r.key).not.toContain(":");
    for (const m of o.majlis) expect(regions.has(m.region)).toBe(true);
    for (const p of o.presets) for (const g of p.rule.groups) {
      for (const d of g.department ?? []) expect(depts.has(d)).toBe(true);
      for (const r of g.role ?? []) expect(roles.has(r)).toBe(true);
      for (const r of g.region ?? []) expect(regions.has(r)).toBe(true);
      for (const m of g.majlis ?? []) expect(majlis.has(m)).toBe(true);
      for (const l of g.level ?? []) expect(LEVELS).toContain(l);
    }
    for (const p of o.personas) {
      const a = p.attributes;
      if (a.department) expect(depts.has(a.department)).toBe(true);
      if (a.role) expect(roles.has(a.role)).toBe(true);
      if (a.majlis) expect(majlis.get(a.majlis)).toBe(a.region);
    }
    expect(o.presets.filter((p) => p.needs_author_department).map((p) => p.id)).toEqual(["my-department"]);
    expect(new Set(o.presets.map((p) => p.id)).size).toBe(o.presets.length);
    expect(new Set(o.personas.map((p) => p.id)).size).toBe(o.personas.length);
    expect(o.personas.some((p) => p.attributes.status === "unrecognized" && p.attributes.is_officeholder === null)).toBe(true);
    expect(o.personas.some((p) => p.attributes.status === "not_applicable" && p.attributes.is_officeholder === false)).toBe(true);
  });
  test("options: copy strings are the frozen texts", () => {
    const c = ok("options").copy;
    expect(c.not_secret.startsWith("Visibility is for convenience, not secrecy.")).toBe(true);
    expect(c.empty_lesson).toBe("Nothing in this lesson applies to your role. You can mark it complete and continue.");
  });
  test("count: aggregates only, no personal data", () => {
    for (const n of ["count", "count_no_cycle"]) {
      const text = JSON.stringify(fx[n].body);
      expect(text).not.toContain("@");
      const b = fx[n].body;
      expect(b.by_level.national + b.by_level.regional + b.by_level.local).toBeLessThanOrEqual(b.count);
      for (const v of [b.count, b.total_officeholders, b.unrecognized]) expect(v).toBeGreaterThanOrEqual(0);
    }
    const e = ok("count").expected;
    expect(e.matching).toBeLessThanOrEqual(e.total);
  });
  test("counterparts: levels in national, regional, local order; reason explains an empty list", () => {
    const rank = { national: 0, regional: 1, local: 2 };
    for (const n of ["counterparts", "counterparts_atfal"]) {
      const levels = ok(n).counterparts.map((c) => rank[c.level]);
      expect(levels).toEqual([...levels].sort((a, b) => a - b));
      for (const c of ok(n).counterparts) expect(c.email).toMatch(/^[^@\s]+@[^@\s]+$/);
    }
    expect(ok("counterparts_unrecognized")).toEqual({ counterparts: [], reason: "unrecognized" });
    expect(ok("counterparts_no_department")).toEqual({ counterparts: [], reason: "no_department" });
    expect(ok("counterparts").reason).toBeNull();
  });
});

describe("error shapes", () => {
  test("403/422 carry a string `detail` and the status the UI branches on", () => {
    for (const [n, s] of [["err_403_count_learner", 403], ["err_403_options_non_member", 403], ["err_422_count_invalid_rule", 422]]) {
      expect(fx[n].status).toBe(s);
      expect(typeof fx[n].body.detail).toBe("string");
    }
    expect(fx.err_422_count_invalid_rule.body.detail).toBe("mode must be 'show' or 'hide'");
  });
  test("every fixture records path/status/body", () => {
    for (const [n, f] of Object.entries(fx)) {
      expect(Object.keys(f).sort(), n).toEqual(["body", "path", "status"]);
      expect(typeof f.path).toBe("string");
    }
  });
});
