'use client'
import React, { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ShieldCheck } from 'lucide-react'
import { Breadcrumbs } from '@components/Objects/Breadcrumbs/Breadcrumbs'
import { useOrg } from '@components/Contexts/OrgContext'
import useCanModerate from '@components/Hooks/useCanModerate'
import ErrorUI from '@components/Objects/StyledElements/Error/Error'
import type { ModerationContentType, ModerationFlagStatusFilter } from '@services/moderation/flags'
import { ModerationFlagCard } from './ModerationFlagCard'
import { useFlagQueue } from './useModerationFlags'
import { cn } from '@/lib/utils'

const PAGE_SIZE = 50
const STATUSES: ModerationFlagStatusFilter[] = ['open', 'reviewed', 'dismissed', 'all']
const TYPES: (ModerationContentType | '')[] = ['', 'discussion', 'discussion_comment', 'assignment_submission', 'user_profile']

export default function ModerationQueue() {
  const { canModerate, loading: rightsLoading } = useCanModerate()
  if (rightsLoading) return null
  if (!canModerate) return <ErrorUI error={{ status: 403, message: 'admin_only' }} />
  return <ModerationQueueInner />
}

function ModerationQueueInner() {
  const { t } = useTranslation()
  const org = useOrg() as any
  const [status, setStatus] = useState<ModerationFlagStatusFilter>('open')
  const [contentType, setContentType] = useState<ModerationContentType | ''>('')
  const [offset, setOffset] = useState(0)

  const { data, isLoading, isError, isFetching, refetch } = useFlagQueue({
    status,
    content_type: contentType,
    limit: PAGE_SIZE,
    offset,
  })

  const items = data?.items ?? []
  const total = data?.total ?? 0

  const changeStatus = (s: ModerationFlagStatusFilter) => {
    setStatus(s)
    setOffset(0)
  }

  return (
    <div className="h-full w-full bg-[#f8f8f8] ps-4 pe-4 pb-10 sm:ps-10 sm:pe-10">
      <div className="pt-6 mb-6">
        <Breadcrumbs items={[{ label: t('moderation.nav'), href: '/dash/moderation', icon: <ShieldCheck size={14} /> }]} />
        <h1 className="mt-4 text-3xl font-bold tracking-tight">{t('moderation.title')}</h1>
        <p className="mt-1 max-w-2xl text-sm text-gray-500">{t('moderation.subtitle')}</p>
      </div>

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div role="group" aria-label={t('moderation.nav')} className="flex items-center rounded-lg border border-gray-200 bg-white p-0.5">
          {STATUSES.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => changeStatus(s)}
              aria-pressed={status === s}
              className={cn(
                'rounded-md px-3 py-1 text-xs font-medium transition-colors',
                status === s ? 'bg-gray-900 text-white' : 'text-gray-500 hover:text-gray-800'
              )}
            >
              {t(`moderation.status.${s}`)}
            </button>
          ))}
        </div>
        <select
          value={contentType}
          onChange={(e) => {
            setContentType(e.target.value as ModerationContentType | '')
            setOffset(0)
          }}
          aria-label={t('moderation.content_type.all')}
          className="rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-xs text-gray-700"
        >
          {TYPES.map((c) => (
            <option key={c || 'all'} value={c}>
              {c ? t(`moderation.content_type.${c}`) : t('moderation.content_type.all')}
            </option>
          ))}
        </select>
      </div>

      {isLoading ? (
        <div className="space-y-3" aria-busy="true">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-28 animate-pulse rounded-xl border border-gray-200 bg-white" />
          ))}
        </div>
      ) : isError ? (
        <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-6 text-center">
          <p className="text-sm text-red-800">{t('moderation.load_error')}</p>
          <button
            type="button"
            onClick={() => refetch()}
            className="mt-3 rounded-lg bg-black px-4 py-1.5 text-xs font-semibold text-white hover:bg-neutral-800"
          >
            {t('moderation.retry')}
          </button>
        </div>
      ) : items.length === 0 ? (
        <div className="rounded-xl border border-dashed border-gray-300 bg-white p-10 text-center">
          <ShieldCheck className="mx-auto mb-3 text-gray-300" size={32} aria-hidden />
          <p className="text-sm font-semibold text-gray-700">{t('moderation.empty_title')}</p>
          <p className="mx-auto mt-1 max-w-md text-sm text-gray-500">{t('moderation.empty_body')}</p>
        </div>
      ) : (
        <div className={cn('space-y-3 transition-opacity', isFetching && 'opacity-70')}>
          {items.map((flag) => (
            <ModerationFlagCard key={flag.flag_uuid} flag={flag} orgslug={org?.slug} />
          ))}
          <div className="flex items-center justify-between pt-2">
            <span className="text-xs text-gray-500">
              {t('moderation.showing', { from: offset + 1, to: Math.min(offset + PAGE_SIZE, total), total })}
            </span>
            <div className="flex gap-2">
              <button
                type="button"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                className="rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 disabled:opacity-40"
              >
                {t('moderation.prev')}
              </button>
              <button
                type="button"
                disabled={offset + PAGE_SIZE >= total}
                onClick={() => setOffset(offset + PAGE_SIZE)}
                className="rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 disabled:opacity-40"
              >
                {t('moderation.next')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
