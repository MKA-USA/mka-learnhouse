'use client'
import React from 'react'
import { toast } from 'react-hot-toast'
import { useTranslation } from 'react-i18next'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ShieldCheck } from 'lucide-react'
import { useOrg } from '@components/Contexts/OrgContext'
import { useLHSession } from '@components/Contexts/LHSessionContext'
import useAdminStatus from '@components/Hooks/useAdminStatus'
import { Switch } from '@components/ui/switch'
import { Checkbox } from '@components/ui/checkbox'
import { queryKeys } from '@/lib/query/keys'
import { revalidateTags } from '@services/utils/ts/requests'
import {
  getOrgAiModerationConfig,
  updateOrgAiModerationConfig,
  type ModerationContentType,
} from '@services/moderation/flags'

const SURFACES: ModerationContentType[] = ['discussion', 'discussion_comment', 'assignment_submission', 'user_profile']

/** Org settings card for AI content moderation (default off, with explicit privacy disclosure). */
export default function OrgEditAIModeration() {
  const { t } = useTranslation()
  const org = useOrg() as any
  const session = useLHSession() as any
  const token = session?.data?.tokens?.access_token
  const queryClient = useQueryClient()
  const { rights } = useAdminStatus()
  const canEdit = rights?.organizations?.action_update === true

  const settingsKey = ['moderation-settings', org?.id]
  const { data: settings, isLoading, isError, refetch } = useQuery({
    queryKey: settingsKey,
    queryFn: () => getOrgAiModerationConfig(org.id, token),
    enabled: !!(org?.id && token),
    retry: false,
    refetchOnWindowFocus: false,
  })

  const [saving, setSaving] = React.useState(false)
  const enabled = settings?.enabled ?? false
  const surfaces = settings?.surfaces ?? SURFACES
  const providerAvailable = settings?.provider_available !== false

  const save = async (next: { enabled: boolean; surfaces: ModerationContentType[] }) => {
    const previous = settings
    queryClient.setQueryData(settingsKey, { ...(settings ?? { provider_available: true }), ...next })
    setSaving(true)
    const tid = toast.loading(t('moderation.settings.saving'))
    try {
      const saved = await updateOrgAiModerationConfig(String(org.id), next, token)
      if (saved && typeof saved.enabled === 'boolean') queryClient.setQueryData(settingsKey, saved)
      await revalidateTags(['organizations'], org.slug)
      queryClient.invalidateQueries({ queryKey: queryKeys.org.detail(org.slug) })
      toast.success(t('moderation.settings.saved'), { id: tid })
    } catch (e: any) {
      queryClient.setQueryData(settingsKey, previous)
      toast.error(e?.message || t('moderation.settings.error'), { id: tid })
    } finally {
      setSaving(false)
    }
  }

  const onToggle = (next: boolean) => save({ enabled: next, surfaces })

  const onSurface = (surface: ModerationContentType, checked: boolean) => {
    const next = checked ? [...new Set([...surfaces, surface])] : surfaces.filter((s) => s !== surface)
    if (next.length === 0) return // at least one surface must stay selected
    save({ enabled, surfaces: SURFACES.filter((s) => next.includes(s)) })
  }

  // Turning ON needs a provider; turning OFF is always allowed.
  const toggleDisabled = saving || !canEdit || isLoading || isError || (!providerAvailable && !enabled)

  return (
    <div className="rounded-xl bg-white nice-shadow p-4 space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div className="flex gap-3 min-w-0">
          <div className="flex-shrink-0 mt-0.5 text-gray-400">
            <ShieldCheck className="w-4 h-4" />
          </div>
          <div className="space-y-0.5 min-w-0">
            <h4 className="text-sm font-medium text-gray-800">{t('moderation.settings.title')}</h4>
            <p className="text-xs text-gray-500 leading-relaxed">{t('moderation.settings.subtitle')}</p>
          </div>
        </div>
        <Switch
          checked={enabled}
          onCheckedChange={onToggle}
          disabled={toggleDisabled}
          aria-label={t('moderation.settings.toggle_label')}
          className="flex-shrink-0 mt-0.5"
        />
      </div>

      {isLoading && <p className="text-xs text-gray-500">{t('moderation.settings.loading')}</p>}
      {isError && (
        <p className="text-xs text-red-700">
          {t('moderation.settings.load_error')}{' '}
          <button type="button" onClick={() => refetch()} className="underline">
            {t('moderation.retry')}
          </button>
        </p>
      )}
      {settings && !providerAvailable && (
        <p role="alert" className="rounded-lg border border-amber-200 bg-amber-50 p-2.5 text-xs text-amber-900">
          {t('moderation.settings.no_provider')}
        </p>
      )}

      {settings && (
        <fieldset className="space-y-2" disabled={saving || !canEdit}>
          <legend className="text-xs font-semibold text-gray-700 mb-1">{t('moderation.settings.surfaces_title')}</legend>
          {SURFACES.map((surface) => (
            <label key={surface} className="flex items-center gap-2 text-xs text-gray-700">
              <Checkbox
                checked={surfaces.includes(surface)}
                onCheckedChange={(v) => onSurface(surface, v === true)}
                disabled={saving || !canEdit}
              />
              {t(`moderation.settings.surface.${surface}`)}
            </label>
          ))}
        </fieldset>
      )}

      <p className="text-xs text-gray-500">{t('moderation.settings.toggle_help')}</p>

      <div className="rounded-lg bg-gray-50 border border-gray-100 p-3">
        <p className="text-xs font-semibold text-gray-700 mb-1.5">{t('moderation.settings.privacy_title')}</p>
        <ul className="list-disc ps-4 space-y-1 text-xs text-gray-600 leading-relaxed">
          {[1, 2, 3, 4, 5].map((n) => (
            <li key={n}>{t(`moderation.settings.privacy_${n}`)}</li>
          ))}
        </ul>
      </div>

      {!canEdit && <p className="text-xs text-amber-700">{t('moderation.settings.admin_only')}</p>}
    </div>
  )
}
