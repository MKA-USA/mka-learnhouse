/**
 * Deterministic MOCK layer for the compliance UI (dev / screenshots only).
 * Enabled by NEXT_PUBLIC_MKA_COMPLIANCE_MOCK=1 and never in a production build
 * (see compliance.ts). ~1,090 synthetic expected learners across 22 courses
 * (1 General + 21 departments), uneven completion, deliberate problem
 * departments, a never-signed-in cohort and contact-check mismatches.
 *
 * Everything here is synthetic: `@example.invalid` mailboxes, invented names.
 * Scoring mirrors the W3 reference (shortfall vs a linear expected curve +
 * overdue + contact mismatches) purely so the UI can be exercised; the real
 * API owns scoring.
 */
import { csvCell, MOCK_TODAY } from '@components/mka/compliance/format'
import type {
  AttentionItem,
  CellRow,
  ComplianceCounts,
  ComplianceCycle,
  ComplianceRag,
  ComplianceScope,
  ComplianceStatus,
  CourseKind,
  CourseSummaryResponse,
  DepartmentRow,
  LearnerFilters,
  LearnerItem,
  LearnerLevel,
  LearnersResponse,
  MajlisRow,
  OverviewResponse,
  RegionRow,
  RemindResponse,
  ScopeCourse,
  ScopeResponse,
} from './compliance.types'

const CYCLES: ComplianceCycle[] = [
  { id: 2, label: '2026-27', starts_on: '2026-09-01', deadline_on: '2026-11-15' },
  { id: 1, label: '2025-26', starts_on: '2025-09-01', deadline_on: '2025-11-15' },
]

export class MockApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

// ---- deterministic randomness -------------------------------------------------------
function hash(s: string): number {
  let h = 2166136261
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return h >>> 0
}
function rng(seed: number) {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6d2b79f5) >>> 0
    let t = a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}
/** Department slug as the API sends it (underscored), distinct from its display name. */
const dk = (name: string) => name.toLowerCase().replace(/[^a-z0-9]+/g, '_')
const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, '')
const dayMs = 86_400_000
const toMs = (iso: string) => Date.parse(`${iso}T00:00:00Z`)
const isoDay = (ms: number) => new Date(ms).toISOString().slice(0, 10)

// ---- org structure ------------------------------------------------------------------
const MAJLIS_REGION: Record<string, string> = {
  Baltimore: 'East', 'Central Jersey': 'East', Harrisburg: 'East', 'North Jersey': 'East', Philadelphia: 'East', Willingboro: 'East',
  Cleveland: 'Great Lakes', Columbus: 'Great Lakes', Dayton: 'Great Lakes', Detroit: 'Great Lakes', Indiana: 'Great Lakes', Kentucky: 'Great Lakes',
  Austin: 'Gulf', Dallas: 'Gulf', 'Fort Worth': 'Gulf', Houston: 'Gulf', Tulsa: 'Gulf',
  Chicago: 'Midwest', 'Kansas City': 'Midwest', Milwaukee: 'Midwest', Minnesota: 'Midwest', Oshkosh: 'Midwest', 'Saint Louis': 'Midwest', Zion: 'Midwest',
  Bronx: 'New York Metro', Brooklyn: 'New York Metro', 'Long Island': 'New York Metro', Queens: 'New York Metro',
  Albany: 'Northeast', Boston: 'Northeast', Connecticut: 'Northeast', Rochester: 'Northeast', 'Syracuse-Binghamton': 'Northeast',
  'Bay Point': 'Northwest', Portland: 'Northwest', Sacramento: 'Northwest', Seattle: 'Northwest', 'Silicon Valley': 'Northwest',
  Atlanta: 'Southeast', Charlotte: 'Southeast', Miami: 'Southeast', Orlando: 'Southeast', Tennessee: 'Southeast',
  'Las Vegas': 'Southwest', 'Los Angeles': 'Southwest', Phoenix: 'Southwest', Tucson: 'Southwest',
  'North Virginia': 'Virginia', 'South Virginia': 'Virginia', Richmond: 'Virginia', RTP: 'Virginia',
}
const REGIONS = [...new Set(Object.values(MAJLIS_REGION))].sort()

