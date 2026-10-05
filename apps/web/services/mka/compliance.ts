'use client'
/**
 * Typed client + TanStack Query hooks for the MKA compliance API
 * (`/mka/compliance/*`, contract: compliance.types.ts / spec section 4).
 *
 * Access control lives ONLY on the server. Nothing here decides who may see
 * data: `scope: 'none'` just means "render nothing", a 403/404 from the API is
 * surfaced as a calm empty state, and every request carries the session bearer
 * token like the other services/*.
 */
import { useMemo } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { getAPIUrl } from '@services/config/config'
import { RequestBodyWithAuthHeader } from '@services/utils/ts/requests'
import { useLHSession } from '@components/Contexts/LHSessionContext'
import { useOrg } from '@components/Contexts/OrgContext'
import { buildQuery, learnerQuery, MOCK_TODAY, truncationNotice } from '@components/mka/compliance/format'
import type {
  ComplianceScope,
  CourseSummaryResponse,
  LearnerFilters,
  LearnersResponse,
  OverviewResponse,
  RemindResponse,
  ScopeResponse,
} from './compliance.types'

export * from './compliance.types'

/**
 * Dev/screenshot mock layer. Inlined at build time by Next (NEXT_PUBLIC_*), and
 * hard-disabled in production builds, so it can never serve fixtures to real users.
 */
export const MKA_COMPLIANCE_MOCK =
  process.env.NEXT_PUBLIC_MKA_COMPLIANCE_MOCK === '1' && process.env.NODE_ENV !== 'production'

/** The course "Remind" button (dry-run preview + confirm dialog) renders only when this flag is on. */
export const MKA_COMPLIANCE_REMIND = process.env.NEXT_PUBLIC_MKA_COMPLIANCE_REMIND === '1'

/** ISO date used for deadline countdowns (fixed in mock mode so screenshots are stable). */
export const complianceToday = (): string => (MKA_COMPLIANCE_MOCK ? MOCK_TODAY : new Date().toISOString().slice(0, 10))

export class ComplianceApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.name = 'ComplianceApiError'
    this.status = status
  }
}

export const mkaComplianceKeys = {
  all: ['mka-compliance'] as const,
  scope: (orgId: number | null, cycleId: number | null) => ['mka-compliance', 'scope', orgId, cycleId] as const,
  overview: (orgId: number | null, cycleId: number | null) => ['mka-compliance', 'overview', orgId, cycleId] as const,
  summary: (orgId: number | null, uuid: string, cycleId: number | null) =>
    ['mka-compliance', 'summary', orgId, uuid, cycleId] as const,
  learners: (orgId: number | null, uuid: string, cycleId: number | null, q: string) =>
    ['mka-compliance', 'learners', orgId, uuid, cycleId, q] as const,
}

export interface ComplianceAuth {
  orgId: number | null
  token: string | undefined
  /** True when requests can be sent (or the mock layer is on). */
  ready: boolean
}

/** Org id + bearer token from the existing contexts. Mock mode needs neither. */
export function useComplianceAuth(): ComplianceAuth {
  const org = useOrg() as { id?: number } | null
  const session = useLHSession() as { data?: { tokens?: { access_token?: string } } } | null
  const token = session?.data?.tokens?.access_token
  const orgId = org?.id ?? null
  if (MKA_COMPLIANCE_MOCK) return { orgId: orgId ?? 1, token, ready: true }
  return { orgId, token, ready: !!(orgId && token) }
}

async function getJSON<T>(path: string, query: Record<string, string | number | null | undefined>, auth: ComplianceAuth): Promise<T> {
  const qs = buildQuery({ org_id: auth.orgId, ...query })
  const res = await fetch(
    `${getAPIUrl()}mka/compliance/${path}${qs ? `?${qs}` : ''}`,
    RequestBodyWithAuthHeader('GET', null, { revalidate: 0 }, auth.token),
  )
  if (!res.ok) throw new ComplianceApiError(res.status, `Compliance request failed (${res.status})`)
  return (await res.json()) as T
}

const seg = (courseUuid: string) => encodeURIComponent(courseUuid)

// ---- fetchers (mock-aware) ------------------------------------------------------------------
export async function fetchScope(auth: ComplianceAuth, cycleId: number | null = null): Promise<ScopeResponse> {
  if (MKA_COMPLIANCE_MOCK) return (await import('./compliance.mock')).mockScope(cycleId)
  return getJSON<ScopeResponse>('scope', { cycle_id: cycleId }, auth)
}

export async function fetchOverview(auth: ComplianceAuth, cycleId: number | null): Promise<OverviewResponse> {
  if (MKA_COMPLIANCE_MOCK) return (await import('./compliance.mock')).mockOverview(cycleId)
  return getJSON<OverviewResponse>('overview', { cycle_id: cycleId }, auth)
}

export async function fetchCourseSummary(auth: ComplianceAuth, courseUuid: string, cycleId: number | null): Promise<CourseSummaryResponse> {
  if (MKA_COMPLIANCE_MOCK) return (await import('./compliance.mock')).mockSummary(courseUuid, cycleId)
  return getJSON<CourseSummaryResponse>(`courses/${seg(courseUuid)}/summary`, { cycle_id: cycleId }, auth)
}

export async function fetchLearners(
  auth: ComplianceAuth,
  courseUuid: string,
  filters: LearnerFilters,
  cycleId: number | null,
): Promise<LearnersResponse> {
  if (MKA_COMPLIANCE_MOCK) return (await import('./compliance.mock')).mockLearners(courseUuid, filters, cycleId)
  const params = new URLSearchParams(learnerQuery(filters, cycleId, null))
  return getJSON<LearnersResponse>(`courses/${seg(courseUuid)}/learners`, Object.fromEntries(params), auth)
}

