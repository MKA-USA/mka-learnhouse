import { describe, expect, test } from "bun:test";
import { getTableConfig } from "drizzle-orm/pg-core";
import * as s from "../src/schema";
import { DEPARTMENTS } from "../src/seed/departments";

describe("department seed", () => {
  test("21 unique canonical departments", () => {
    expect(DEPARTMENTS.length).toBe(21);
    expect(new Set(DEPARTMENTS.map((d) => d.slug)).size).toBe(21);
    expect(DEPARTMENTS.every((d) => d.translation && d.name && d.mailboxPrefix)).toBe(true);
  });
  test("Aitmad maps to motamid mailbox; Nau Mubaeen reuses rishtanata", () => {
    expect(DEPARTMENTS.find((d) => d.slug === "aitmad")?.mailboxPrefix).toBe("motamid");
    expect(DEPARTMENTS.find((d) => d.slug === "nau-mubaeen")?.mailboxPrefix).toBe("rishtanata");
  });
  test("slugs are url-safe", () => {
    for (const d of DEPARTMENTS) expect(d.slug).toMatch(/^[a-z0-9]+(-[a-z0-9]+)*$/);
  });
});

describe("schema idempotency keys", () => {
  const uniques = (t: Parameters<typeof getTableConfig>[0]) => getTableConfig(t).uniqueConstraints.map((u) => u.columns.map((c) => c.name));
  test("person_role", () => expect(uniques(s.personRole)).toContainEqual(["cycle_id", "department_slug", "level", "region", "majlis"]));
  test("dept_plan", () => expect(uniques(s.deptPlan)).toContainEqual(["cycle_id", "department_slug", "level"]));
  test("course_map", () => expect(uniques(s.courseMap)).toContainEqual(["cycle_id", "kind", "department_slug"]));
  test("idmap", () => expect(uniques(s.idmap)).toContainEqual(["source_system", "source_kind", "source_id"]));
  test("enrollment_log", () => expect(uniques(s.enrollmentLog)).toContainEqual(["cycle_id", "lh_course_uuid", "learner_email"]));
  test("directory_override", () => expect(uniques(s.directoryOverride)).toContainEqual(["cycle_id", "department_slug", "level", "region", "majlis"]));
  test("cycle label unique", () => expect(getTableConfig(s.cycle).columns.find((c) => c.name === "label")?.isUnique).toBe(true));
  test("no analytics tables here", () => expect(Object.keys(s)).not.toContain("progressSnapshot"));
});
