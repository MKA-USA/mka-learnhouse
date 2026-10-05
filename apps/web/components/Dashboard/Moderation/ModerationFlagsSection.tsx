'use client'
import React from 'react'
import { useTranslation } from 'react-i18next'
import { Flag } from 'lucide-react'
import { useOrg } from '@components/Contexts/OrgContext'
import { ModerationFlagCard } from './ModerationFlagCard'
import { useUserFlags } from './useModerationFlags'

/** Staff-only dossier section. Renders nothing when there is nothing to show or the API denies access. */
export function ModerationFlagsSection({ userUuid, isStaff = true }: { userUuid: string | undefined; isStaff?: boolean }) {
  const { t } = useTranslation()
  const org = useOrg() as any
  const { data, isError } = useUserFlags(userUuid, isStaff)
  if (!isStaff || isError) return null
  const items = data?.items ?? []
  return (
    <section className="rounded-xl border border-gray-200 bg-white p-5" aria-labelledby="mod-flags-title">
      <div className="mb-3 flex items-center gap-2">
        <Flag size={14} className="text-gray-400" aria-hidden />
        <h3 id="mod-flags-title" className="text-sm font-semibold text-gray-800">{t('moderation.dossier.title')}</h3>
        <span className="text-xs text-gray-400">{t('moderation.dossier.subtitle')}</span>
      </div>
      {items.length === 0 ? (
        <p className="text-sm text-gray-400">{t('moderation.dossier.none')}</p>
      ) : (
        <div className="space-y-3">
          {items.map((f) => (
            <ModerationFlagCard key={f.flag_uuid} flag={f} orgslug={org?.slug} compact />
          ))}
        </div>
      )}
    </section>
  )
}

export default ModerationFlagsSection
