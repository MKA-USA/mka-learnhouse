import type { LhApi } from "../lh/api";
import { LhHttpError } from "../lh/errors";

export interface AuthorAssignment { department: string; email: string; courseUuid: string }
export interface AuthorResult { department: string; status: "added" | "activated" | "unchanged" | "not_signed_in" | "skipped_creator" | "failed" | "planned_add" | "planned_activate"; detail?: string }

/**
 * Department Mohtamim as ACTIVE contributor of the department course.
 * Verified endpoints (apps/api/src): routers/courses/courses.py::api_get_course_contributors (GET /courses/{uuid}/contributors),
 * api_add_bulk_course_contributors (POST /courses/{uuid}/bulk-add-contributors, JSON body = list of usernames; creates CONTRIBUTOR/PENDING),
 * api_update_course_contributor (PUT /courses/{uuid}/contributors/{user_id}?authorship=&authorship_status=); enums in db/resource_authors.py.
 * Only org members are touched: the username is resolved through the org-scoped GET /admin/{org}/users/by-email lookup.
 */
export async function assignAuthors(api: LhApi, rows: AuthorAssignment[], apply: boolean): Promise<AuthorResult[]> {
  const out: AuthorResult[] = [];
  for (const r of rows) {
    let user: { id: number; username?: string };
    try { user = await api.getUserByEmail(r.email); }
    catch (e) { out.push({ department: r.department, status: e instanceof LhHttpError && e.status === 404 ? "not_signed_in" : "failed", detail: e instanceof LhHttpError ? `HTTP ${e.status}` : "error" }); continue; }
    try {
      const cur = (await api.getCourseContributors(r.courseUuid)).find((c) => c.user_id === user.id);
      if (cur?.authorship === "CREATOR") { out.push({ department: r.department, status: "skipped_creator" }); continue; }
      if (cur?.authorship_status === "ACTIVE") { out.push({ department: r.department, status: "unchanged" }); continue; }
      if (!apply) { out.push({ department: r.department, status: cur ? "planned_activate" : "planned_add" }); continue; }
      if (!cur) {
        if (!user.username) { out.push({ department: r.department, status: "failed", detail: "no username on user record" }); continue; }
        const res = await api.addContributors(r.courseUuid, [user.username]);
        if (res.failed?.length) { out.push({ department: r.department, status: "failed", detail: "bulk-add reported a failure" }); continue; }
      }
      await api.setContributor(r.courseUuid, user.id, cur?.authorship ?? "CONTRIBUTOR", "ACTIVE");
      out.push({ department: r.department, status: cur ? "activated" : "added" });
    } catch (e) { out.push({ department: r.department, status: "failed", detail: e instanceof LhHttpError ? `HTTP ${e.status}` : "error" }); }
  }
  return out;
}