const DEPARTMENTS = [
  'Aitmad', 'Amoomi', 'Amoor-e-Tuluba', 'Atfal', 'Ishaat', 'Khidmat-e-Khalq', 'Maal', 'Mohasib', 'Nau Mubaeen', 'Rishta Nata',
  'Sanat-o-Tijarat', 'Sehat-e-Jismani', 'Tabligh', 'Tahrik-e-Jadid', 'Tajneed', 'Taleem', 'Tarbiyyat', 'Waqar-e-Amal', 'Waqf-e-Nau',
  'Wasiyyat', 'New Immigrants',
]

interface Profile { neverStart: number; pace: [number, number]; startDelay: number; stall: number; noAttest: number; mismatch: number; unsigned: number }
const BASE: Profile = { neverStart: 0.05, pace: [0.2, 0.8], startDelay: 16, stall: 0.05, noAttest: 0.1, mismatch: 0.04, unsigned: 0.04 }
// The deliberate problems, so every RAG state and reason wording appears.
const PROFILES: Record<string, Partial<Profile>> = {
  Tarbiyyat: { neverStart: 0.55, startDelay: 30, unsigned: 0.12 },
  'Waqf-e-Nau': { stall: 0.6 },
  Ishaat: { mismatch: 0.3 },
  'New Immigrants': { noAttest: 0.55 },
  'Nau Mubaeen': { unsigned: 0.3, neverStart: 0.3 },
  Tajneed: { neverStart: 0.01, pace: [0.5, 0.9], startDelay: 5, noAttest: 0.02, unsigned: 0.01 },
  Taleem: { neverStart: 0.01, pace: [0.45, 0.85], startDelay: 6, noAttest: 0.03, unsigned: 0.01 },
}
const REGION_FIX: { dept: string; regions: string[]; neverStart: number }[] = [
  { dept: 'Maal', regions: ['Gulf', 'Southwest'], neverStart: 0.85 },
]

// ---- synthetic roster + progress --------------------------------------------------------
const GENERAL_LESSONS = 7
const FIRST = ['Amir', 'Bilal', 'Daniyal', 'Faisal', 'Hamza', 'Idris', 'Junaid', 'Khalid', 'Luqman', 'Mansoor', 'Nadeem', 'Omar', 'Qasim', 'Rashid', 'Salman', 'Tahir', 'Umar', 'Waleed', 'Yusuf', 'Zahid']
const LAST = ['Exampleton', 'Sampleman', 'Testani', 'Mockwood', 'Fixtureson', 'Demoud', 'Placeholder', 'Syntheti', 'Specimen', 'Dummer']

interface CourseState { done: number; total: number; attestedAt: string | null; lastActivityAt: string | null; status: ComplianceStatus }
interface Person {
  id: string
  email: string
  department: string
  level: LearnerLevel
  region: string | null
  majlis: string | null
  roleTitle: string
  name: string | null
  signedIn: boolean
  dueOn: string
  general: CourseState
  dept: CourseState
  overall: ComplianceStatus
  mismatch: boolean | null
}

function courseStatus(signedIn: boolean, done: number, total: number, attested: boolean, overdue: boolean): ComplianceStatus {
  if (!signedIn) return 'not_signed_in'
  if (attested) return 'attested'
  if (overdue) return 'overdue'
  if (done >= total) return 'completed'
  return done > 0 ? 'in_progress' : 'not_started'
}

