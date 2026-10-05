import type { CourseProgress, CycleInfo, LearnerRecord } from "../src/types";

export const CYCLE: CycleInfo = { label: "2026-27", startsOn: "2026-11-01", deadlineOn: "2026-12-01" };
export const course = (p: Partial<CourseProgress> = {}): CourseProgress => ({ enrolled: true, lessonsDone: 0, lessonsTotal: 5, ...p });
export const rec = (p: Partial<LearnerRecord> = {}): LearnerRecord => ({
  id: "r1", departmentSlug: "tabligh", level: "majlis", region: "Northeast", majlis: "Albany", roleTitle: "Nazim Tabligh",
  email: "tabligh.albany@example.invalid", general: course({ lessonsTotal: 3 }), department: course(), ...p,
});
