import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { renderToStaticMarkup } from "react-dom/server";
import React from "react";

import {
  attestedPct, buildHeatmap, buildQuery, cellLabel, chaseListFilename, chaseTotal, csvCell,
  courseForDepartment, deptLabel, learnerKey, nz, truncationNotice, attentionTitle,
  daysUntil, deadlineLabel, fmtDate, learnerQuery, pctOf, safeRag, sameCourse, statusSegments,
} from "../components/mka/compliance/format.ts";
import { mkaCourseTabs } from "../components/mka/compliance/course-tab.tsx";
import { RagBadge, StatusChip } from "../components/mka/compliance/badges.tsx";

const counts = (o = {}) => ({ expected: 10, not_signed_in: 1, not_started: 2, in_progress: 3, completed: 1, attested: 2, overdue: 1, ...o });

describe("numbers", () => {
  test("pctOf is safe", () => {
    expect(pctOf(1, 0)).toBe(0);
    expect(pctOf(5, 10)).toBe(50);
    expect(pctOf(50, 10)).toBe(100);
    expect(attestedPct(counts())).toBe(20);
  });
  test("chaseTotal and segments", () => {
    expect(chaseTotal(counts())).toBe(4);
    const segs = statusSegments(counts({ completed: 0 }));
    expect(segs.map((s) => s.status)).toEqual(["attested", "in_progress", "not_started", "not_signed_in", "overdue"]);
  });
  test("unknown rag degrades", () => {
    expect(safeRag("purple")).toBe("none");
    expect(safeRag("red")).toBe("red");
  });
});

describe("heatmap", () => {
  const dept = (department, rag, score) => ({ department, rag, score, attested_pct: 0, reasons: [], ...counts() });
  const cell = (department, region, rag) => ({ department, region, rag, reasons: [], ...counts() });
  test("worst department first, regions A-Z", () => {
    const h = buildHeatmap([dept("A", "green", 1), dept("B", "red", 50)], [cell("A", "West", "green"), cell("B", "East", "red")]);
    expect(h.rows.map((r) => r.department)).toEqual(["B", "A"]);
    expect(h.regions).toEqual(["East", "West"]);
  });
  test("cell label never relies on colour", () => {
    expect(cellLabel("Maal", "Gulf", cell("Maal", "Gulf", "red"))).toContain("Needs attention");
    expect(cellLabel("Maal", "Gulf", undefined)).toContain("no expected learners");
  });
});

describe("dates and urls", () => {
  test("dates are UTC-stable", () => {
    expect(fmtDate("2026-10-20")).toBe("Oct 20, 2026");
    expect(fmtDate(null)).toBe("—");
    expect(daysUntil("2026-11-15", "2026-10-20")).toBe(26);
    expect(deadlineLabel("2026-10-19", "2026-10-20")).toBe("1 day past deadline");
  });
  test("buildQuery drops empties and encodes", () => {
    expect(buildQuery({ a: "x y", b: "", c: undefined, d: 0 })).toBe("a=x+y&d=0");
    expect(learnerQuery({ q: " a&b=c ", status: "overdue" }, 3, 7)).toBe("org_id=7&cycle_id=3&status=overdue&q=a%26b%3Dc");
  });
  test("course uuid forms compare equal", () => {
    expect(sameCourse("course_abc", "abc")).toBe(true);
    expect(sameCourse("course_abc", "abd")).toBe(false);
  });
  test("chase list filename is sanitised", () => {
    expect(chaseListFilename("../../Etc/Passwd <x>", "2026-10-20")).toBe("chase-list-etc-passwd-x-2026-10-20.csv");
    expect(chaseListFilename("!!!", "2026-10-20")).toBe("chase-list-course-2026-10-20.csv");
  });
});

