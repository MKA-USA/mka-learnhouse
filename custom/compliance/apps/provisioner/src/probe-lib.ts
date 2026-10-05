import { LhApi, LhHttpError, LhNetworkError } from "@mka/compliance-core/lh";

export type Verdict = "OK" | "forbidden" | "unauthorized" | "not-found" | "plan-required" | "error" | "unknown";
export interface ProbeRow { endpoint: string; status: number | "-"; verdict: Verdict; note: string }

export function classify(e: unknown): { status: number | "-"; verdict: Verdict; note: string } {
  if (e instanceof LhHttpError) {
    const plan = e.status === 403 && /pro plan|plan or higher/i.test(e.detail ?? "");
    const verdict: Verdict = plan ? "plan-required" : e.status === 401 ? "unauthorized" : e.status === 403 ? "forbidden"
      : e.status === 404 ? "not-found" : "error";
    // detail may contain PII for some endpoints; only surface it for 403/401 permission text.
    const note = e.status === 403 || e.status === 401 ? (e.detail ?? "").replace(/\S+@\S+/g, "<email>").slice(0, 120) : "";
    return { status: e.status, verdict, note };
  }
  if (e instanceof LhNetworkError) return { status: "-", verdict: "error", note: "network error" };
  return { status: "-", verdict: "error", note: "unexpected error" };
}

export function count(x: unknown): string {
  return Array.isArray(x) ? `${x.length} item(s)` : typeof x === "number" ? `count=${x}` : x && typeof x === "object" ? "object" : "empty";
}

export function renderMatrix(rows: ProbeRow[]): string {
  const esc = (s: string) => s.replace(/\|/g, "/");
  return ["| Endpoint | HTTP | Result | Note |", "|---|---|---|---|",
    ...rows.map((r) => `| \`${esc(r.endpoint)}\` | ${r.status} | ${r.verdict} | ${esc(r.note)} |`)].join("\n");
}

/** Read-only probe. Only GET calls; samples ids stay in memory and are never reported. */
export async function runProbe(api: LhApi, candidates: string[]): Promise<{ rows: ProbeRow[]; orgSlug: string | null; orgId: number | null; stoppedReason?: string }> {
  const rows: ProbeRow[] = [];
  const step = async <T>(endpoint: string, fn: () => Promise<T>): Promise<T | undefined> => {
    try { const r = await fn(); rows.push({ endpoint, status: 200, verdict: "OK", note: count(r) }); return r; }
    catch (e) { rows.push({ endpoint, ...classify(e) }); return undefined; }
  };
  const client = api.client as unknown as { orgSlug: string };

  // 1. org discovery (token has no whoami; try candidate slugs against the count endpoint)
  let orgSlug: string | null = null;
  for (const slug of candidates) {
    client.orgSlug = slug;
    const r = await step(`GET /courses/org_slug/${slug === candidates[0] ? "{org_slug}" : "{candidate}"}/count`, () => api.countCourses());
    const last = rows[rows.length - 1]!;
    if (last.status === 401) return { rows, orgSlug: null, orgId: null, stoppedReason: "token rejected (HTTP 401)" };
    if (r !== undefined) { orgSlug = slug; break; }
  }
  if (!orgSlug) return { rows, orgSlug: null, orgId: null, stoppedReason: "no org slug accepted; set LH_ORG_SLUG" };
  client.orgSlug = orgSlug;

  // 2. courses
  const courses = await step("GET /courses/org_slug/{org}/page/1/limit/5?include_unpublished=true", () => api.listCourses(1, 5, true));
  const orgId = courses?.[0]?.org_id ?? null;
  const cu = courses?.[0]?.course_uuid;
  if (cu) {
    await step("GET /courses/{course_uuid}/meta", () => api.getCourseMeta(cu));
    await step("GET /chapters/course/{course_uuid}/meta", () => api.listChaptersMeta(cu));
    const asg = await step("GET /assignments/course/{course_uuid}", () => api.listCourseAssignments(cu)) as { assignment_uuid?: string }[] | undefined;
    const au = asg?.[0]?.assignment_uuid;
    if (au) await step("GET /assignments/{assignment_uuid}/submissions", () => api.listAssignmentSubmissions(au, 5));
    else rows.push({ endpoint: "GET /assignments/{assignment_uuid}/submissions", status: "-", verdict: "unknown", note: "no assignment to sample" });
    await step("GET /certifications/course/{course_uuid}", () => api.listCertificationsForCourse(cu));
    await step("GET /admin/{org}/courses/{course_uuid}/analytics", () => api.getCourseAnalytics(cu));
    const enr = await step("GET /admin/{org}/courses/{course_uuid}/enrollments", () => api.listCourseEnrollments(cu, 1, 5));
    const uid = enr?.[0]?.user?.id;
    if (uid !== undefined) {
      await step("GET /admin/{org}/progress/{user_id}", () => api.getAllUserProgress(uid));
      await step("GET /admin/{org}/progress/{user_id}/{course_uuid}", () => api.getUserProgress(uid, cu));
      await step("GET /admin/{org}/enrollments/{user_id}", () => api.getUserEnrollments(uid));
      await step("GET /admin/{org}/trails/{user_id}", () => api.getUserTrailDetail(uid));
      await step("GET /admin/{org}/certifications/{user_id}", () => api.getUserCertificates(uid));
    } else {
      for (const p of ["progress/{user_id}", "progress/{user_id}/{course_uuid}", "enrollments/{user_id}", "trails/{user_id}", "certifications/{user_id}"])
        rows.push({ endpoint: `GET /admin/{org}/${p}`, status: "-", verdict: "unknown", note: "no enrolled user to sample" });
    }
  } else {
    rows.push({ endpoint: "course-dependent endpoints", status: "-", verdict: "unknown", note: "no course to sample" });
  }

  // 3. usergroups
  if (orgId !== null) {
    const ug = await step("GET /usergroups/org/{org_id}", () => api.listUserGroups(orgId));
    const g = ug?.[0]?.usergroup_uuid;
    if (g) await step("GET /admin/{org}/usergroups/{usergroup_uuid}/members", () => api.listUserGroupMembers(g));
  } else {
    rows.push({ endpoint: "GET /usergroups/org/{org_id}", status: "-", verdict: "unknown", note: "org_id unknown (no courses)" });
  }

  // 4. users: no list endpoint is token-accessible; /users/* and /orgs/* reject tokens by design.
  rows.push({ endpoint: "GET /orgs/{org_id}/users (list users)", status: "-", verdict: "unknown", note: "not probed: router rejects API tokens (source-verified); use by-email lookups" });
  rows.push({ endpoint: "write scopes (courses/chapters/activities/assignments create)", status: "-", verdict: "unknown", note: "write scopes unverified; token rights not readable with a token; no write attempted" });
  return { rows, orgSlug, orgId };
}
