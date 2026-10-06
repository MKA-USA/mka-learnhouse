// MKA fork: API <-> UI contract. The fixtures in tests/fixtures/mka-compliance/*.json are REAL responses dumped by the API test
// world (apps/api/src/tests/routers/test_mka_compliance_contract_dump.py). Here they are (1) shape-checked against
// services/mka/compliance.types.ts by a small runtime validator that mirrors those types, and (2) fed to the UI helpers.
import { describe, expect, test } from "bun:test";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import {
  attentionTitle, attestedPct, buildHeatmap, cellLabel, chaseTotal, courseForDepartment, deptLabel, learnerKey,
  learnerQuery, nz, safeRag, statusSegments,
} from "../components/mka/compliance/format.ts";
import { Breakdown } from "../components/mka/compliance/Breakdown.tsx";
import { errorStatus, mkaComplianceKeys } from "../services/mka/compliance.ts";

const DIR = join(import.meta.dir, "fixtures", "mka-compliance");
const fx = Object.fromEntries(readdirSync(DIR).filter((f) => f.endsWith(".json")).map((f) => [f.replace(/\.json$/, ""), JSON.parse(readFileSync(join(DIR, f), "utf8"))]));
const ok = (name) => { expect(fx[name].status).toBe(200); return fx[name].body; };

// ---- mini shape language: "string" | "number" | "boolean" | "string?" (nullable) | [shape] | {k: shape} | ["a","b"] enum via {enum:[..]} ----
const STATUSES = ["not_signed_in", "not_started", "in_progress", "completed", "attested", "overdue"];
const RAGS = ["green", "amber", "red", "none"];
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
  } else {
    if (v === null || typeof v !== "object") return problems.push(`${path}: not an object`);
    for (const [k, s] of Object.entries(shape)) {
      if (k.endsWith("?")) { if (k.slice(0, -1) in v) check(`${path}.${k.slice(0, -1)}`, s, v[k.slice(0, -1)]); }
      else if (!(k in v)) problems.push(`${path}.${k}: missing`);
      else check(`${path}.${k}`, s, v[k]);
    }
  }
}
const validate = (shape, v, name) => { problems.length = 0; check(name, shape, v); return [...problems]; };

const cycle = { id: "number", label: "string", starts_on: "string", deadline_on: "string" };
const counts = { expected: "number", not_signed_in: "number", not_started: "number", in_progress: "number", completed: "number", attested: "number", overdue: "number" };
const rag = { enum: RAGS };
const scopeCourse = { course_uuid: "string", name: "string", kind: { enum: ["general", "department"] }, department: "string?", "department_name?": "string?" };
// The UI types say `region: string` / `majlis: string`; the API sends null for unassigned groups, so the types are widened to
// `string | null` (fixed in compliance.types.ts) and the shapes below follow the fixed types.
const SHAPES = {
  scope: { scope: { enum: ["all", "own", "none"] }, courses: [scopeCourse], departments: ["string"], "cycle?": { ...cycle }, "cycles?": [cycle] },
  overview: {
    cycle: { ...cycle }, totals: counts,
    departments: [{ ...counts, department: "string", "department_name?": "string?", attested_pct: "number", rag, score: "number", reasons: ["string"] }],
    cells: [{ ...counts, department: "string", "department_name?": "string?", region: "string?", rag, reasons: ["string"] }],
    attention: [{ department: "string", "department_name?": "string?", "region?": "string?", rag, "score?": "number", reasons: ["string"] }],
  },
  summary: {
    cycle: { ...cycle }, course: { course_uuid: "string", name: "string" }, totals: counts,
    by_region: [{ ...counts, region: "string?" }], by_majlis: [{ ...counts, majlis: "string?", "region?": "string?" }],
    by_level: [{ ...counts, level: { enum: ["national", "regional", "local"] } }], rag, reasons: ["string"],
  },
  learner: {
    "id?": "number", email: "string", role_title: "string?", person_name: "string?", department: "string", "department_name?": "string?",
    level: { enum: ["national", "regional", "local"] }, majlis: "string?", region: "string?", signed_in: "boolean",
    status: { enum: STATUSES }, lessons_done: "number", lessons_total: "number", last_activity_at: "string?", attested_at: "string?",
    contact_check: { "answers?": "object?", mismatch: "boolean?" },
  },
};
SHAPES.learners = { cycle: { ...cycle }, items: [SHAPES.learner], total: "number" };

