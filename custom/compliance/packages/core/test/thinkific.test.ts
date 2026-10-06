import { describe, expect, test } from "bun:test";
import { existsSync } from "node:fs";
import { DEFAULT_THINKIFIC_DIR, departmentCourses, foundationCourse, listTkCourses, seedPlansFromThinkific, scanContent } from "../src";

describe("content flags", () => {
  test("flags non-approved links, outside citations, dropped images; alislam is fine", () => {
    const f = scanContent({ text: "As narrated in Sahih Bukhari", links: ["https://www.alislam.org/x", "https://en.wikipedia.org/a", "https://docs.google.com/d"], imagesDropped: 2 });
    expect(f.map((x) => x.code).sort()).toEqual(["image-dropped", "non-approved-source-link", "operational-link", "outside-source-citation"]);
  });
});

describe.skipIf(!existsSync(DEFAULT_THINKIFIC_DIR))("real Thinkific export", () => {
  const courses = listTkCourses(DEFAULT_THINKIFIC_DIR);
  test("mapping by real title, not folder slug", () => {
    const dc = departmentCourses(courses);
    expect(dc.length).toBe(20);
    expect(dc.find((x) => x.course.id === 3255556)?.departmentSlug).toBe("aitmad");
    expect(dc.find((x) => x.course.id === 3345383)).toBeUndefined(); // template
    expect(foundationCourse(courses)?.id).toBe(3280094);
  });
  test("seed: 20 stale plans from Thinkific with docs", () => {
    const s = seedPlansFromThinkific(courses);
    expect(s.plans.length).toBe(20);
    expect(s.missing).toEqual([]);
    expect(s.plans.every((p) => p.stale && p.source === "thinkific-2025-26" && p.responsibilitiesDoc && p.okrsDoc)).toBe(true);
    expect(JSON.stringify(s.plans[0]!.okrsDoc)).not.toContain("font-family");
  });
});
