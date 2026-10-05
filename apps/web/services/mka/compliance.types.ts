/**
 * MKA native compliance analytics: API contract types.
 * Mirrors spec section 4 (docs/superpowers/specs/2026-10-04-mka-native-compliance-analytics-design.md).
 * The server is the only enforcement point; these types describe what it returns.
 *
 * Fields the frozen contract leaves open are marked `// (open)` and are always
 * read defensively by the UI (see README notes in the PR/report).
 */

export type ComplianceScope = 'all' | 'own' | 'none'

export type ComplianceStatus =
  | 'not_signed_in'
  | 'not_started'
  | 'in_progress'
  | 'completed'
  | 'attested'
  | 'overdue'

/** (open) the contract names RAG but not its literal values; W3 reference uses these. */
export type ComplianceRag = 'green' | 'amber' | 'red' | 'none'

export type CourseKind = 'general' | 'department'
export type LearnerLevel = 'national' | 'regional' | 'local'

export interface ComplianceCycle {
  id: number
  label: string
  starts_on: string
  deadline_on: string
}

export interface ComplianceCounts {
  expected: number
  not_signed_in: number
  not_started: number
  in_progress: number
  completed: number
  attested: number
  overdue: number
}

export interface ScopeCourse {
  course_uuid: string
  name: string
  kind: CourseKind
  /** Department SLUG (stable key, never display text); "" / null for the General course. */
  department: string | null
  department_name?: string | null
}

/** GET /scope */
export interface ScopeResponse {
  scope: ComplianceScope
  courses: ScopeCourse[]
  departments: string[]
  /** The cycle these courses belong to (extra; ignored). */
  cycle?: ComplianceCycle | null
  /** (open) not in the frozen contract: tolerated when present so the cycle picker can list cycles. */
  cycles?: ComplianceCycle[]
}

export interface RagFields {
  attested_pct: number
  rag: ComplianceRag
  score: number
  reasons: string[]
}

export interface DepartmentRow extends ComplianceCounts, RagFields {
  /** Slug (key). "" = national/executive group; display with `department_name`. */
  department: string
  department_name?: string | null
}

export interface CellRow extends ComplianceCounts {
  department: string
  department_name?: string | null
  region: string
  rag: ComplianceRag
  reasons: string[]
  attested_pct?: number // (open)
  score?: number // (open)
}

/** (open) "ranked departments/cells with reasons": shape not pinned by the contract. */
export interface AttentionItem {
  department: string
  department_name?: string | null
  region?: string | null
  rag: ComplianceRag
  score?: number
  reasons: string[]
  expected?: number
  attested_pct?: number
  overdue?: number
  not_started?: number
  not_signed_in?: number
}

/** GET /overview (scope all) */
export interface OverviewResponse {
  /** null when no cycle has been imported yet. */
  cycle: ComplianceCycle | null
  totals: ComplianceCounts
  departments: DepartmentRow[]
  cells: CellRow[]
  attention: AttentionItem[]
}

export interface BreakdownRow extends ComplianceCounts {
  rag?: ComplianceRag // (open)
  reasons?: string[] // (open)
}
export interface RegionRow extends BreakdownRow {
  region: string
}
export interface MajlisRow extends BreakdownRow {
  majlis: string
  region?: string | null // (open)
}
export interface LevelRow extends BreakdownRow {
  level: LearnerLevel
}

/** GET /courses/{course_uuid}/summary */
export interface CourseSummaryResponse {
  cycle: ComplianceCycle
  /** (open) `course:{…}` content not pinned; ScopeCourse-compatible. */
  course: Partial<ScopeCourse> & { course_uuid: string; name: string }
  totals: ComplianceCounts
  by_region: RegionRow[]
  by_majlis: MajlisRow[]
  by_level: LevelRow[]
  rag: ComplianceRag
  reasons: string[]
}

export interface ContactCheck {
  /** (open) answer JSON shape unverified server-side: render nothing from it. */
  answers?: unknown
  mismatch: boolean | null
}

export interface LearnerItem {
  /** Stable unique id of the list item (React key). Fallback key is built when an older API omits it. */
  id?: string | number
  email: string
  role_title: string
  person_name: string | null
  department: string
  department_name?: string | null
  level: LearnerLevel
  majlis: string | null
  region: string | null
  signed_in: boolean
  status: ComplianceStatus
  lessons_done: number
  lessons_total: number
  last_activity_at: string | null
  attested_at: string | null
  contact_check: ContactCheck
}

/** GET /courses/{course_uuid}/learners */
export interface LearnersResponse {
  cycle: ComplianceCycle
  items: LearnerItem[]
  total: number
}

export interface LearnerFilters {
  status?: ComplianceStatus | ''
  region?: string
  majlis?: string
  level?: LearnerLevel | ''
  q?: string
  page?: number
  page_size?: number
}