describe("shapes: API fixtures satisfy compliance.types.ts", () => {
  test("fixtures exist", () => expect(Object.keys(fx).length).toBeGreaterThanOrEqual(20));
  for (const n of ["scope_all", "scope_own", "scope_none", "nocycle_scope"])
    test(n, () => {
      const body = ok(n);
      const shape = { ...SHAPES.scope, "cycle?": body.cycle ? { ...cycle } : "object?" };
      expect(validate(shape, body, n)).toEqual([]);
    });
  test("overview", () => expect(validate(SHAPES.overview, ok("overview"), "overview")).toEqual([]));
  test("nocycle overview (cycle null, empty)", () => {
    const b = ok("nocycle_overview");
    expect(b.cycle).toBeNull();
    expect(validate({ ...SHAPES.overview, cycle: "object?" }, b, "nocycle_overview")).toEqual([]);
  });
  for (const n of ["course_summary_tabligh", "course_summary_general"])
    test(n, () => expect(validate(SHAPES.summary, ok(n), n)).toEqual([]));
  for (const n of ["learners_tabligh", "learners_general_page2", "learners_general_filtered", "learners_tabligh_as_author"])
    test(n, () => expect(validate(SHAPES.learners, ok(n), n)).toEqual([]));
  test("trend is tolerated (no UI type)", () => expect(Array.isArray(ok("trend_general").series)).toBe(true));
});

describe("error shapes", () => {
  const detail = (n) => fx[n].body.detail;
  test("403/404/422 carry a string `detail` and the status the UI branches on", () => {
    for (const [n, s] of [["err_403_overview_as_author", 403], ["err_403_non_member", 403], ["err_403_learners_as_plain_user", 403],
      ["err_404_out_of_scope_course", 404], ["err_422_org_required", 422], ["nocycle_summary", 404], ["nocycle_learners", 404]]) {
      expect(fx[n].status).toBe(s);
      expect(typeof detail(n)).toBe("string");
      expect(errorStatus({ status: fx[n].status })).toBe(s);
    }
  });
  test("a course outside the scope looks like a missing one", () => {
    expect(fx.err_404_out_of_scope_course.body).toEqual(fx.nocycle_summary.body);
  });
});

describe("UI helpers accept the real responses without throwing", () => {
  test("heatmap + labels from the real overview (null region for the national group)", () => {
    const o = ok("overview");
    const h = buildHeatmap(o.departments, o.cells);
    expect(h.rows.length).toBe(o.departments.length);
    for (const r of h.rows) expect(typeof r.label).toBe("string");
    for (const c of o.cells) expect(cellLabel(c.department, c.region ?? "", c)).toContain(String(c.expected));
    for (const a of o.attention) expect(attentionTitle(a).length).toBeGreaterThan(0);
    for (const reg of h.regions) expect(typeof reg).toBe("string");
    for (const d of o.departments) expect(deptLabel(d.department, d.department_name)).not.toMatch(/^[a-z_]+$/);
  });
  test("counts helpers", () => {
    const o = ok("overview");
    expect(chaseTotal(o.totals)).toBeGreaterThanOrEqual(0);
    expect(attestedPct(o.totals)).toBeGreaterThanOrEqual(0);
    expect(statusSegments(o.totals).length).toBeGreaterThan(0);
    for (const d of o.departments) expect(safeRag(d.rag)).toBe(d.rag);
  });
  test("learner keys are unique per page and nz handles null/empty", () => {
    for (const n of ["learners_tabligh", "learners_general_page2"]) {
      const keys = ok(n).items.map((l) => learnerKey({ ...l, role_title: l.role_title ?? "" }));
      expect(new Set(keys).size).toBe(keys.length);
    }
    expect(nz(null)).toBeNull();
  });
  test("scope: general course has a null department; department courses resolve", () => {
    const s = ok("scope_all");
    const general = s.courses.find((c) => c.kind === "general");
    expect(general.department).toBeNull();
    for (const dep of s.departments) expect(courseForDepartment(s.courses, dep)?.department).toBe(dep);
  });
  test("query keys and learner query build from the real filters", () => {
    expect(mkaComplianceKeys.learners(1, "course_x", 1, learnerQuery({ status: "not_signed_in", level: "local", q: "ghost", page: 2, page_size: 4 }, 1, 1)).length).toBe(6);
    expect(learnerQuery({ status: "not_signed_in" }, 1, 1)).toContain("status=not_signed_in");
  });
  test("a learner whose department is the national group has a display name", () => {
    const l = ok("learners_general_filtered").items.concat(ok("learners_tabligh").items);
    for (const x of l) expect(deptLabel(x.department, x.department_name).length).toBeGreaterThan(0);
  });
  test("Breakdown renders the real summary (null region / Majlis groups sort and label without throwing)", () => {
    for (const n of ["course_summary_tabligh", "course_summary_general"]) {
      const s = ok(n);
      expect(s.by_region.some((r) => r.region === null) || s.by_majlis.some((m) => m.majlis === null)).toBe(true);
      const html = renderToStaticMarkup(React.createElement(Breakdown, { byRegion: s.by_region, byMajlis: s.by_majlis, region: "", majlis: "", onRegion() {}, onMajlis() {} }));
      expect(html).toContain("No region recorded");
    }
  });
});