function buildWorld() {
  const cycle = CYCLES[0]
  const startMs = toMs(cycle.starts_on)
  const asOfMs = toMs(MOCK_TODAY)
  const people: Person[] = []

  for (const department of DEPARTMENTS) {
    const slots: { level: LearnerLevel; region: string | null; majlis: string | null; role: string }[] = []
    slots.push({ level: 'national', region: null, majlis: null, role: `Mohtamim ${department}` })
    for (const region of REGIONS) slots.push({ level: 'regional', region, majlis: null, role: `Regional Nazim ${department}` })
    for (const [majlis, region] of Object.entries(MAJLIS_REGION)) {
      if (hash(`${department}:${majlis}`) % 100 < 73) slots.push({ level: 'local', region, majlis, role: `Nazim ${department}` })
    }
    const deptLessons = 5 + (hash(department) % 4)
    for (const s of slots) {
      const id = `${slug(department)}.${slug(s.majlis ?? s.region ?? 'national')}`
      const r = rng(hash(`mock:${id}`))
      const p: Profile = { ...BASE, ...(PROFILES[department] ?? {}) }
      for (const fx of REGION_FIX) if (fx.dept === department && s.region && fx.regions.includes(s.region)) p.neverStart = fx.neverStart

      const signedIn = r() >= p.unsigned
      const appointed = s.level === 'local' && r() < 0.08 ? toMs('2026-08-05') + Math.floor(r() * 45) * dayMs : null
      const dueMs = appointed !== null ? appointed + 30 * dayMs : toMs(cycle.deadline_on)
      const never = !signedIn || r() < p.neverStart
      const start = (appointed !== null ? Math.max(appointed, startMs) : startMs) + Math.floor(r() * p.startDelay) * dayMs
      const pace = p.pace[0] + r() * (p.pace[1] - p.pace[0])
      const total = GENERAL_LESSONS + deptLessons
      const cap = r() < p.stall ? Math.max(1, Math.floor(total * (0.35 + r() * 0.4))) : total
      const elapsed = (asOfMs - start) / dayMs
      const done = never || elapsed < 0 ? 0 : Math.min(cap, total, Math.floor(elapsed * pace) + 1)
      const gDone = Math.min(done, GENERAL_LESSONS)
      const dDone = Math.max(0, done - GENERAL_LESSONS)
      const attGeneral = r() >= p.noAttest * 0.5
      const attDept = r() >= p.noAttest
      const attestedAt = (n: number) => isoDay(asOfMs - (1 + Math.floor(r() * (3 + n))) * dayMs)
      const gAtt = gDone >= GENERAL_LESSONS && attGeneral ? attestedAt(8) : null
      const dAtt = dDone >= deptLessons && attDept ? attestedAt(4) : null
      const overdue = dueMs < asOfMs
      const lastActivity = (d: number, att: string | null) =>
        d > 0 ? att ?? isoDay(Math.min(asOfMs, start + Math.ceil(d / pace) * dayMs)) : null
      const general: CourseState = {
        done: gDone,
        total: GENERAL_LESSONS,
        attestedAt: gAtt,
        lastActivityAt: lastActivity(gDone, gAtt),
        status: courseStatus(signedIn, gDone, GENERAL_LESSONS, gAtt !== null, overdue),
      }
      const dept: CourseState = {
        done: dDone,
        total: deptLessons,
        attestedAt: dAtt,
        lastActivityAt: lastActivity(dDone, dAtt),
        status: courseStatus(signedIn, dDone, deptLessons, dAtt !== null, overdue),
      }
      let overall: ComplianceStatus
      if (!signedIn) overall = 'not_signed_in'
      else if (gAtt && dAtt) overall = 'attested'
      else if (overdue) overall = 'overdue'
      else if (done >= total) overall = 'completed'
      else overall = done > 0 ? 'in_progress' : 'not_started'
      const mismatch = s.level === 'local' && dDone >= deptLessons ? r() < p.mismatch : null
      const named = signedIn || r() < 0.4
      people.push({
        id,
        email: `${slug(department)}.${slug(s.majlis ?? s.region ?? 'national')}@example.invalid`,
        department,
        level: s.level,
        region: s.region,
        majlis: s.majlis,
        roleTitle: s.role,
        name: named ? `${FIRST[hash(id) % FIRST.length]} ${LAST[hash(id + 'x') % LAST.length]}` : null,
        signedIn,
        dueOn: isoDay(dueMs),
        general,
        dept,
        overall,
        mismatch,
      })
    }
  }
  return { cycle, people }
}

let _world: ReturnType<typeof buildWorld> | null = null
const world = () => (_world ??= buildWorld())

// ---- courses ----------------------------------------------------------------------------------
export const MOCK_GENERAL_UUID = 'course_mock-general'
const deptUuid = (d: string) => `course_mock-${slug(d)}`

export const MOCK_COURSES: ScopeCourse[] = [
  { course_uuid: MOCK_GENERAL_UUID, name: 'MKA Officeholder Orientation (General)', kind: 'general', department: null, department_name: null },
  ...DEPARTMENTS.map((d): ScopeCourse => ({ course_uuid: deptUuid(d), name: `${d} Officeholder Course`, kind: 'department', department: dk(d), department_name: d })),
]
const OWN_DEPARTMENTS = ['Tarbiyyat', 'Tabligh']

