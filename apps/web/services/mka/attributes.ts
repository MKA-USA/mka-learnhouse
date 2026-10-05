'use client'
/**
 * Typed client + TanStack Query hooks for the MKA attributes API (`/mka/attributes/*`,
 * contract: docs/superpowers/specs/2026-10-05-mka-audience-contracts.md §2–3).
 *
 * Access control lives ONLY on the server. Nothing here decides who may see data: a failing
 * or loading `/me` yields `viewer: null, canViewAll: false`, so UI built on top fails closed.
 */
import { useEffect, useMemo, useState } from 'react'
import { useParams } from 'next/navigation'
import { useQuery } from '@tanstack/react-query'
import { getAPIUrl } from '@services/config/config'
import { RequestBodyWithAuthHeader } from '@services/utils/ts/requests'
import { useLHSession } from '@components/Contexts/LHSessionContext'
import { useOrg } from '@components/Contexts/OrgContext'
import { mkaAudienceMock } from './flags'
import type {
  AudienceCount,
  AudienceOptions,
  CountState,
  Counterparts,
  MkaMeResponse,
  MkaViewerAttributes,
  Rule,
} from '@components/mka/audience/types'

// Dev/screenshot mock layer: NEXT_PUBLIC_MKA_AUDIENCE_MOCK=1, hard-disabled in production builds (flags.ts).
// Read at call time (Next still inlines NEXT_PUBLIC_* inside functions) so tests can flip it.
const MOCK = mkaAudienceMock

export class AttributesApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.name = 'AttributesApiError'
    this.status = status
  }
}

export const mkaAttributeKeys = {
  all: ['mka-attributes'] as const,
  me: (courseUuid: string | null) => ['mka-attributes', 'me', courseUuid] as const,
  options: (orgId: number | null) => ['mka-attributes', 'options', orgId] as const,
  count: (orgId: number | null, courseUuid: string | null, hash: string) =>
    ['mka-attributes', 'count', orgId, courseUuid, hash] as const,
  counterparts: () => ['mka-attributes', 'counterparts'] as const,
}

export interface AttributesAuth {
  token: string | undefined
  /** True once the session is resolved (signed in or definitely anonymous). */
  resolved: boolean
  signedIn: boolean
}

export function useAttributesAuth(): AttributesAuth {
  const session = useLHSession() as { status?: string; data?: { tokens?: { access_token?: string } } } | null
  const token = session?.data?.tokens?.access_token
  if (MOCK()) return { token, resolved: true, signedIn: true }
  return { token, resolved: !!session && session.status !== 'loading', signedIn: !!token }
}

async function request<T>(method: 'GET' | 'POST', path: string, body: unknown, token: string | undefined): Promise<T> {
  const res = await fetch(`${getAPIUrl()}mka/attributes/${path}`, RequestBodyWithAuthHeader(method, body, { revalidate: 0 }, token))
  if (!res.ok) throw new AttributesApiError(res.status, `Attributes request failed (${res.status})`)
  return (await res.json()) as T
}

const mock = () => import('./attributes.mock')

// ---- fetchers (mock-aware) ------------------------------------------------------------------
export async function fetchMe(token: string | undefined, courseUuid: string | null): Promise<MkaMeResponse> {
  if (MOCK()) return (await mock()).mockMe()
  const qs = courseUuid ? `?course_uuid=${encodeURIComponent(courseUuid)}` : ''
  return request<MkaMeResponse>('GET', `me${qs}`, null, token)
}

export async function fetchAudienceOptions(token: string | undefined, orgId: number): Promise<AudienceOptions> {
  if (MOCK()) return (await mock()).mockOptions()
  return request<AudienceOptions>('GET', `options?org_id=${orgId}`, null, token)
}

export async function fetchAudienceCount(
  token: string | undefined,
  body: { org_id: number; course_uuid?: string | null; rule: unknown },
): Promise<AudienceCount> {
  if (MOCK()) return (await mock()).mockCount(body.rule)
  const payload: Record<string, unknown> = { org_id: body.org_id, rule: body.rule }
  if (body.course_uuid) payload.course_uuid = body.course_uuid
  return request<AudienceCount>('POST', 'audience/count', payload, token)
}

export async function fetchCounterparts(token: string | undefined): Promise<Counterparts> {
  if (MOCK()) return (await mock()).mockCounterparts()
  return request<Counterparts>('GET', 'me/counterparts', null, token)
}

export type PreviewPerson = { user_id: number; display_name: string; email: string }

export async function searchPreviewPeople(
  token: string | undefined,
  orgId: number,
  q: string,
): Promise<{ people: PreviewPerson[] }> {
  if (MOCK()) return (await mock()).mockPeople(q)
  return request('GET', `preview-people?org_id=${orgId}&q=${encodeURIComponent(q)}`, null, token)
}

/** Previewing a specific person writes an audit row server-side. */
export async function fetchPreviewPerson(
  token: string | undefined,
  orgId: number,
  userId: number,
): Promise<{ attributes: MkaViewerAttributes }> {
  if (MOCK()) return (await mock()).mockPerson(userId)
  return request('POST', `preview-people/${userId}?org_id=${orgId}`, null, token)
}

// ---- scope (org id + course uuid) -----------------------------------------------------------
export type AudienceScope = { orgId: number | null; courseUuid: string | null }

const withCoursePrefix = (v: string) => (v.startsWith('course_') ? v : `course_${v}`)

