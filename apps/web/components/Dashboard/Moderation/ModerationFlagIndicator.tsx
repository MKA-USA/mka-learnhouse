'use client'
import React from 'react'
import { useTranslation } from 'react-i18next'
import { Flag } from 'lucide-react'
import { Popover, PopoverContent, PopoverTrigger } from '@components/ui/popover'
import type { ModerationContentType } from '@services/moderation/flags'
import { useOrg } from '@components/Contexts/OrgContext'
import { ModerationFlagCard } from './ModerationFlagCard'
import { useContentFlags } from './useModerationFlags'

interface ModerationFlagIndicatorProps {
  contentType: ModerationContentType
  contentUuid: string | undefined
  /** The caller's existing staff gate. When false this renders nothing and fetches nothing. */
  isStaff: boolean
  className?: string
}

/**
 * Small "flagged for review" chip with a detail popover. Staff only; renders
 * nothing for non-staff, while loading, on error, or when there is no open flag.
 */
export function ModerationFlagIndicator({ contentType, contentUuid, isStaff, className }: ModerationFlagIndicatorProps) {
  const { t } = useTranslation()
  const org = useOrg() as any
  const { data } = useContentFlags(contentType, contentUuid, isStaff)

  if (!isStaff) return null
  const open = (data?.items ?? []).filter((f) => f.status === 'open')
  if (open.length === 0) return null

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          onClick={(e) => e.stopPropagation()}
          className={
            className ??
            'inline-flex items-center gap-1 rounded-md bg-amber-50 px-1.5 py-0.5 text-[11px] font-medium text-amber-800 hover:bg-amber-100'
          }
        >
          <Flag size={11} aria-hidden /> {t('moderation.flagged_badge')}
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-96 max-w-[90vw] space-y-3 p-3" onClick={(e) => e.stopPropagation()}>
        <p className="text-sm font-semibold text-gray-800">{t('moderation.flag_title')}</p>
        {open.map((f) => (
          <ModerationFlagCard key={f.flag_uuid} flag={f} orgslug={org?.slug} showContentType={false} compact className="border-gray-100" />
        ))}
      </PopoverContent>
    </Popover>
  )
}

export default ModerationFlagIndicator
