/** Types follow apps/api pydantic models; see docs/lh-api-notes.md for sources. */
export interface LhCourse {
  id: number; org_id: number; course_uuid: string; name: string;
  description?: string | null; about?: string | null; learnings?: string | null; tags?: string | null;
  public: boolean; published: boolean; open_to_contributors: boolean;
  creation_date: string; update_date: string; extra_metadata?: Record<string, unknown> | null;
}
export interface LhActivity {
  id: number; org_id: number; course_id: number; activity_uuid: string; name: string;
  activity_type: ActivityType; activity_sub_type: ActivitySubType;
  content: Record<string, unknown>; published: boolean;
}
export interface LhChapter {
  id: number; chapter_uuid: string; name: string; description?: string | null;
  org_id: number; course_id: number; activities: LhActivity[];
}
export type ActivityType = "TYPE_VIDEO" | "TYPE_DOCUMENT" | "TYPE_DYNAMIC" | "TYPE_ASSIGNMENT" | "TYPE_CUSTOM" | "TYPE_SCORM";
export type ActivitySubType =
  | "SUBTYPE_DYNAMIC_PAGE" | "SUBTYPE_DYNAMIC_MARKDOWN" | "SUBTYPE_DYNAMIC_EMBED" | "SUBTYPE_DYNAMIC_RESOURCE"
  | "SUBTYPE_VIDEO_YOUTUBE" | "SUBTYPE_VIDEO_HOSTED" | "SUBTYPE_DOCUMENT_PDF" | "SUBTYPE_DOCUMENT_DOC"
  | "SUBTYPE_ASSIGNMENT_ANY" | "SUBTYPE_CUSTOM" | "SUBTYPE_SCORM_12" | "SUBTYPE_SCORM_2004";
export type AssignmentTaskType = "FILE_SUBMISSION" | "QUIZ" | "FORM" | "CODE" | "SHORT_ANSWER" | "NUMBER_ANSWER" | "CUSTOM" | "OTHER";

export interface CreateCourseInput {
  name: string; description: string; about: string; public: boolean;
  learnings?: string; tags?: string; extra_metadata?: Record<string, unknown>;
}
export interface UpdateCourseInput {
  name?: string; description?: string; about?: string; learnings?: string; tags?: string;
  public?: boolean; published?: boolean; extra_metadata?: Record<string, unknown>;
}
export interface CreateChapterInput { name: string; description?: string; org_id: number; course_id: number; }
export interface CreateActivityInput {
  chapter_id: number; name: string; activity_type?: ActivityType; activity_sub_type?: ActivitySubType;
  content?: Record<string, unknown>; published?: boolean; details?: Record<string, unknown>;
}
export interface UpdateActivityInput { name?: string; content?: Record<string, unknown>; published?: boolean; details?: Record<string, unknown>; }
export interface CreateAssignmentInput {
  title: string; description: string; grading_type: string; org_id: number; course_id: number;
  chapter_id: number; activity_id: number; due_date?: string | null; published?: boolean;
  auto_grading?: boolean; ungraded?: boolean; pass_threshold_percentage?: number | null;
}
export interface CreateAssignmentTaskInput {
  title: string; description: string; hint: string; assignment_type: AssignmentTaskType;
  contents: Record<string, unknown>; max_grade_value?: number;
}

export interface LhUserRef { id: number; user_uuid: string; username?: string; email?: string; [k: string]: unknown }
export interface EnrollmentItem { user: LhUserRef; enrolled_at: string; status: string }
export interface ProgressSummaryItem {
  course_uuid: string; course_name: string; status: string; total_activities: number;
  completed_activities: number; completion_percentage: number; enrolled_at: string;
}
export interface UserProgress {
  course_uuid: string; user_id: number; total_activities: number; completed_activities: number;
  completion_percentage: number; completed_activity_ids: number[];
}
export interface BulkEnrollResult { enrolled: number[]; already_enrolled: number[]; skipped: number[] }
export interface CourseAnalytics {
  course_uuid: string; enrollment_count: number; completed_count: number; in_progress_count: number;
  total_activities: number; average_completion_percentage: number; certificate_count: number;
}
export interface UserGroup { id: number; org_id: number; usergroup_uuid: string; name: string; description: string }