describe("API-shape tolerance", () => {
  test("nz treats '' and null alike", () => {
    expect(nz("")).toBeNull();
    expect(nz("  ")).toBeNull();
    expect(nz(null)).toBeNull();
    expect(nz("Gulf")).toBe("Gulf");
  });
  test("department display: name wins, slug is prettified, '' is the national group", () => {
    expect(deptLabel("sanat_o_tijarat", "Sanat-o-Tijarat")).toBe("Sanat-o-Tijarat");
    expect(deptLabel("sanat_o_tijarat", null)).toBe("Sanat O Tijarat");
    expect(deptLabel("", "")).toBe("National leadership");
    expect(deptLabel(null)).toBe("National leadership");
  });
  test("attention title uses the name and ignores empty region", () => {
    expect(attentionTitle({ department: "maal", department_name: "Maal", region: "", rag: "red", reasons: [] })).toBe("Maal");
    expect(attentionTitle({ department: "maal", department_name: "Maal", region: "Gulf", rag: "red", reasons: [] })).toBe("Maal \u00b7 Gulf");
  });
  test("national group row links to the General course; no name-based keys", () => {
    const courses = [{ kind: "general", department: null, id: 1 }, { kind: "department", department: "maal", id: 2 }];
    expect(courseForDepartment(courses, "").id).toBe(1);
    expect(courseForDepartment(courses, "maal").id).toBe(2);
    expect(courseForDepartment(courses, "nope")).toBeUndefined();
  });
  test("learnerKey prefers server id; fallback distinguishes level", () => {
    const base = { email: "a@x", role_title: "Nazim", department: "maal", majlis: null };
    expect(learnerKey({ ...base, id: 7, level: "local" })).toBe("id:7");
    expect(learnerKey({ ...base, level: "local" })).not.toBe(learnerKey({ ...base, level: "regional" }));
  });
  test("heatmap keeps the '' (national) group, labelled", () => {
    const d = { department: "", department_name: "National leadership", rag: "amber", score: 5, attested_pct: 0, reasons: [], ...counts() };
    const h = buildHeatmap([d], []);
    expect(h.rows[0].label).toBe("National leadership");
  });
  test("CSV truncation notice from X-Truncated / X-Row-Limit", () => {
    expect(truncationNotice(null, null)).toBeNull();
    expect(truncationNotice("false", "5000")).toBeNull();
    expect(truncationNotice("true", null)).toBe("List truncated at 5,000 rows. Narrow the filters to get the rest.");
    expect(truncationNotice("True", "2000")).toContain("2,000");
  });
});

describe("csvCell", () => {
  test("neutralises spreadsheet formulas and quotes", () => {
    expect(csvCell("=HYPERLINK(1)")).toBe("'=HYPERLINK(1)");
    expect(csvCell("+1")).toBe("'+1");
    expect(csvCell('a,"b"')).toBe('"a,""b"""');
    expect(csvCell(null)).toBe("");
  });
});

describe("mkaCourseTabs (nav gating is cosmetic, API enforces)", () => {
  test("none -> no tab", () => expect(mkaCourseTabs("abc", "none")).toEqual([]));
  test("all -> tab requiring update", () => {
    const t = mkaCourseTabs("abc", "all");
    expect(t).toHaveLength(1);
    expect(t[0].key).toBe("compliance");
    expect(t[0].requiredPermission).toBe("update");
    expect(t[0].href).toBe("/dash/courses/course/abc/compliance");
  });
  test("own -> only own courses", () => {
    expect(mkaCourseTabs("abc", "own", [{ course_uuid: "course_abc" }])).toHaveLength(1);
    expect(mkaCourseTabs("zzz", "own", [{ course_uuid: "course_abc" }])).toEqual([]);
  });
});

describe("components render text, not just colour", () => {
  test("RagBadge has label and icon", () => {
    const html = renderToStaticMarkup(React.createElement(RagBadge, { rag: "red" }));
    expect(html).toContain("Needs attention");
    expect(html).toContain("<svg");
  });
  test("StatusChip escapes and labels", () => {
    const html = renderToStaticMarkup(React.createElement(StatusChip, { status: "not_signed_in" }));
    expect(html).toContain("Not signed in");
    expect(html).toContain("<svg");
  });
});

describe("hook guard: upstream MKA hook lines exist (re-apply after pulling upstream)", () => {
  const read = (p) => readFileSync(new URL(`../${p}`, import.meta.url), "utf8");
  test("H1 DashLeftMenu", () => {
    const s = read("components/Dashboard/Menus/DashLeftMenu.tsx");
    expect(s).toContain("const mkaScope = useMkaComplianceScope() // MKA fork");
    expect(s).toContain('href="/dash/compliance"');
    expect(s).toMatch(/import \{ ShieldCheck \} from '@phosphor-icons\/react' \/\/ MKA fork/);
  });
  test("H2 DashMobileMenu", () => {
    const s = read("components/Dashboard/Menus/DashMobileMenu.tsx");
    expect(s).toContain("const mkaScope = useMkaComplianceScope() // MKA fork");
    expect(s).toContain('<PanelItem href="/dash/compliance"');
  });
  test("H3 course subpage", () => {
    const s = read("app/orgs/[orgslug]/dash/courses/course/[courseuuid]/[subpage]/page.tsx");
    expect(s).toContain("tabs.push(...useMkaCourseTabs(params.courseuuid)) // MKA fork");
    expect(s).toContain("params.subpage == 'compliance' && hasPermission('update')");
    expect(s).toContain("from '@components/mka/compliance/course-tab' // MKA fork");
  });
});
