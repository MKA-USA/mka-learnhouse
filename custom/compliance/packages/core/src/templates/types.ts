import type { PMDoc } from "../content/pm";

export type TaskSpec =
  | { key: string; type: "QUIZ"; title: string; description: string; hint: string; contents: { grading_mode: "ALL_OR_NOTHING"; questions: QuizQuestion[] } }
  | { key: string; type: "FORM"; title: string; description: string; hint: string; contents: { questions: FormQuestion[] } };
export interface QuizQuestion { questionUUID: string; questionText: string; response_type: "single" | "multiple"; options: { optionUUID: string; text: string; fileID: string; type: "text"; assigned_right_answer: boolean }[] }
export interface FormQuestion { questionUUID: string; questionText: string; blanks: { blankUUID: string; placeholder: string; correctAnswer: string; hint?: string }[] }

export interface SourceRef { system: "thinkific"; courseId: number; chapterId?: string; lessonId?: string; path?: string }

export type ActivitySpec =
  | { kind: "page"; key: string; name: string; doc: PMDoc; source?: SourceRef }
  | { kind: "assignment"; key: string; name: string; title: string; description: string; ungraded: boolean; passThreshold?: number; tasks: TaskSpec[]; source?: SourceRef }
  | { kind: "video"; key: string; name: string; file: { rel: string; abs: string; size: number }; source?: SourceRef }
  | { kind: "pdf"; key: string; name: string; file: { rel: string; abs: string; size: number }; source?: SourceRef };

export interface ChapterSpec { key: string; name: string; description: string; source?: SourceRef; activities: ActivitySpec[] }
export interface CourseSpec {
  key: string; kind: "general" | "department"; departmentSlug: string; cycle: string;
  name: string; description: string; about: string; learnings: string; tags: string;
  chapters: ChapterSpec[]; flags: string[];
}

export interface PlanInput { departmentSlug: string; level: string; responsibilitiesDoc: PMDoc | null; okrsDoc: PMDoc | null; resourcesDoc: PMDoc | null; stale: boolean; source: string }
