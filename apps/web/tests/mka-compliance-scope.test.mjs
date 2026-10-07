// MKA fork seam C: the viewer-scope helpers of the Compliance page (pure; the API enforces on every endpoint).
import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { hasOverview, scopeKind, scopeLabel } from "../components/mka/compliance/format.ts";
import { mkaCourseTabs } from "../components/mka/compliance/course-tab.tsx";

const fixture = (n) => JSON.parse(readFileSync(join(import.meta.dir, "fixtures", "mka-compliance", `${n}.json`), "utf8")).body;

describe("scopeKind", () => {
  test("reads kind, falls back to the legacy scope string", () => {
    expect(scopeKind({ scope: "own", kind: "filtered" })).toBe("filtered");
    expect(scopeKind({ scope: "all" })).toBe("all");
    expect(scopeKind({ scope: "own" })).toBe("own");
    expect(scopeKind({ scope: "none", kind: "none" })).toBe("none");
  });
  test("anything unknown degrades to none (render nothing)", () => {
    expect(scopeKind(undefined)).toBe("none");
    expect(scopeKind(null)).toBe("none");
    expect(scopeKind({ scope: "root" })).toBe("none");
    expect(scopeKind({ scope: "all", kind: "root" })).toBe("none");
  });
  test("the real API fixtures", () => {
    expect(scopeKind(fixture("scope_all"))).toBe("all");
    expect(scopeKind(fixture("scope_own"))).toBe("own");
    expect(scopeKind(fixture("scope_none"))).toBe("none");
    expect(scopeKind(fixture("scope_filtered"))).toBe("filtered");
  });
});

describe("overview access", () => {
  test("all and filtered viewers get the overview; own and none do not", () => {
    expect(hasOverview("all")).toBe(true);
    expect(hasOverview("filtered")).toBe(true);
    expect(hasOverview("own")).toBe(false);
    expect(hasOverview("none")).toBe(false);
  });
});

describe("scopeLabel (page header)", () => {
  test("shows the API's label for a filtered viewer", () => {
    expect(scopeLabel(fixture("scope_filtered"))).toBe("Your Majlis: Albany");
    expect(scopeLabel({ scope: "own", kind: "filtered", filter: { field: "region", value: "Northeast", label: "Your region: Northeast" } })).toBe("Your region: Northeast");
  });
  test("builds one when the label is missing, never crashes", () => {
    expect(scopeLabel({ scope: "own", kind: "filtered", filter: { field: "majlis", value: "Albany" } })).toBe("Your Majlis: Albany");
    expect(scopeLabel({ scope: "own", kind: "filtered", filter: { field: "department", value: "tabligh", label: "  " } })).toBe("Your department: tabligh");
    expect(scopeLabel({ scope: "own", kind: "filtered", filter: null })).toBe("Your unit");
  });
  test("nothing for everyone else", () => {
    for (const n of ["scope_all", "scope_own", "scope_none"]) expect(scopeLabel(fixture(n))).toBeNull();
    expect(scopeLabel(undefined)).toBeNull();
    expect(scopeLabel({ scope: "all", filter: { field: "majlis", value: "Albany", label: "Your Majlis: Albany" } })).toBeNull();
  });
});

describe("course tab for a filtered viewer (legacy scope own)", () => {
  const filtered = fixture("scope_filtered");
  test("shown on a course of their scope, hidden elsewhere", () => {
    expect(mkaCourseTabs("course_general", filtered.scope, filtered.courses).length).toBe(1);
    expect(mkaCourseTabs("course_other", filtered.scope, filtered.courses)).toEqual([]);
  });
});
