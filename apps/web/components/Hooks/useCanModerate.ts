import { useMemo } from 'react'
import useAdminStatus from '@components/Hooks/useAdminStatus'
import { useOrg } from '@components/Contexts/OrgContext'

/**
 * Mirrors the API's `is_moderation_staff`: org managers, or a role in THIS org
 * that grants `communities.action_update` (community moderators).
 *
 * Kept out of useAdminStatus on purpose: that hook only merges a fixed set of
 * resource keys, so `communities` rights are not in its `rights` object.
 */
export default function useCanModerate(): { canModerate: boolean; loading: boolean } {
  const { canManageOrg, userRoles, loading } = useAdminStatus()
  const org = useOrg() as any
  const orgId = org?.id

  const isCommunityModerator = useMemo(
    () =>
      !!orgId &&
      (userRoles || []).some(
        (r) => r?.org?.id === orgId && r?.role?.rights?.communities?.action_update === true
      ),
    [userRoles, orgId]
  )

  return { canModerate: canManageOrg || isCommunityModerator, loading }
}
