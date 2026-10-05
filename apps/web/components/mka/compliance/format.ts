/**
 * Pure helpers for the MKA compliance UI (no React, no DOM): unit-tested in
 * tests/mka-compliance-format.test.mjs.
 */
import type {
  AttentionItem,
  CellRow,
  ComplianceCounts,
  ComplianceRag,
  ComplianceStatus,
  DepartmentRow,
  LearnerFilters,
} from '@services/mka/compliance.types'

/** Fixed "today" for the mock layer so fixtures and screenshots are deterministic. */
export const MOCK_TODAY = '2026-10-20'

// ---- status / RAG vocabulary ------------------------------------------------

/** Chase order: the people who most need a nudge first. */
export const STATUS_ORDER: ComplianceStatus[] = [
  'overdue',
  'not_signed_in',
  'not_started',
  'in_progress',
  'completed',
  'attested',
]

export type Tone = 'red' | 'amber' | 'slate' | 'blue' | 'teal' | 'green'

export const STATUS_META: Record<ComplianceStatus, { label: string; hint: string; tone: Tone }> = {
  overdue: { label: 'Overdue', hint: 'Past their due date and not attested', tone: 'red' },
  not_signed_in: { label: 'Not signed in', hint: 'Has never signed in to LearnHouse', tone: 'slate' },
  not_started: { label: 'Not started', hint: 'Signed in but has not begun the course', tone: 'amber' },
  in_progress: { label: 'In progress', hint: 'Some lessons done', tone: 'blue' },
  completed: { label: 'Completed', hint: 'All lessons done, not yet attested', tone: 'teal' },
  attested: { label: 'Attested', hint: 'Completed and signed off', tone: 'green' },
}

export const RAG_META: Record<ComplianceRag, { label: string; short: string; severity: number }> = {
  red: { label: 'Needs attention', short: 'Red', severity: 3 },
  amber: { label: 'Watch', short: 'Amber', severity: 2 },
  green: { label: 'On track', short: 'Green', severity: 1 },
  none: { label: 'No data', short: 'None', severity: 0 },
}

export const isStatus = (v: unknown): v is ComplianceStatus =>
  typeof v === 'string' && Object.prototype.hasOwnProperty.call(STATUS_META, v)

export const isRag = (v: unknown): v is ComplianceRag =>
  typeof v === 'string' && Object.prototype.hasOwnProperty.call(RAG_META, v)

/** Unknown server values degrade to 'none' instead of crashing the page. */
export const safeRag = (v: unknown): ComplianceRag => (isRag(v) ? v : 'none')

export const ragSeverity = (r: ComplianceRag): number => RAG_META[safeRag(r)].severity

// ---- numbers ------------------------------------------------------------------

export function pctOf(part: number, whole: number): number {
  if (!whole || whole <= 0 || !Number.isFinite(part)) return 0
  return Math.max(0, Math.min(100, (part / whole) * 100))
}

/** "42%" ; whole numbers only. */
export function fmtPct(p: number): string {
  return `${Math.round(p)}%`
}

export const attestedPct = (c: Pick<ComplianceCounts, 'attested' | 'expected'>): number =>
  pctOf(c.attested, c.expected)

/** People who need a nudge now: overdue + never signed in + not started. */
export function chaseTotal(c: ComplianceCounts): number {
  return c.overdue + c.not_signed_in + c.not_started
}

export const SEGMENT_ORDER: ComplianceStatus[] = [
  'attested',
  'completed',
  'in_progress',
  'not_started',
  'not_signed_in',
  'overdue',
]

export interface Segment {
  status: ComplianceStatus
  count: number
  pct: number
}

/** Stacked-bar segments, fixed order, zero segments dropped. */
export function statusSegments(c: ComplianceCounts): Segment[] {
  return SEGMENT_ORDER.map((status) => ({
    status,
    count: c[status],
    pct: pctOf(c[status], c.expected),
  })).filter((s) => s.count > 0)
}

/** Screen-reader text for a stacked bar. */
export function segmentsLabel(c: ComplianceCounts): string {
  if (!c.expected) return 'No expected learners'
  return statusSegments(c)
    .map((s) => `${STATUS_META[s.status].label} ${s.count}`)
    .concat([`of ${c.expected} expected`])
    .join(', ')
}

// ---- heatmap ----------------------------------------------------------------------

export interface HeatmapRow {
  /** Slug: the key. */
  department: string
  /** Display name. */
  label: string
  summary: DepartmentRow | null
  cells: Record<string, CellRow>
}

export interface Heatmap {
  regions: string[]
  rows: HeatmapRow[]
}

/**
 * Department x region grid. Rows: worst department first (RAG then score), so
 * the eye lands on who to chase. Columns: regions A-Z (stable, learnable).
 */
export function buildHeatmap(departments: DepartmentRow[], cells: CellRow[]): Heatmap {
  const regionSet = new Set<string>()
  const byDept = new Map<string, HeatmapRow>()
  for (const d of departments) byDept.set(d.department, { department: d.department, label: deptLabel(d.department, d.department_name), summary: d, cells: {} })
  for (const c of cells) {
    // The API sends region: null for rows with no recorded region: normalise to '' (never a null map key / sort operand).
    const region = nz(c.region) ?? ''
    regionSet.add(region)
    let row = byDept.get(c.department)
    if (!row) {
      row = { department: c.department, label: deptLabel(c.department, c.department_name), summary: null, cells: {} }
      byDept.set(c.department, row)
    }
    row.cells[region] = c
  }
  const rows = [...byDept.values()].sort(
    (a, b) =>
      ragSeverity(b.summary?.rag ?? 'none') - ragSeverity(a.summary?.rag ?? 'none') ||
      (b.summary?.score ?? 0) - (a.summary?.score ?? 0) ||
      a.label.localeCompare(b.label),
  )
  return { regions: [...regionSet].sort((a, b) => a.localeCompare(b)), rows }
}

