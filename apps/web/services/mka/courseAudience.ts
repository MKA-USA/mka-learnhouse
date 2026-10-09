// MKA fork — fetchers for the per-course Audience API (contract: seam A, routers/mka_course_audience.py).
// All endpoint shapes live in this file so they are easy to adjust.
import { getAPIUrl } from '@services/config/config'
import { RequestBodyWithAuthHeader } from '@services/utils/ts/requests'

export type CourseAudienceKind = 'everyone' | 'officeholders' | 'custom'
export type CourseAudienceMode = 'required' | 'optin'
export type CustomRule = { departments: string[]; levels: string[]; roles: string[] }

export type CourseAudienceBody = { audience: CourseAudienceKind; mode: CourseAudienceMode; rule: Partial<CustomRule> }

export type CourseAudienceState =
  | { audience: null }
  | { audience: CourseAudienceKind; mode: CourseAudienceMode; rule: Partial<CustomRule> | null; usergroup_id: number | null; matched_count: number }

export type AudiencePreview = {
  matched_count: number
  would_enroll: number
  sample: { user_id: number; name: string; email: string }[]
}

export type AudienceApplyResult = { memberships_added: number; memberships_removed: number; enrolled: number; matched_count: number }

export type RawOptions = { departments?: unknown[]; levels?: unknown[]; roles?: unknown[] }

export class CourseAudienceError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.name = 'CourseAudienceError'
    this.status = status
  }
}

async function request<T>(method: 'GET' | 'POST' | 'PUT' | 'DELETE', path: string, body: unknown, token?: string): Promise<T> {
  const res = await fetch(`${getAPIUrl()}mka/courses/${path}`, RequestBodyWithAuthHeader(method, body, { revalidate: 0 }, token))
  if (!res.ok) {
    let detail = ''
    try {
      const j = await res.json()
      detail = typeof j?.detail === 'string' ? j.detail : ''
    } catch {
      /* non-JSON error body */
    }
    throw new CourseAudienceError(res.status, detail || `Request failed (${res.status})`)
  }
  return (res.status === 204 ? ({} as T) : ((await res.json()) as T))
}

const enc = encodeURIComponent

export const fetchCourseAudience = (courseUuid: string, token?: string) =>
  request<CourseAudienceState>('GET', `${enc(courseUuid)}/audience`, null, token)

export const previewCourseAudience = (courseUuid: string, body: CourseAudienceBody, token?: string) =>
  request<AudiencePreview>('POST', `${enc(courseUuid)}/audience/preview`, body, token)

export const saveCourseAudience = (courseUuid: string, body: CourseAudienceBody, token?: string) =>
  request<AudienceApplyResult>('PUT', `${enc(courseUuid)}/audience`, body, token)

export const removeCourseAudience = (courseUuid: string, token?: string) =>
  request<unknown>('DELETE', `${enc(courseUuid)}/audience`, null, token)

export const fetchCourseAudienceOptions = (token?: string) => request<RawOptions>('GET', 'audience/options', null, token)
