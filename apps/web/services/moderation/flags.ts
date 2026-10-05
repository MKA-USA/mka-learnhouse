import { getAPIUrl } from '@services/config/config'
import { RequestBodyWithAuthHeader, errorHandling } from '@services/utils/ts/requests'

/**
 * Typed client for the AI content-moderation flag endpoints.
 *
 * Staff only: the API returns 403/404 to students and authors, and the UI
 * must never call these for non-staff. Flags are review aids, not verdicts.
 */

export type ModerationFlagStatus = 'open' | 'reviewed' | 'dismissed'
export type ModerationFlagStatusFilter = ModerationFlagStatus | 'all'
export type ModerationContentType =
  | 'discussion'
  | 'discussion_comment'
  | 'assignment_submission'
  | 'user_profile'
export type ModerationSeverity = 'medium' | 'high'

export interface ModerationFlagScores {
  pii: number
  toxicity: number
  spam: number
  academic_integrity: number | null
}

export interface ModerationFlag {
  flag_uuid: string
  org_id: number
  content_type: ModerationContentType
  content_uuid: string
  author_user_uuid: string | null
  kind: string
  severity: ModerationSeverity
  scores: ModerationFlagScores
  reasons: string[]
  status: ModerationFlagStatus
  reviewed_by_user_uuid: string | null
  reviewed_at: string | null
  created_at: string
  content_link: string | null
}

export interface ModerationFlagList {
  items: ModerationFlag[]
  total: number
}

export interface ModerationFlagItems {
  items: ModerationFlag[]
}

export interface ListModerationFlagsParams {
  status?: ModerationFlagStatusFilter
  content_type?: ModerationContentType | ''
  limit?: number
  offset?: number
}

export interface AiModerationConfigPayload {
  enabled: boolean
  surfaces?: string[]
}

export interface AiModerationSettings {
  enabled: boolean
  surfaces: ModerationContentType[]
  provider_available: boolean
}

const base = () => `${getAPIUrl()}moderation-flags`

export async function listModerationFlags(
  org_id: number | string,
  params: ListModerationFlagsParams,
  access_token: string
): Promise<ModerationFlagList> {
  const qs = new URLSearchParams()
  qs.set('status', params.status ?? 'open')
  if (params.content_type) qs.set('content_type', params.content_type)
  qs.set('limit', String(params.limit ?? 50))
  qs.set('offset', String(params.offset ?? 0))
  const result: any = await fetch(
    `${base()}/orgs/${org_id}?${qs.toString()}`,
    RequestBodyWithAuthHeader('GET', null, null, access_token)
  )
  return errorHandling(result)
}

export async function getModerationFlagsByContent(
  org_id: number | string,
  content_type: ModerationContentType,
  content_uuid: string,
  access_token: string
): Promise<ModerationFlagItems> {
  const qs = new URLSearchParams({ content_type, content_uuid })
  const result: any = await fetch(
    `${base()}/orgs/${org_id}/by-content?${qs.toString()}`,
    RequestBodyWithAuthHeader('GET', null, null, access_token)
  )
  return errorHandling(result)
}

export async function getModerationFlagsByUser(
  org_id: number | string,
  user_uuid: string,
  access_token: string
): Promise<ModerationFlagItems> {
  const result: any = await fetch(
    `${base()}/orgs/${org_id}/by-user/${encodeURIComponent(user_uuid)}`,
    RequestBodyWithAuthHeader('GET', null, null, access_token)
  )
  return errorHandling(result)
}

export async function updateModerationFlagStatus(
  flag_uuid: string,
  status: ModerationFlagStatus,
  access_token: string
): Promise<ModerationFlag> {
  // RequestBodyWithAuthHeader only serialises a body for POST/PUT/DELETE,
  // so PATCH builds its own options.
  const result: any = await fetch(`${base()}/${encodeURIComponent(flag_uuid)}`, {
    method: 'PATCH',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${access_token}`,
    },
    redirect: 'follow',
    credentials: 'include',
    cache: 'no-store',
    body: JSON.stringify({ status }),
  })
  return errorHandling(result)
}

export async function updateOrgAiModerationConfig(
  org_id: number | string,
  payload: AiModerationConfigPayload,
  access_token: string
) {
  const result: any = await fetch(
    `${getAPIUrl()}orgs/${org_id}/config/ai-moderation`,
    RequestBodyWithAuthHeader('PUT', payload, null, access_token)
  )
  return errorHandling(result)
}

export async function getOrgAiModerationConfig(
  org_id: number | string,
  access_token: string
): Promise<AiModerationSettings> {
  const result: any = await fetch(
    `${getAPIUrl()}orgs/${org_id}/config/ai-moderation`,
    RequestBodyWithAuthHeader('GET', null, null, access_token)
  )
  return errorHandling(result)
}