// ---- aggregation + scoring --------------------------------------------------------------------
const ZERO: ComplianceCounts = { expected: 0, not_signed_in: 0, not_started: 0, in_progress: 0, completed: 0, attested: 0, overdue: 0 }
function tally(statuses: ComplianceStatus[]): ComplianceCounts {
  const c = { ...ZERO }
  for (const s of statuses) {
    c.expected++
    c[s]++
  }
  return c
}

function score(c: ComplianceCounts, mismatches: number): { rag: ComplianceRag; score: number; reasons: string[]; attested_pct: number } {
  const n = c.expected
  if (n === 0) return { rag: 'none', score: 0, reasons: [], attested_pct: 0 }
  const cy = CYCLES[0]
  const expectedPct = Math.min(1, Math.max(0, (toMs(MOCK_TODAY) - toMs(cy.starts_on)) / (toMs(cy.deadline_on) - toMs(cy.starts_on))))
  const actual = c.attested / n
  const shortfall = Math.max(0, expectedPct - actual)
  const overdueRate = c.overdue / n
  const mismatchRate = mismatches / n
  const sc = Math.round(100 * (0.6 * shortfall + 0.25 * overdueRate + 0.15 * Math.min(1, 3 * mismatchRate)) * 10) / 10
  let rag: ComplianceRag = sc >= 25 ? 'red' : sc >= 10 ? 'amber' : 'green'
  if (c.overdue > 0 && overdueRate >= 0.2) rag = 'red'
  else if (rag === 'green' && mismatchRate >= 0.1) rag = 'amber'
  const reasons: string[] = []
  if (c.overdue > 0) reasons.push(`${c.overdue} of ${n} overdue`)
  if (c.not_signed_in > 0) reasons.push(`${c.not_signed_in} of ${n} never signed in`)
  if (c.not_started > 0) reasons.push(`${c.not_started} of ${n} haven't started`)
  if (shortfall >= 0.05) reasons.push(`attested ${Math.round(actual * 100)}% vs ${Math.round(expectedPct * 100)}% expected`)
  if (mismatches > 0) reasons.push(`${mismatches} contact self-check mismatch${mismatches === 1 ? '' : 'es'}`)
  return { rag, score: sc, reasons, attested_pct: Math.round(actual * 1000) / 10 }
}

const rank = (r: ComplianceRag) => ({ red: 3, amber: 2, green: 1, none: 0, not_started: 0 })[r]

function overviewOf(): Omit<OverviewResponse, 'cycle'> {
  const { people } = world()
  const totals = tally(people.map((p) => p.overall))
  const departments: DepartmentRow[] = DEPARTMENTS.map((department) => {
    const ps = people.filter((p) => p.department === department)
    const c = tally(ps.map((p) => p.overall))
    return { department: dk(department), department_name: department, ...c, ...score(c, ps.filter((p) => p.mismatch === true).length) }
  })
  const cells: CellRow[] = []
  for (const department of DEPARTMENTS) {
    for (const region of REGIONS) {
      const ps = people.filter((p) => p.department === department && p.region === region)
      const c = tally(ps.map((p) => p.overall))
      const sc = score(c, ps.filter((p) => p.mismatch === true).length)
      cells.push({ department: dk(department), department_name: department, region, ...c, rag: sc.rag, reasons: sc.reasons, attested_pct: sc.attested_pct, score: sc.score })
    }
  }
  const attention: AttentionItem[] = [
    ...departments.filter((d) => d.rag === 'red' || d.rag === 'amber').map((d): AttentionItem => ({
      department: d.department, department_name: d.department_name, region: null, rag: d.rag, score: d.score, reasons: d.reasons, expected: d.expected,
      attested_pct: d.attested_pct, overdue: d.overdue, not_started: d.not_started, not_signed_in: d.not_signed_in,
    })),
    ...cells.filter((c) => c.rag === 'red' && c.expected >= 3).map((c): AttentionItem => ({
      department: c.department, department_name: c.department_name, region: c.region, rag: c.rag, score: c.score, reasons: c.reasons, expected: c.expected,
      attested_pct: c.attested_pct, overdue: c.overdue, not_started: c.not_started, not_signed_in: c.not_signed_in,
    })),
  ]
    .sort((a, b) => rank(b.rag) - rank(a.rag) || (b.score ?? 0) - (a.score ?? 0))
    .slice(0, 14)
  return { totals, departments, cells, attention }
}

