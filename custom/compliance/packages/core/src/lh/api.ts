import { LhClient } from "./client";
import type * as T from "./types";

/**
 * Typed wrappers over verified endpoints (see docs/lh-api-notes.md).
 * Methods marked WRITE issue POST/PUT/DELETE: never call them from the probe.
 */
export class LhApi {
  constructor(readonly client: LhClient) {}
  private get a() { return `/admin/${this.client.orgSlug}`; }

  // ---- reads --------------------------------------------------------------
  listCourses(page = 1, limit = 50, includeUnpublished = true) {
    return this.client.get<T.LhCourse[]>(
      `/courses/org_slug/${this.client.orgSlug}/page/${page}/limit/${limit}`,
      { include_unpublished: includeUnpublished });
  }
  countCourses() { return this.client.get<number>(`/courses/org_slug/${this.client.orgSlug}/count`); }
  getCourse(courseUuid: string) { return this.client.get<T.LhCourse>(`/courses/${courseUuid}`); }
  getCourseMeta(courseUuid: string) { return this.client.get<Record<string, unknown>>(`/courses/${courseUuid}/meta`, { with_unpublished_activities: true }); }
  listChaptersMeta(courseUuid: string) { return this.client.get<unknown>(`/chapters/course/${courseUuid}/meta`); }
  listCourseAssignments(courseUuid: string) { return this.client.get<unknown[]>(`/assignments/course/${courseUuid}`); }
  listAssignmentSubmissions(assignmentUuid: string, limit = 50, offset = 0) {
    return this.client.get<unknown[]>(`/assignments/${assignmentUuid}/submissions`, { limit, offset });
  }
  listUserGroups(orgId: number) { return this.client.get<T.UserGroup[]>(`/usergroups/org/${orgId}`); }
  listCertificationsForCourse(courseUuid: string) { return this.client.get<unknown[]>(`/certifications/course/${courseUuid}`); }

  getUserByEmail(email: string) { return this.client.get<T.LhUserRef>(`${this.a}/users/by-email/${encodeURIComponent(email)}`); }
  listCourseEnrollments(courseUuid: string, page = 1, limit = 100) {
    return this.client.get<T.EnrollmentItem[]>(`${this.a}/courses/${courseUuid}/enrollments`, { page, limit });
  }
  getUserEnrollments(userId: number) { return this.client.get<unknown>(`${this.a}/enrollments/${userId}`); }
  getAllUserProgress(userId: number) { return this.client.get<T.ProgressSummaryItem[]>(`${this.a}/progress/${userId}`); }
  getUserProgress(userId: number, courseUuid: string) { return this.client.get<T.UserProgress>(`${this.a}/progress/${userId}/${courseUuid}`); }
  getUserTrailDetail(userId: number) { return this.client.get<unknown>(`${this.a}/trails/${userId}`); }
  getUserCertificates(userId: number) { return this.client.get<unknown[]>(`${this.a}/certifications/${userId}`); }
  getCourseAnalytics(courseUuid: string) { return this.client.get<T.CourseAnalytics>(`${this.a}/courses/${courseUuid}/analytics`); }
  listUserGroupMembers(usergroupUuid: string) { return this.client.get<unknown[]>(`${this.a}/usergroups/${usergroupUuid}/members`); }

  // ---- WRITE (not used in milestone 0) -----------------------------------
  createCourse(orgId: number, input: T.CreateCourseInput) {
    const f = new FormData();
    f.set("name", input.name); f.set("description", input.description); f.set("about", input.about);
    f.set("public", String(input.public));
    if (input.learnings) f.set("learnings", input.learnings);
    if (input.tags) f.set("tags", input.tags);
    if (input.extra_metadata) f.set("extra_metadata", JSON.stringify(input.extra_metadata));
    return this.client.request<T.LhCourse>("POST", "/courses/", { query: { org_id: orgId }, form: f });
  }
  updateCourse(courseUuid: string, input: T.UpdateCourseInput) { return this.client.put<T.LhCourse>(`/courses/${courseUuid}`, input); }
  createChapter(input: T.CreateChapterInput) { return this.client.post<T.LhChapter>("/chapters/", input); }
  createActivity(input: T.CreateActivityInput) { return this.client.post<T.LhActivity>("/activities/", input); }
  updateActivity(activityUuid: string, input: T.UpdateActivityInput) { return this.client.put<T.LhActivity>(`/activities/${activityUuid}`, input); }
  createAssignment(input: T.CreateAssignmentInput) { return this.client.post<{ assignment_uuid: string }>("/assignments/", input); }
  createAssignmentTask(assignmentUuid: string, input: T.CreateAssignmentTaskInput) {
    return this.client.post<{ assignment_task_uuid: string }>(`/assignments/${assignmentUuid}/tasks`, input);
  }
  provisionUser(body: { email: string; username: string; first_name?: string; last_name?: string; role_id?: number }) {
    return this.client.post<T.LhUserRef>(`${this.a}/users`, body);
  }
  enroll(userId: number, courseUuid: string) { return this.client.post(`${this.a}/enrollments/${userId}/${courseUuid}`); }
  bulkEnroll(courseUuid: string, userIds: number[]) {
    return this.client.post<T.BulkEnrollResult>(`${this.a}/enrollments/bulk`, { course_uuid: courseUuid, user_ids: userIds });
  }
  createUserGroup(name: string, description = "") { return this.client.post<T.UserGroup>(`${this.a}/usergroups`, { name, description }); }
}