/** Accessible label for one heatmap cell. */
export function cellLabel(department: string, region: string, c: CellRow | undefined): string {
  region = nz(region) ?? 'no region recorded'
  if (!c || !c.expected) return `${department}, ${region}: no expected learners`
  return `${department}, ${region}: ${RAG_META[safeRag(c.rag)].label}, ${fmtPct(attestedPct(c))} attested of ${c.expected}${
    c.overdue ? `, ${c.overdue} overdue` : ''
  }`
}

export function attentionTitle(a: AttentionItem): string {
  const d = deptLabel(a.department, a.department_name)
  return nz(a.region) ? `${d} \u00b7 ${a.region}` : d
}

// ---- dates ---------------------------------------------------------------------------

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** ISO date or datetime -> "Oct 20, 2026" (UTC, so SSR and client agree). "-" when unparsable. */
export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00Z` : iso)
  if (Number.isNaN(d.getTime())) return '—'
  return `${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}, ${d.getUTCFullYear()}`
}

/** Whole days from `today` to `deadline` (negative when past). Both ISO dates. */
export function daysUntil(deadlineIso: string, todayIso: string): number {
  const a = Date.parse(`${deadlineIso.slice(0, 10)}T00:00:00Z`)
  const b = Date.parse(`${todayIso.slice(0, 10)}T00:00:00Z`)
  if (Number.isNaN(a) || Number.isNaN(b)) return 0
  return Math.round((a - b) / 86_400_000)
}

export function deadlineLabel(deadlineIso: string, todayIso: string): string {
  const n = daysUntil(deadlineIso, todayIso)
  if (n === 0) return 'Due today'
  if (n > 0) return `${n} day${n === 1 ? '' : 's'} left`
  return `${-n} day${n === -1 ? '' : 's'} past deadline`
}

// ---- URLs / query strings ----------------------------------------------------------

/** URLSearchParams from a flat record; drops undefined / null / empty values. */
export function buildQuery(params: Record<string, string | number | null | undefined>): string {
  const sp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === '') continue
    sp.set(k, String(v))
  }
  return sp.toString()
}

export function learnerQuery(f: LearnerFilters, cycleId?: number | null, orgId?: number | null): string {
  return buildQuery({
    org_id: orgId ?? undefined,
    cycle_id: cycleId ?? undefined,
    status: f.status,
    region: f.region,
    majlis: f.majlis,
    level: f.level,
    q: f.q?.trim(),
    page: f.page,
    page_size: f.page_size,
  })
}

/** Course uuids appear both as `course_<uuid>` and bare `<uuid>`. */
export const bareCourseUuid = (u: string): string => u.replace(/^course_/, '')

export const sameCourse = (a: string, b: string): boolean => bareCourseUuid(a) === bareCourseUuid(b)

/** Only the fixed, sanitised name is ever used for the download: never server- or user-supplied text. */
export function chaseListFilename(courseName: string, todayIso: string): string {
  const slug = courseName
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 48)
  return `chase-list-${slug || 'course'}-${todayIso.slice(0, 10)}.csv`
}

/** CSV cell escape with spreadsheet-formula neutralisation (used by the mock CSV; the API must do the same). */
export function csvCell(v: unknown): string {
  let s = v === null || v === undefined ? '' : String(v)
  if (/^[=+\-@\t\r]/.test(s)) s = `'${s}`
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}

export function lessonProgress(done: number, total: number): { pct: number; label: string } {
  return { pct: pctOf(done, total), label: total > 0 ? `${done}/${total}` : '—' }
}

/** Course a department row links to: its department course; the national/executive group ("" slug) links to the General course. */
export function courseForDepartment<C extends { kind: string; department: string | null }>(courses: C[], department: string): C | undefined {
  if (!nz(department)) return courses.find((c) => c.kind === 'general')
  return courses.find((c) => c.kind === 'department' && c.department === department)
}

// ---- API-shape tolerance (slug vs name, "" vs null) -----------------------------------------

export const NATIONAL_LABEL = 'National leadership'

/** "" / whitespace / null -> null. The API may send either for an empty optional field. */
export const nz = (v: string | null | undefined): string | null => (v && v.trim() ? v : null)

const titleCase = (slug: string) =>
  slug
    .split(/[_\-\s]+/)
    .filter(Boolean)
    .map((w) => w[0].toUpperCase() + w.slice(1))
    .join(' ')

/** Display name for a department: `department_name`, else a prettified slug, else the national group label. Never the raw slug. */
export function deptLabel(department: string | null | undefined, name?: string | null): string {
  return nz(name) ?? (nz(department) ? titleCase(department as string) : NATIONAL_LABEL)
}

/** Stable React key for a learner row: server `id`, else a composite incl. level and Majlis. */
export function learnerKey(l: {
  id?: string | number
  email: string
  role_title: string | null
  department: string
  level: string
  majlis?: string | null
}): string {
  return l.id !== undefined && l.id !== null ? `id:${l.id}` : [l.email, l.role_title ?? '', l.department, l.level, l.majlis ?? ''].join('|')
}

/** Notice for a capped CSV (`X-Truncated: true`; `X-Row-Limit` when sent), else null. */
export function truncationNotice(truncated: string | null | undefined, limit: string | null | undefined): string | null {
  if (truncated?.toLowerCase() !== 'true') return null
  const n = Number(limit)
  const rows = Number.isFinite(n) && n > 0 ? n : 5000
  return `List truncated at ${rows.toLocaleString('en-US')} rows. Narrow the filters to get the rest.`
}