/**
 * "Remind" (seam C). `dryRun` defaults to TRUE on the server too: a real send needs an explicit `dryRun === false`.
 * Throws ComplianceApiError with the HTTP status (403 / 404 / 409 / 429) so the dialog can word each case.
 */
export async function remindCourse(
  auth: ComplianceAuth,
  courseUuid: string,
  cycleId: number | null,
  dryRun: boolean,
): Promise<RemindResponse> {
  if (MKA_COMPLIANCE_MOCK) return (await import('./compliance.mock')).mockRemind(courseUuid, dryRun)
  const qs = buildQuery({ org_id: auth.orgId, cycle_id: cycleId, dry_run: dryRun ? 'true' : 'false' })
  const res = await fetch(
    `${getAPIUrl()}mka/compliance/courses/${seg(courseUuid)}/remind?${qs}`,
    RequestBodyWithAuthHeader('POST', null, { revalidate: 0 }, auth.token),
  )
  if (!res.ok) throw new ComplianceApiError(res.status, `Remind request failed (${res.status})`)
  return (await res.json()) as RemindResponse
}

/**
 * Chase-list CSV. The URL is built from the typed filters via URLSearchParams
 * (never string-concatenated user text) and fetched with the bearer token, so
 * the server scope-checks it; the file is saved from a Blob under a fixed,
 * sanitised filename supplied by the caller.
 */
export async function downloadChaseListCsv(
  auth: ComplianceAuth,
  courseUuid: string,
  filters: LearnerFilters,
  cycleId: number | null,
  filename: string,
): Promise<{ notice: string | null }> {
  let blob: Blob
  let notice: string | null = null
  if (MKA_COMPLIANCE_MOCK) {
    const csv = await (await import('./compliance.mock')).mockChaseCsv(courseUuid, filters)
    blob = new Blob([csv.csv], { type: 'text/csv;charset=utf-8' })
    notice = truncationNotice(csv.truncated ? 'true' : null, null)
  } else {
    const params = new URLSearchParams(learnerQuery({ ...filters, page: undefined, page_size: undefined }, cycleId, auth.orgId))
    const res = await fetch(
      `${getAPIUrl()}mka/compliance/courses/${seg(courseUuid)}/learners.csv?${params.toString()}`,
      RequestBodyWithAuthHeader('GET', null, { revalidate: 0 }, auth.token),
    )
    if (!res.ok) throw new ComplianceApiError(res.status, `CSV download failed (${res.status})`)
    notice = truncationNotice(res.headers.get('X-Truncated'), res.headers.get('X-Row-Limit'))
    blob = await res.blob()
  }
  const url = URL.createObjectURL(blob)
  try {
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.rel = 'noopener'
    document.body.appendChild(a)
    a.click()
    a.remove()
  } finally {
    setTimeout(() => URL.revokeObjectURL(url), 10_000)
  }
  return { notice }
}

// ---- hooks ----------------------------------------------------------------------------------------
const noRetryOnClientError = (count: number, err: unknown) => {
  const s = (err as ComplianceApiError)?.status
  if (s && s >= 400 && s < 500) return false
  return count < 2
}

/** Scope for the selected cycle (null = server default). 403 is a normal "no access" answer, not a failure to report. */
export function useComplianceScopeQuery(cycleId: number | null = null) {
  const auth = useComplianceAuth()
  return useQuery({
    queryKey: [...mkaComplianceKeys.scope(auth.orgId, cycleId), MKA_COMPLIANCE_MOCK && typeof window !== 'undefined' ? window.location.search : ''],
    queryFn: () => fetchScope(auth, cycleId),
    enabled: auth.ready,
    staleTime: 5 * 60_000,
    placeholderData: keepPreviousData,
    retry: noRetryOnClientError,
  })
}

/**
 * Nav visibility only. 'none' while loading or on any error, so a failing API
 * can never leak a nav item (the API still enforces on every endpoint).
 */
export function useMkaComplianceScope(): ComplianceScope {
  const { data } = useComplianceScopeQuery()
  return data?.scope ?? 'none'
}

export function useComplianceOverview(cycleId: number | null, enabled = true) {
  const auth = useComplianceAuth()
  return useQuery({
    queryKey: mkaComplianceKeys.overview(auth.orgId, cycleId),
    queryFn: () => fetchOverview(auth, cycleId),
    enabled: auth.ready && enabled,
    staleTime: 60_000,
    retry: noRetryOnClientError,
  })
}

export function useCourseSummary(courseUuid: string, cycleId: number | null, enabled = true) {
  const auth = useComplianceAuth()
  return useQuery({
    queryKey: mkaComplianceKeys.summary(auth.orgId, courseUuid, cycleId),
    queryFn: () => fetchCourseSummary(auth, courseUuid, cycleId),
    enabled: auth.ready && enabled && !!courseUuid,
    staleTime: 60_000,
    retry: noRetryOnClientError,
  })
}

export function useLearners(courseUuid: string, filters: LearnerFilters, cycleId: number | null) {
  const auth = useComplianceAuth()
  const key = useMemo(() => learnerQuery(filters, cycleId, null), [filters, cycleId])
  return useQuery({
    queryKey: mkaComplianceKeys.learners(auth.orgId, courseUuid, cycleId, key),
    queryFn: () => fetchLearners(auth, courseUuid, filters, cycleId),
    enabled: auth.ready && !!courseUuid,
    staleTime: 30_000,
    placeholderData: keepPreviousData,
    retry: noRetryOnClientError,
  })
}

/** HTTP status behind a failed query, when it has one (403/404 get their own states). */
export const errorStatus = (err: unknown): number | null => {
  const s = (err as { status?: unknown })?.status
  return typeof s === 'number' ? s : null
}