/**
 * Where the org id / course uuid come from (verified in this checkout):
 *  - org id: `activity.org_id` (ActivityRead), falling back to the OrgContext org;
 *  - course uuid: explicit hint from the hook site (`props.course.course_uuid`), else the route
 *    param `courseuuid` (learner/embed pages) or `courseid` (/editor/course/[courseid]/...).
 *    ActivityRead carries only the numeric `course_id`, so it cannot be used.
 * The API stores uuids with the `course_` prefix; route params may omit it, so it is normalised.
 */
export function useAudienceScope(activity: any, hints?: { courseUuid?: string | null; orgId?: number | null }): AudienceScope {
  const org = useOrg() as { id?: number } | null
  const params = useParams() as Record<string, string | string[] | undefined> | null
  const fromRoute = params?.courseuuid ?? params?.courseid
  const raw = hints?.courseUuid || (Array.isArray(fromRoute) ? fromRoute[0] : fromRoute) || null
  return {
    orgId: (hints?.orgId ?? activity?.org_id ?? org?.id ?? null) as number | null,
    courseUuid: raw ? withCoursePrefix(String(raw)) : null,
  }
}

// ---- hooks ----------------------------------------------------------------------------------
export type MkaViewerState = {
  state: 'loading' | 'ready' | 'error'
  viewer: MkaViewerAttributes | null
  canViewAll: boolean
}

/** Viewer attributes. Loading / error / anonymous all yield `viewer: null, canViewAll: false` (fail closed). */
export function useMkaViewer(courseUuid?: string | null): MkaViewerState {
  const auth = useAttributesAuth()
  const key = courseUuid ?? null
  const q = useQuery({
    queryKey: mkaAttributeKeys.me(key),
    queryFn: () => fetchMe(auth.token, key),
    enabled: auth.resolved && auth.signedIn,
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false,
    retry: 1,
  })
  return useMemo<MkaViewerState>(() => {
    if (!auth.resolved) return { state: 'loading', viewer: null, canViewAll: false }
    if (!auth.signedIn) return { state: 'ready', viewer: null, canViewAll: false } // anonymous: NULL_VIEWER
    // Data wins: a failed background refetch must not turn a resolved viewer into an anonymous one.
    if (q.data) return { state: 'ready', viewer: q.data.attributes, canViewAll: !!q.data.can_view_all }
    if (q.isError) return { state: 'error', viewer: null, canViewAll: false }
    return { state: 'loading', viewer: null, canViewAll: false }
  }, [auth.resolved, auth.signedIn, q.isError, q.data])
}

export function useAudienceOptions(orgId: number | null | undefined, enabled = true) {
  const auth = useAttributesAuth()
  return useQuery({
    queryKey: mkaAttributeKeys.options(orgId ?? null),
    queryFn: () => fetchAudienceOptions(auth.token, orgId as number),
    enabled: enabled && auth.resolved && auth.signedIn && !!orgId,
    staleTime: 10 * 60_000,
    refetchOnWindowFocus: false,
    retry: 1,
  })
}

/** Stable key for a rule: object key order and the TOP-LEVEL `label` (display cache) do not matter. */
export function ruleHash(rule: unknown): string {
  const norm = (x: unknown): unknown => {
    if (Array.isArray(x)) return x.map(norm)
    if (x && typeof x === 'object') {
      return Object.fromEntries(
        Object.entries(x as Record<string, unknown>)
          .sort(([a], [b]) => (a < b ? -1 : 1))
          .map(([k, v]) => [k, norm(v)]),
      )
    }
    return x
  }
  if (rule && typeof rule === 'object' && !Array.isArray(rule)) {
    const { label: _label, ...rest } = rule as Record<string, unknown>
    return JSON.stringify(norm(rest))
  }
  return JSON.stringify(norm(rule))
}

/** Debounced (400 ms) audience count, cached by stable rule hash. Authoring only: pass `rule: null` to stay idle. */
export function useAudienceCount(orgId: number | null | undefined, courseUuid: string | null | undefined, rule: Rule | null): CountState {
  const auth = useAttributesAuth()
  const hash = rule ? ruleHash(rule) : ''
  const [debounced, setDebounced] = useState(hash)
  useEffect(() => {
    if (hash === debounced) return
    const t = setTimeout(() => setDebounced(hash), 400)
    return () => clearTimeout(t)
  }, [hash, debounced])
  const settled = hash === debounced
  const q = useQuery({
    queryKey: mkaAttributeKeys.count(orgId ?? null, courseUuid ?? null, debounced),
    queryFn: () =>
      fetchAudienceCount(auth.token, { org_id: orgId as number, course_uuid: courseUuid ?? null, rule: JSON.parse(debounced) }),
    enabled: auth.resolved && auth.signedIn && !!orgId && !!rule && debounced !== '',
    staleTime: 60_000,
    refetchOnWindowFocus: false,
    retry: false,
  })
  if (!rule || !orgId) return { state: 'idle' }
  if (!settled || q.isFetching) return q.data ? { state: 'loading', data: q.data } : { state: 'loading' }
  if (q.isError) return { state: 'error' }
  if (q.data) return { state: 'ready', data: q.data }
  return { state: 'idle' }
}

export function useCounterparts(enabled = true) {
  const auth = useAttributesAuth()
  return useQuery({
    queryKey: mkaAttributeKeys.counterparts(),
    queryFn: () => fetchCounterparts(auth.token),
    enabled: enabled && auth.resolved && auth.signedIn,
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false,
    retry: 1,
  })
}
