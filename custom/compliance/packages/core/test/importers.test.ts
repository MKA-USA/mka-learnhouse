import { describe, expect, test } from "bun:test";
import { parseCsv, parseDeptPlans, parseOverrides, parseNames, applyOverrides, buildGapReport, generateRoster, resolveDepartment, resolveMajlis } from "../src";

describe("csv", () => {
  test("quotes, commas, newlines, BOM, CRLF", () => {
    const r = parseCsv('﻿a,b,c\r\n1,"x, y","line1\nline2"\r\n2,"he said ""hi""",\r\n');
    expect(r.headers).toEqual(["a", "b", "c"]);
    expect(r.rows[0]!.cells).toEqual(["1", "x, y", "line1\nline2"]);
    expect(r.rows[1]!.cells).toEqual(["2", 'he said "hi"', ""]);
    expect(r.rows[1]!.line).toBe(4);
  });
});

describe("resolvers", () => {
  test("department aliases", () => {
    expect(resolveDepartment("Tarbiyat")).toBe("tarbiyyat");
    expect(resolveDepartment("Tarbiyat Training Course")).toBe("tarbiyyat");
    expect(resolveDepartment("General Secretary")).toBe("aitmad");
    expect(resolveDepartment("nonsense")).toBeNull();
  });
  test("syracuse alias", () => {
    expect(resolveMajlis("syracuse")).toEqual({ name: "Syracuse-Binghamton", aliased: true });
    expect(resolveMajlis("Saint Louis").name).toBe("Saint Louis");
  });
});

const PLANS = `department,level,responsibilities_md,okrs_md,resources_md,updated_by,stale
Tabligh,all,"# Duties\n- one\n- two","Objective 1: Grow",,raza,false
Tarbiyat,national,#REF!,"Objective 1: Pray",,x,true
Bogus,all,hi,,,,
Maal,all,,,,,
Tabligh,all,"# Duties v2",,,raza,false
Ishaat,all,"short row
Taleem,planet,x,,,,
`;
describe("dept plans importer", () => {
  const r = parseDeptPlans(PLANS);
  test("never throws, reports issues", () => {
    const codes = r.issues.map((i) => i.code);
    expect(codes).toContain("sheet-error");
    expect(codes).toContain("unknown-department");
    expect(codes).toContain("empty-plan");
    expect(codes).toContain("duplicate-key");
    expect(codes).toContain("slug-alias");
  });
  test("later duplicate wins; aliases resolved; docs derived", () => {
    const t = r.rows.find((x) => x.departmentSlug === "tabligh")!;
    expect(t.responsibilitiesMd).toBe("# Duties v2");
    expect(t.responsibilitiesDoc?.content[0]?.type).toBe("heading");
    expect(r.rows.find((x) => x.departmentSlug === "tarbiyyat")!.responsibilitiesDoc).toBeNull();
  });
  test("idempotent: parsing twice is identical", () => { expect(parseDeptPlans(PLANS).rows).toEqual(r.rows); });
  test("missing column is reported, not thrown", () => { expect(parseDeptPlans("a,b\n1,2").issues[0]!.code).toBe("missing-column"); });
});

const OV = `department,level,role,region,majlis,learner_email,person_name,note
Tabligh,,,,Boston,tabligh.boston@mkausa.org,Test Nazim,
Atfal,,nazim_atfal,,Syracuse,nazim.syracuse@atfalusa.org,Atfal Nazim,syracuse alias
Atfal,,,,Dayton,amoor-e-tuluba.dayton@mkausa.org,,swapped
Maal,,,,Austin,tabligh.austin@mkausa.org,,wrong dept
Tajneed,,,,Nowhere,tajneed.nowhere@mkausa.org,,
Taleem,,,,Albany,#REF!,#REF!,
Mohasib,,,,Albany,mohasib.albany@mkausa.org,"Dup Person",
Mohasib,,,,Boston,mohasib.albany@mkausa.org,,dup mailbox
Waqf-e-Nau,,,,Detroit,waqf-e-nau.detroit@mkausa.org
Sehat-e-Jismani,,,,Atlanta,nobody-at-example,,
`;
describe("directory overrides importer", () => {
  const r = parseOverrides(OV);
  const codes = r.issues.map((i) => i.code);
  test("quirks detected", () => {
    expect(codes).toContain("slug-alias");
    expect(codes).toContain("swapped-columns");
    expect(codes).toContain("department-mismatch");
    expect(codes).toContain("unknown-majlis");
    expect(codes).toContain("sheet-error");
    expect(codes).toContain("duplicate-mailbox");
    expect(codes).toContain("email-majlis-mismatch");
    expect(codes).toContain("shifted-row");
    expect(codes).toContain("bad-email");
  });
  test("swapped Atfal/Amoor-e-Tuluba is auto-corrected from the mailbox", () => {
    expect(r.rows.find((x) => x.majlis === "Dayton")?.departmentSlug).toBe("amoor-e-tuluba");
  });
  test("applyOverrides: matches by dept/level/majlis(+role), marks source, reports ambiguity", () => {
    const base = generateRoster();
    const { roster, issues } = applyOverrides(base, r.rows);
    const t = roster.find((x) => x.learnerEmail === "tabligh.boston@mkausa.org")!;
    expect(t.personName).toBe("Test Nazim"); expect(t.source).toBe("override");
    expect(roster.find((x) => x.role === "nazim_atfal" && x.majlis === "Syracuse-Binghamton")?.personName).toBe("Atfal Nazim");
    expect(roster.length).toBe(base.length);
    expect(issues.every((i) => i.code.startsWith("override-"))).toBe(true);
  });
  test("no PII-free crash on empty input", () => { expect(parseOverrides("").issues[0]!.code).toBe("missing-column"); });
});

describe("names importer", () => {
  test("shifted, error, missing, valid", () => {
    const r = parseNames("email,name\ntabligh.boston@mkausa.org,Ali\nmaal.boston@mkausa.org,maal.x@mkausa.org\ntaleem.boston@mkausa.org,#REF!\nishaat.boston@mkausa.org,N/A\nnot-an-email,Bob\n");
    expect(r.names.get("tabligh.boston@mkausa.org")).toBe("Ali");
    expect(r.names.size).toBe(1);
    expect(r.issues.map((i) => i.code).sort()).toEqual(["bad-email", "missing-name", "sheet-error", "shifted-row"]);
  });
});

describe("gap report", () => {
  test("headline counts and no personal names", () => {
    const roster = generateRoster({ names: new Map([["tabligh.boston@mkausa.org", "Secret Name"]]) });
    const { markdown, counts } = buildGapReport({ cycleLabel: "2026-27", roster, plans: [{ departmentSlug: "tabligh", level: "all", stale: true, source: "x" }], issues: [{ file: "f", line: 2, severity: "warn", code: "sheet-error", message: "m" }] });
    expect(counts.rosterRows).toBe(roster.length);
    expect(counts.missingNames).toBe(roster.length - 1);
    expect(counts.departmentsWithoutPlan).toBe(20);
    expect(counts.departmentsStalePlanOnly).toBe(1);
    expect(markdown).toContain("Departments with **no plan**");
    expect(markdown).not.toContain("Secret Name");
  });
});