// ---- public mock API ------------------------------------------------------------------------------
const wait = (ms = 120) => new Promise((r) => setTimeout(r, ms))

/** Mock viewer scope: `?mock_scope=all|own|none` (default all). Client-only; absent on the server. */
export function mockViewerScope(): ComplianceScope {
  if (typeof window === 'undefined') return 'all'
  const v = new URLSearchParams(window.location.search).get('mock_scope')
  return v === 'own' || v === 'none' ? v : 'all'
}

function cycleFor(cycleId?: number | null): ComplianceCycle {
  return CYCLES.find((c) => c.id === cycleId) ?? CYCLES[0]
}

function visibleCourses(scope: ComplianceScope): ScopeCourse[] {
  if (scope === 'all') return MOCK_COURSES
  if (scope === 'own') return MOCK_COURSES.filter((c) => c.department_name && OWN_DEPARTMENTS.includes(c.department_name))
  return []
}

export async function mockScope(cycleId?: number | null): Promise<ScopeResponse> {
  await wait(60)
  const scope = mockViewerScope()
  const courses = visibleCourses(scope)
  return {
    scope,
    courses,
    departments: (scope === 'all' ? DEPARTMENTS : scope === 'own' ? OWN_DEPARTMENTS : []).map(dk),
    cycle: cycleFor(cycleId),
    cycles: CYCLES,
  }
}

export async function mockOverview(cycleId?: number | null): Promise<OverviewResponse> {
  await wait()
  if (mockViewerScope() !== 'all') throw new MockApiError(403, 'Forbidden')
  return { cycle: cycleFor(cycleId), ...overviewOf() }
}

function findCourse(uuid: string): ScopeCourse {
  const c = visibleCourses(mockViewerScope()).find((x) => x.course_uuid === uuid || x.course_uuid === `course_${uuid}`)
  if (!c) throw new MockApiError(404, 'Not found') // outside scope: 404, never confirm existence
  return c
}

function courseRows(c: ScopeCourse) {
  const { people } = world()
  const ps = c.kind === 'general' ? people : people.filter((p) => p.department === c.department_name)
  return ps.map((p) => ({ p, st: c.kind === 'general' ? p.general : p.dept }))
}

export async function mockSummary(uuid: string, cycleId?: number | null): Promise<CourseSummaryResponse> {
  await wait()
  const course = findCourse(uuid)
  const rows = courseRows(course)
  const totals = tally(rows.map((r) => r.st.status))
  const mism = rows.filter((r) => r.p.mismatch === true).length
  const sc = score(totals, mism)
  const by_region: RegionRow[] = REGIONS.map((region) => {
    const rs = rows.filter((r) => r.p.region === region)
    const c = tally(rs.map((r) => r.st.status))
    return { region, ...c, rag: score(c, rs.filter((r) => r.p.mismatch === true).length).rag }
  }).filter((r) => r.expected > 0)
  const majalis = [...new Set(rows.map((r) => r.p.majlis).filter((m): m is string => !!m))].sort()
  const by_majlis: MajlisRow[] = majalis.map((majlis) => {
    const rs = rows.filter((r) => r.p.majlis === majlis)
    const c = tally(rs.map((r) => r.st.status))
    return { majlis, region: MAJLIS_REGION[majlis] ?? null, ...c, rag: score(c, rs.filter((r) => r.p.mismatch === true).length).rag }
  })
  const levels: LearnerLevel[] = ['national', 'regional', 'local']
  const by_level = levels
    .map((level) => ({ level, ...tally(rows.filter((r) => r.p.level === level).map((r) => r.st.status)) }))
    .filter((l) => l.expected > 0)
  return {
    cycle: cycleFor(cycleId),
    course: { course_uuid: course.course_uuid, name: course.name, kind: course.kind as CourseKind, department: course.department, department_name: course.department_name },
    totals,
    by_region,
    by_majlis,
    by_level,
    rag: sc.rag,
    reasons: sc.reasons,
  }
}

