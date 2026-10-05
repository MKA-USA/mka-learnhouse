import { DEPARTMENTS } from "../../core/src/seed/departments";
import type { LhApi } from "../../core/src/lh/api";
import { maxDay } from "./dates";
import { expectedContacts, recordAt, type FixtureWorld } from "./fixtures";
import type { AssignmentInfo, AssignmentKind, CourseRef, EnrollmentRow, SubmissionRow, SyncLhPort, TrailCourse } from "./sync";
import type { SelfCheckAnswers } from "./types";

// ---- fixture port: simulates LearnHouse from the synthetic world ----------------------------------------
export function fixtureCourses(): CourseRef[] {
  return [{ kind: "general", departmentSlug: "", courseUuid: "course_fx_general" },
    ...DEPARTMENTS.map((d) => ({ kind: "department" as const, departmentSlug: d.slug, courseUuid: `course_fx_${d.slug}` }))];
}

export function createFixturePort(world: FixtureWorld, day: string): SyncLhPort {
  const idByEmail = new Map(world.roster.map((e, i) => [e.email, i + 1]));
  const byId = new Map(world.roster.map((e) => [idByEmail.get(e.email)!, e]));
  const rec = (uid: number) => recordAt(world, byId.get(uid)!, day);
  const deptOf = (uuid: string) => uuid === "course_fx_general" ? null : uuid.replace("course_fx_", "");
  return {
    async listEnrollments(uuid) {
      const dept = deptOf(uuid);
      return world.roster.filter((e) => dept === null || e.departmentSlug === dept)
        .map((e): EnrollmentRow => ({ userId: idByEmail.get(e.email)!, email: e.email, enrolledAt: world.cycle.startsOn, status: "STATUS_IN_PROGRESS" }));
    },
    async getUserTrail(uid) {
      const r = rec(uid);
      const out: TrailCourse[] = [];
      for (const [k, c] of [["general", r.general], ["dept", r.department]] as const) {
        if (!c) continue;
        out.push({
          courseUuid: k === "general" ? "course_fx_general" : `course_fx_${r.departmentSlug}`, lessonsDone: c.lessonsDone, lessonsTotal: c.lessonsTotal,
          status: c.completedAt ? "STATUS_COMPLETED" : "STATUS_IN_PROGRESS", lastActivityAt: c.lastActivityAt ?? null, completedAt: c.completedAt ?? null,
        });
      }
      return out;
    },
    async listAssignments(uuid): Promise<AssignmentInfo[]> {
      const out: AssignmentInfo[] = [{ uuid: `${uuid}:signoff`, title: "Final sign-off", kind: "signoff" }];
      if (deptOf(uuid) !== null) out.push({ uuid: `${uuid}:contacts`, title: "Contact self-check", kind: "selfcheck" });
      out.push({ uuid: `${uuid}:quiz1`, title: "Knowledge quiz 1", kind: "quiz" }, { uuid: `${uuid}:quiz2`, title: "Knowledge quiz 2", kind: "quiz" });
      return out;
    },
    async listSubmissions(aUuid): Promise<SubmissionRow[]> {
      const [course, kind] = aUuid.split(":");
      const dept = deptOf(course!);
      const rows: SubmissionRow[] = [];
      const quizN = kind === "quiz1" ? 1 : kind === "quiz2" ? 2 : 0;
      for (const e of world.roster) {
        if (dept !== null && e.departmentSlug !== dept) continue;
        const uid = idByEmail.get(e.email)!, r = rec(uid), c = dept === null ? r.general : r.department;
        if (quizN) { const sc = c?.quizScores?.[quizN - 1]; if (sc !== undefined) rows.push({ userId: uid, status: "GRADED", grade: sc, percent: sc, attempt: 1, updatedAt: c?.lastActivityAt ?? null }); continue; }
        if (c?.attestedAt) rows.push({ userId: uid, status: "SUBMITTED", grade: null, percent: null, attempt: 1, updatedAt: c.attestedAt });
      }
      return rows;
    },
    async listSelfCheckAnswers(aUuid) {
      const dept = deptOf(aUuid.split(":")[0]!);
      const m = new Map<number, SelfCheckAnswers>();
      for (const e of world.roster) {
        if (e.departmentSlug !== dept) continue;
        const uid = idByEmail.get(e.email)!, r = rec(uid);
        if (r.selfCheck?.answered) {
          const exp = expectedContacts(e), wrong = "qaid.someone-else@example.invalid";
          const t = world.traj.get(e.id)!;
          m.set(uid, { majlis: exp.majlis, regionalQaid: t.wrongField === "regionalQaid" ? wrong : exp.regionalQaid, deptHead: t.wrongField === "deptHead" ? wrong : exp.deptHead });
        }
      }
      return m;
    },
  };
}

