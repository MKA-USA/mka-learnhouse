import type { MapRow } from "./types";

export interface CycleCoursesFile {
  cycle: string; starts_on: string; deadline: string; deadline_on: string; generatedAt: string;
  courses: { kind: string; department: string; department_slug: string; course_uuid: string;
    activities: { key: string; kind: string; activity_uuid: string; assignment_uuid?: string; task_uuids?: Record<string, string> }[];
    signoff: { activity_uuid: string; assignment_uuid: string; task_uuids: Record<string, string> } | null;
    contact_check: { activity_uuid: string; assignment_uuid: string; task_uuids: Record<string, string> } | null }[];
}

/** Machine-readable cycle -> courses mapping (read by the in-LearnHouse analytics view). */
export function buildCycleCourses(cycle: string, startsOn: string, deadline: string, rows: MapRow[], now = new Date()): CycleCoursesFile {
  const pick = (r: MapRow, key: string) => {
    const a = r.structure.activities[key]; if (!a?.assignmentUuid) return null;
    return { activity_uuid: a.uuid, assignment_uuid: a.assignmentUuid, task_uuids: Object.fromEntries(Object.entries(a.tasks ?? {}).map(([k, v]) => [k, v.uuid])) };
  };
  return { cycle, starts_on: startsOn, deadline, deadline_on: deadline, generatedAt: now.toISOString(),
    courses: [...rows].sort((a, b) => (a.kind + a.departmentSlug).localeCompare(b.kind + b.departmentSlug)).map((r) => ({
      kind: r.kind, department: r.departmentSlug.replace(/-/g, "_"), department_slug: r.departmentSlug, course_uuid: r.lhCourseUuid,
      activities: Object.entries(r.structure.activities).map(([key, a]) => ({ key, kind: a.kind, activity_uuid: a.uuid, ...(a.assignmentUuid ? { assignment_uuid: a.assignmentUuid } : {}), ...(a.tasks ? { task_uuids: Object.fromEntries(Object.entries(a.tasks).map(([k, v]) => [k, v.uuid])) } : {}) })),
      signoff: pick(r, "signoff"), contact_check: pick(r, "contact-selfcheck") })) };
}
