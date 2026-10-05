'use client'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useLHSession } from '@components/Contexts/LHSessionContext'
import { useOrg } from '@components/Contexts/OrgContext'
import {
  getModerationFlagsByContent,
  getModerationFlagsByUser,
  listModerationFlags,
  updateModerationFlagStatus,
  type ListModerationFlagsParams,
  type ModerationContentType,
  type ModerationFlagStatus,
} from '@services/moderation/flags'

const STALE_TIME = 60_000

/** 403/404 mean "not visible to you / nothing there": treat as no flags, silently. */
async function orEmptyOnDenied<T extends { items: any[] }>(p: Promise<T>): Promise<T> {
  try {
    return await p
  } catch (e: any) {
    if (e?.status === 403 || e?.status === 404) return { items: [] } as unknown as T
    throw e
  }
}
export const MODERATION_KEY = 'moderation-flags'

function useAuth() {
  const org = useOrg() as any
  const session = useLHSession() as any
  return {
    orgId: org?.id as number | undefined,
    orgslug: org?.slug as string | undefined,
    token: session?.data?.tokens?.access_token as string | undefined,
  }
}

/**
 * Flags for one piece of content. `isStaff` MUST be the caller's existing staff
 * gate (e.g. community `canManage`, dashboard access). When false nothing is
 * fetched, so students and authors never hit the endpoint.
 */
export function useContentFlags(
  contentType: ModerationContentType,
  contentUuid: string | undefined,
  isStaff: boolean
) {
  const { orgId, token } = useAuth()
  return useQuery({
    queryKey: [MODERATION_KEY, 'content', orgId, contentType, contentUuid],
    queryFn: () =>
      orEmptyOnDenied(getModerationFlagsByContent(orgId as number, contentType, contentUuid as string, token as string)),
    enabled: !!(isStaff && orgId && token && contentUuid),
    staleTime: STALE_TIME,
    retry: false,
    refetchOnWindowFocus: false,
  })
}

export function useUserFlags(userUuid: string | undefined, isStaff: boolean) {
  const { orgId, token } = useAuth()
  return useQuery({
    queryKey: [MODERATION_KEY, 'user', orgId, userUuid],
    queryFn: () => orEmptyOnDenied(getModerationFlagsByUser(orgId as number, userUuid as string, token as string)),
    enabled: !!(isStaff && orgId && token && userUuid),
    staleTime: STALE_TIME,
    retry: false,
    refetchOnWindowFocus: false,
  })
}

export function useFlagQueue(params: ListModerationFlagsParams) {
  const { orgId, token } = useAuth()
  return useQuery({
    queryKey: [MODERATION_KEY, 'queue', orgId, params.status, params.content_type, params.limit, params.offset],
    queryFn: () => listModerationFlags(orgId as number, params, token as string),
    enabled: !!(orgId && token),
    staleTime: 15_000,
    retry: false,
    placeholderData: (prev) => prev,
  })
}

export function useFlagStatusMutation() {
  const { token } = useAuth()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ flagUuid, status }: { flagUuid: string; status: ModerationFlagStatus }) =>
      updateModerationFlagStatus(flagUuid, status, token as string),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [MODERATION_KEY] })
    },
  })
}
