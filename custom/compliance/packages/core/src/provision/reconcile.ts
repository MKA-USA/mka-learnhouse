import type { LhApi } from "../lh/api";
import { LhHttpError } from "../lh/errors";

export interface LearnerTarget { email: string; courseUuids: string[] }
export interface ReconcileOptions { apply: boolean; maxPerBulk?: number; log?: (s: string) => void }
export interface ReconcileResult {
  learners: number; notSignedUp: string[]; lookupFailed: number;
  perCourse: { courseUuid: string; wanted: number; alreadyEnrolled: number; toEnroll: number; enrolled: number; skippedNotInOrg: number }[];
  enrollmentRows: { email: string; courseUuid: string; userId: number | null; status: string }[];
}

/** All user ids currently enrolled in a course (paged read). */
export async function listEnrolledUserIds(api: LhApi, courseUuid: string): Promise<Set<number>> {
  const ids = new Set<number>();
  for (let page = 1; page < 200; page++) {
    const rows = await api.listCourseEnrollments(courseUuid, page, 100);
    for (const r of rows) ids.add(r.user.id);
    if (rows.length < 100) break;
  }
  return ids;
}

/**
 * Enroll only emails that already have a LearnHouse account (never provisions users).
 * Admin enroll needs an existing org member: services/admin/admin.py::enroll_user/_get_user_in_org.
 */
export async function reconcileEnrollments(api: LhApi, targets: LearnerTarget[], opts: ReconcileOptions): Promise<ReconcileResult> {
  const log = opts.log ?? (() => {});
  const res: ReconcileResult = { learners: targets.length, notSignedUp: [], lookupFailed: 0, perCourse: [], enrollmentRows: [] };
  const userIdByEmail = new Map<string, number>();
  for (const t of targets) {
    try {
      const u = await api.getUserByEmail(t.email);
      userIdByEmail.set(t.email, u.id);
    } catch (e) {
      if (e instanceof LhHttpError && e.status === 404) { res.notSignedUp.push(t.email); for (const c of t.courseUuids) res.enrollmentRows.push({ email: t.email, courseUuid: c, userId: null, status: "not_signed_up" }); }
      else { res.lookupFailed++; for (const c of t.courseUuids) res.enrollmentRows.push({ email: t.email, courseUuid: c, userId: null, status: "failed" }); }
    }
  }
  log(`lookups done: ${userIdByEmail.size} existing, ${res.notSignedUp.length} not signed up, ${res.lookupFailed} failed`);

  const courses = [...new Set(targets.flatMap((t) => t.courseUuids))];
  for (const course of courses) {
    const want = targets.filter((t) => t.courseUuids.includes(course) && userIdByEmail.has(t.email));
    const enrolled = await listEnrolledUserIds(api, course);
    const need = want.filter((t) => !enrolled.has(userIdByEmail.get(t.email)!));
    const row = { courseUuid: course, wanted: want.length, alreadyEnrolled: want.length - need.length, toEnroll: need.length, enrolled: 0, skippedNotInOrg: 0 };
    for (const t of want) if (enrolled.has(userIdByEmail.get(t.email)!)) res.enrollmentRows.push({ email: t.email, courseUuid: course, userId: userIdByEmail.get(t.email)!, status: "already_enrolled" });
    if (opts.apply && need.length) {
      const size = opts.maxPerBulk ?? 200;
      for (let i = 0; i < need.length; i += size) {
        const chunk = need.slice(i, i + size);
        const r = await api.bulkEnroll(course, chunk.map((t) => userIdByEmail.get(t.email)!));
        row.enrolled += r.enrolled.length; row.skippedNotInOrg += r.skipped.length;
        for (const t of chunk) { const id = userIdByEmail.get(t.email)!; res.enrollmentRows.push({ email: t.email, courseUuid: course, userId: id, status: r.enrolled.includes(id) ? "enrolled" : r.already_enrolled.includes(id) ? "already_enrolled" : "skipped_not_in_org" }); }
      }
    } else for (const t of need) res.enrollmentRows.push({ email: t.email, courseUuid: course, userId: userIdByEmail.get(t.email)!, status: "planned" });
    res.perCourse.push(row);
  }
  return res;
}
