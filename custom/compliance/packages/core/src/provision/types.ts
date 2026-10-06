export interface ActivityRecord { id: number; uuid: string; hash: string; chapterKey: string; kind: string; assignmentUuid?: string; tasks?: Record<string, { uuid: string; hash: string }> }
export interface CourseStructure {
  courseId: number; metaHash: string;
  chapters: Record<string, { id: number; uuid: string }>;
  activities: Record<string, ActivityRecord>;
}
export interface MapRow { cycleId: number; kind: string; departmentSlug: string; lhCourseUuid: string; lhCourseId: number | null; structure: CourseStructure; contentHash: string | null }
export interface IdmapEntry { sourceSystem: string; sourceKind: string; sourceId: string; lhKind: string; lhUuid: string; sourcePath?: string | null }

export interface MapStore {
  get(kind: string, departmentSlug: string): Promise<MapRow | null>;
  save(row: Omit<MapRow, "cycleId">): Promise<void>;
  addIdmap(e: IdmapEntry): Promise<void>;
}

export type Action = "create" | "update" | "unchanged" | "conflict";
export interface PlanItem { level: "course" | "chapter" | "activity" | "task"; key: string; action: Action; detail?: string }
export interface CoursePlan { courseKey: string; name: string; action: Action; counts: { chapters: number; pages: number; assignments: number; tasks: number; media: number }; items: PlanItem[]; flags: string[]; conflict?: string }
