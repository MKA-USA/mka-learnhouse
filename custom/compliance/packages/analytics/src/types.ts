export type Level = "national" | "region" | "majlis";
export type Stage = "not_started" | "in_progress" | "completed" | "attested";
/** `overdue` replaces the stage once past due and not attested; the stage is kept alongside. */
export type Status = Stage | "overdue";
export type Rag = "green" | "amber" | "red" | "none";

export interface CycleInfo { label: string; startsOn: string; deadlineOn: string }

export interface RosterEntry {
  id: string;
  departmentSlug: string;          // '' = executive (no department)
  level: Level;
  region: string;                  // '' for national
  majlis: string;                  // '' unless level = majlis
  roleTitle: string;
  email: string;
  personName?: string | null;
  appointedOn?: string | null;     // YYYY-MM-DD
}

export interface CourseProgress {
  enrolled: boolean;
  lessonsDone: number;
  lessonsTotal: number;
  completedAt?: string | null;
  attestedAt?: string | null;      // final sign-off submitted
  quizScores?: number[];           // percentages 0..100
  lastActivityAt?: string | null;
}

export interface SelfCheckAnswers { majlis?: string; regionalQaid?: string; deptHead?: string }
export interface SelfCheckExpected { majlis?: string; regionalQaid?: string; deptHead?: string }
export interface SelfCheckResult { answered: boolean; mismatches: string[] }

export interface LearnerRecord extends RosterEntry {
  general: CourseProgress | null;
  department: CourseProgress | null;
  selfCheck?: SelfCheckResult;
}

/** One learner scored as of a day. This is also the shape persisted in progress_snapshot. */
export interface ScoredLearner {
  rosterId: string;
  email: string;
  personName: string | null;
  departmentSlug: string;
  level: Level;
  region: string;
  majlis: string;
  roleTitle: string;
  appointedOn: string | null;
  stage: Stage;
  status: Status;
  overdue: boolean;
  lessonsDone: number;
  lessonsTotal: number;
  quizAvg: number | null;
  completedAt: string | null;
  attestedAt: string | null;
  lastActivityAt: string | null;
  dueOn: string;
  daysOverdue: number;
  /** 0..1: how much of the "attested" target this learner should have reached on the snapshot day. */
  expectedAttested: number;
  selfCheckAnswered: boolean;
  selfCheckMismatches: number;
}

export type Dimension = "department" | "region" | "majlis" | "level";