// ---- real adapter over core's LhApi (READ-ONLY calls only) -----------------------------------------------
export interface LhPortOptions {
  /** Map FORM answer keys (as authored by the course generator) to our fields. Keys are matched case-insensitively. */
  selfCheckFields?: { majlis: string; regionalQaid: string; deptHead: string };
  pageSize?: number;
}

export function classifyAssignment(title: string): AssignmentKind {
  const t = title.toLowerCase();
  if (/sign-?\s?off|attest|i confirm/.test(t)) return "signoff";
  if (/contact|self-?\s?check/.test(t)) return "selfcheck";
  if (/quiz|knowledge|check/.test(t)) return "quiz";
  return "other";
}

type Obj = Record<string, unknown>;
const asObj = (v: unknown): Obj => (v && typeof v === "object" ? (v as Obj) : {});
const str = (v: unknown): string | null => (typeof v === "string" && v ? v : null);
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

/** Field shapes for trails/enrollments are VERIFIED-LIVE; assignment submission shapes are SRC-only (see docs/analytics-source-notes.md). */
export function lhPortFromApi(api: LhApi, opts: LhPortOptions = {}): SyncLhPort {
  const page = opts.pageSize ?? 100;
  const f = opts.selfCheckFields ?? { majlis: "majlis", regionalQaid: "regional_qaid", deptHead: "dept_head" };
  return {
    async listEnrollments(uuid) {
      const out: EnrollmentRow[] = [];
      for (let p = 1; ; p++) {
        const rows = await api.listCourseEnrollments(uuid, p, page);
        for (const r of rows) out.push({ userId: r.user.id, email: String(r.user.email ?? ""), enrolledAt: r.enrolled_at, status: r.status, lastLoginAt: str(r.user["last_login_at"]) });
        if (rows.length < page) return out;
      }
    },
    async getUserTrail(uid) {
      const t = asObj(await api.getUserTrailDetail(uid));
      return (Array.isArray(t["courses"]) ? t["courses"] : []).map((c): TrailCourse => {
        const co = asObj(c);
        const acts = (Array.isArray(co["chapters"]) ? co["chapters"] : []).flatMap((ch) => (Array.isArray(asObj(ch)["activities"]) ? (asObj(ch)["activities"] as unknown[]) : []));
        const last = maxDay(...acts.map((a) => str(asObj(a)["completed_at"])));
        const status = str(co["status"]) ?? "";
        return {
          courseUuid: str(co["course_uuid"]) ?? "", lessonsDone: num(co["completed_activities"]) ?? 0, lessonsTotal: num(co["total_activities"]) ?? 0,
          status, lastActivityAt: last, completedAt: status === "STATUS_COMPLETED" ? last : null,
        };
      });
    },
    async listAssignments(uuid) {
      return (await api.listCourseAssignments(uuid)).map((a) => asObj(a)).filter((a) => str(a["assignment_uuid"]))
        .map((a) => ({ uuid: str(a["assignment_uuid"])!, title: str(a["title"]) ?? "", kind: classifyAssignment(str(a["title"]) ?? "") }));
    },
    async listSubmissions(aUuid) {
      const out: SubmissionRow[] = [];
      for (let off = 0; ; off += 500) {
        const rows = await api.listAssignmentSubmissions(aUuid, 500, off);
        for (const r of rows.map(asObj)) {
          const gd = asObj(r["grade_display"]);
          out.push({ userId: num(r["user_id"]) ?? -1, status: str(r["submission_status"]) ?? "", grade: num(r["grade"]), percent: num(gd["percentage"]), attempt: num(r["attempt_number"]) ?? 1, updatedAt: str(r["update_date"]) });
        }
        if (rows.length < 500) return out;
      }
    },
    async listSelfCheckAnswers(aUuid) {
      const m = new Map<number, SelfCheckAnswers>();
      try {
        const tasks = await api.client.get<unknown[]>(`/assignments/${aUuid}/tasks`);
        for (const t of tasks.map(asObj)) {
          const tu = str(t["assignment_task_uuid"]);
          if (!tu) continue;
          const subs = await api.client.get<unknown[]>(`/assignments/${aUuid}/tasks/${tu}/submissions`);
          for (const s of subs.map(asObj)) {
            const uid = num(s["user_id"]);
            if (uid === null) continue;
            const raw = asObj(s["task_submission"]);
            const lower = Object.fromEntries(Object.entries(asObj(raw["answers"] ?? raw)).map(([k, v]) => [k.toLowerCase(), v]));
            m.set(uid, { majlis: str(lower[f.majlis]) ?? undefined, regionalQaid: str(lower[f.regionalQaid]) ?? undefined, deptHead: str(lower[f.deptHead]) ?? undefined });
          }
        }
      } catch { /* shapes UNVERIFIED: no self-check data rather than a failed sync */ }
      return m;
    },
  };
}
