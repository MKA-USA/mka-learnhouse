'use client'
import React from 'react'
import Link from 'next/link'
import dayjs from 'dayjs'
import toast from 'react-hot-toast'
import { useTranslation } from 'react-i18next'
import { AlertTriangle, Check, ExternalLink, RotateCcw, X } from 'lucide-react'
import { getUriWithOrg } from '@services/config/config'
import { safeExternalUrl, safeInternalPath } from '@services/security/url'
import type { ModerationFlag, ModerationFlagStatus } from '@services/moderation/flags'
import { useFlagStatusMutation } from './useModerationFlags'
import { cn } from '@/lib/utils'

const SCORE_KEYS = ['pii', 'toxicity', 'spam', 'academic_integrity'] as const

export function SeverityBadge({ severity }: { severity: ModerationFlag['severity'] }) {
  const { t } = useTranslation()
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium',
        severity === 'high' ? 'bg-amber-100 text-amber-900' : 'bg-gray-100 text-gray-700'
      )}
    >
      <AlertTriangle size={12} aria-hidden />
      {t(`moderation.severity.${severity}`)}
    </span>
  )
}

export function ScoreChips({ scores }: { scores: ModerationFlag['scores'] }) {
  const { t } = useTranslation()
  return (
    <ul className="flex flex-wrap gap-1.5" aria-label={t('moderation.flag_title')}>
      {SCORE_KEYS.map((key) => {
        const value = scores?.[key]
        if (value === null || value === undefined) return null
        const pct = Math.round(Math.max(0, Math.min(1, value)) * 100)
        return (
          <li
            key={key}
            className={cn(
              'rounded-full border px-2 py-0.5 text-xs',
              pct >= 50 ? 'border-amber-300 bg-amber-50 text-amber-900' : 'border-gray-200 bg-white text-gray-500'
            )}
          >
            {t(`moderation.scores.${key}`)} {pct}%
          </li>
        )
      })}
    </ul>
  )
}

function ContentLink({ link, orgslug }: { link: string; orgslug?: string }) {
  const { t } = useTranslation()
  const cls = 'inline-flex items-center gap-1 text-xs font-medium text-gray-700 underline-offset-2 hover:underline'
  const label = (
    <>
      {t('moderation.view_content')} <ExternalLink size={12} aria-hidden />
    </>
  )
  // Only same-origin relative paths (routed through getUriWithOrg) and http(s)
  // URLs are rendered. javascript:, data:, protocol-relative etc. render nothing.
  const external = safeExternalUrl(link)
  if (external) {
    return (
      <a href={external} rel="noopener noreferrer" className={cls}>
        {label}
      </a>
    )
  }
  const internal = safeInternalPath(link, '')
  if (internal.startsWith('/')) {
    return (
      <Link href={getUriWithOrg(orgslug ?? '', internal)} className={cls}>
        {label}
      </Link>
    )
  }
  return null
}

interface ModerationFlagCardProps {
  flag: ModerationFlag
  orgslug?: string
  /** Show the content-type label (queue and dossier). Hidden when already in context. */
  showContentType?: boolean
  compact?: boolean
  className?: string
}

/** One flag: severity, score chips, reasons, content link and review actions. Staff only. */
export function ModerationFlagCard({ flag, orgslug, showContentType = true, compact, className }: ModerationFlagCardProps) {
  const { t } = useTranslation()
  const mutation = useFlagStatusMutation()

  const setStatus = (status: ModerationFlagStatus) =>
    mutation.mutate(
      { flagUuid: flag.flag_uuid, status },
      {
        onSuccess: () => toast.success(t('moderation.updated')),
        onError: () => toast.error(t('moderation.update_failed')),
      }
    )

  const hasIntegrity = flag.scores?.academic_integrity !== null && flag.scores?.academic_integrity !== undefined
  const busy = mutation.isPending

  return (
    <div className={cn('rounded-xl border border-gray-200 bg-white p-4 space-y-3', className)}>
      <div className="flex flex-wrap items-center gap-2">
        <SeverityBadge severity={flag.severity} />
        {showContentType && (
          <span className="text-xs font-medium text-gray-600">{t(`moderation.content_type.${flag.content_type}`)}</span>
        )}
        <span className="rounded-md bg-gray-50 px-1.5 py-0.5 text-xs text-gray-500">
          {t(`moderation.status.${flag.status}`)}
        </span>
        <span className="ms-auto text-xs text-gray-400">
          {t('moderation.flagged_on', { date: dayjs(flag.created_at).format('MMM D, YYYY') })}
        </span>
      </div>

      <ScoreChips scores={flag.scores} />

      {flag.reasons?.length > 0 && !compact && (
        <div>
          <p className="mb-1 text-xs font-medium text-gray-500">{t('moderation.reasons')}</p>
          <ul className="list-disc space-y-0.5 ps-4 text-sm text-gray-700">
            {flag.reasons.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        </div>
      )}
      {flag.reasons?.length > 0 && compact && (
        <p className="text-sm text-gray-700">{flag.reasons.join(' · ')}</p>
      )}

      {hasIntegrity && (
        <p className="rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-900">{t('moderation.integrity_note')}</p>
      )}
      <p className="text-xs text-gray-400">{t('moderation.advisory')}</p>

      <div className="flex flex-wrap items-center gap-2">
        {flag.content_link && <ContentLink link={flag.content_link} orgslug={orgslug} />}
        <div className="ms-auto flex items-center gap-2">
          {flag.status === 'open' ? (
            <>
              <button
                type="button"
                onClick={() => setStatus('dismissed')}
                disabled={busy}
                className="inline-flex items-center gap-1 rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
              >
                <X size={12} aria-hidden /> {t('moderation.dismiss')}
              </button>
              <button
                type="button"
                onClick={() => setStatus('reviewed')}
                disabled={busy}
                className="inline-flex items-center gap-1 rounded-lg bg-black px-3 py-1.5 text-xs font-semibold text-white hover:bg-neutral-800 disabled:opacity-50"
              >
                <Check size={12} aria-hidden /> {t('moderation.mark_reviewed')}
              </button>
            </>
          ) : (
            <button
              type="button"
              onClick={() => setStatus('open')}
              disabled={busy}
              className="inline-flex items-center gap-1 rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
            >
              <RotateCcw size={12} aria-hidden /> {t('moderation.reopen')}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

export default ModerationFlagCard
