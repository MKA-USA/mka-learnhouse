'use client'
import React from 'react'
import { cn } from '@/lib/utils'
import type { ComplianceCounts, ComplianceStatus } from '@services/mka/compliance.types'
import { StatusBar, StatusLegend, STATUS_ICON, TONE_CLASS } from './badges'
import { STATUS_META, chaseTotal, fmtPct, pctOf } from './format'

const CARD_ORDER: ComplianceStatus[] = ['attested', 'completed', 'in_progress', 'not_started', 'not_signed_in', 'overdue']

/**
 * Totals as scannable tiles plus one stacked bar. With `onSelect`, tiles act as
 * status filters (aria-pressed); without it they are plain read-only tiles.
 */
export function SummaryCards({
  totals,
  selected,
  onSelect,
  showChaseCallout = false,
}: {
  totals: ComplianceCounts
  selected?: ComplianceStatus | ''
  onSelect?: (s: ComplianceStatus | '') => void
  showChaseCallout?: boolean
}) {
  const chase = chaseTotal(totals)
  return (
    <section aria-label="Cycle totals" className="space-y-3">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-7">
        <div className="col-span-2 rounded-xl bg-white p-4 nice-shadow sm:col-span-3 lg:col-span-1">
          <div className="text-xs font-medium text-gray-500">Expected</div>
          <div className="mt-1 text-2xl font-bold tracking-tight tabular-nums text-gray-900">{totals.expected}</div>
          <div className="mt-0.5 text-xs text-gray-400">officeholders</div>
        </div>
        {CARD_ORDER.map((s) => {
          const meta = STATUS_META[s]
          const Icon = STATUS_ICON[s]
          const n = totals[s]
          const body = (
            <>
              <div className={cn('flex items-center gap-1.5 text-xs font-medium', TONE_CLASS[meta.tone].text)}>
                <Icon aria-hidden="true" className="size-3.5" />
                {meta.label}
              </div>
              <div className="mt-1 text-2xl font-bold tracking-tight tabular-nums text-gray-900">{n}</div>
              <div className="mt-0.5 text-xs text-gray-400">{fmtPct(pctOf(n, totals.expected))} of expected</div>
            </>
          )
          const base = 'rounded-xl bg-white p-4 text-start nice-shadow'
          return onSelect ? (
            <button
              key={s}
              type="button"
              aria-pressed={selected === s}
              onClick={() => onSelect(selected === s ? '' : s)}
              className={cn(
                base,
                'transition-shadow hover:shadow-lg focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring',
                selected === s && 'ring-2 ring-gray-900',
              )}
            >
              {body}
            </button>
          ) : (
            <div key={s} className={base}>
              {body}
            </div>
          )
        })}
      </div>
      <div className="rounded-xl bg-white p-4 nice-shadow">
        <StatusBar counts={totals} />
        <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <StatusLegend />
          {showChaseCallout && chase > 0 ? (
            <p className="text-sm font-medium text-gray-800">
              {chase} {chase === 1 ? 'person needs' : 'people need'} a nudge
              <span className="font-normal text-gray-500">
                {' '}
                ({totals.overdue} overdue, {totals.not_signed_in} not signed in, {totals.not_started} not started)
              </span>
            </p>
          ) : null}
        </div>
      </div>
    </section>
  )
}