const PRIORITY: ComplianceStatus[] = ['overdue', 'not_signed_in', 'not_started', 'in_progress', 'completed', 'attested']

function filtered(course: ScopeCourse, f: LearnerFilters) {
  const q = (f.q ?? '').trim().toLowerCase()
  return courseRows(course)
    .filter(({ p, st }) => {
      if (f.status && st.status !== f.status) return false
      if (f.region && p.region !== f.region) return false
      if (f.majlis && p.majlis !== f.majlis) return false
      if (f.level && p.level !== f.level) return false
      if (q && !`${p.email} ${p.name ?? ''} ${p.roleTitle} ${p.majlis ?? ''}`.toLowerCase().includes(q)) return false
      return true
    })
    .sort(
      (a, b) =>
        PRIORITY.indexOf(a.st.status) - PRIORITY.indexOf(b.st.status) ||
        (a.p.region ?? '').localeCompare(b.p.region ?? '') ||
        (a.p.majlis ?? '').localeCompare(b.p.majlis ?? ''),
    )
}

function toItem({ p, st }: { p: Person; st: CourseState }): LearnerItem {
  return {
    id: p.id,
    email: p.email,
    role_title: p.roleTitle,
    person_name: p.name,
    department: dk(p.department),
    department_name: p.department,
    level: p.level,
    majlis: p.majlis,
    region: p.region,
    signed_in: p.signedIn,
    status: st.status,
    lessons_done: st.done,
    lessons_total: st.total,
    last_activity_at: st.lastActivityAt,
    attested_at: st.attestedAt,
    contact_check: { mismatch: p.mismatch },
  }
}

export async function mockLearners(uuid: string, f: LearnerFilters, cycleId?: number | null): Promise<LearnersResponse> {
  await wait()
  const course = findCourse(uuid)
  const all = filtered(course, f)
  const size = Math.min(200, f.page_size ?? 25)
  const page = Math.max(1, f.page ?? 1)
  return { cycle: cycleFor(cycleId), items: all.slice((page - 1) * size, page * size).map(toItem), total: all.length }
}

export async function mockChaseCsv(uuid: string, f: LearnerFilters): Promise<{ csv: string; truncated: boolean }> {
  await wait()
  const course = findCourse(uuid)
  const head = ['Name', 'Role', 'Department', 'Majlis', 'Region', 'Mailbox', 'Status']
  const lines = filtered(course, f).map(({ p, st }) =>
    [p.name ?? '', p.roleTitle, p.department, p.majlis ?? '', p.region ?? '', p.email, st.status].map(csvCell).join(','),
  )
  return { csv: [head.join(','), ...lines].join('\r\n'), truncated: false }
}

// ---- remind (seam C) ------------------------------------------------------------------------
const _reminded = new Set<string>()

/** Mirrors the API: preview is free, a real send takes the course's 24 h slot (second one: 429). */
export async function mockRemind(uuid: string, dryRun: boolean): Promise<RemindResponse> {
  await wait()
  const course = findCourse(uuid) // 404 outside the viewer's scope
  if (mockViewerScope() === 'none') throw new MockApiError(403, 'Forbidden')
  if (_reminded.has(course.course_uuid)) throw new MockApiError(429, 'Already reminded')
  const rows = courseRows(course).map(({ st }) => st.status)
  const attested = rows.filter((s) => s === 'attested').length
  const outstanding = rows.length - attested
  const recent = Math.min(outstanding, Math.floor(outstanding / 5))
  const wouldSend = outstanding - recent
  if (!dryRun) _reminded.add(course.course_uuid)
  return {
    dry_run: dryRun, enabled: true, test_mode: true, candidates: outstanding,
    would_send: dryRun ? wouldSend : 0, sent: dryRun ? 0 : wouldSend, skipped_recent: recent,
    skipped_attested: attested, skipped_excluded: 0, suppressed: 0, failed: 0, disabled: 0, stopped: null,
    remaining: 0, time_budget_hit: false, quarantined: 0, newly_quarantined: 0, skipped_cooldown: 0, cooldown_days: 3, preview_digest: dryRun ? `mock-${course.course_uuid}` : null,
  }
}
