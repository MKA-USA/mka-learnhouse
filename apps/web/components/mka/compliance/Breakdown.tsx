'use client'
import React, { useMemo, useState } from 'react'
import { cn } from '@/lib/utils'
import type { ComplianceCounts, MajlisRow, RegionRow } from '@services/mka/compliance.types'
import { RAG_ICON, RAG_TONE, StatusBar, TONE_CLASS } from './badges'
import { RAG_META, attestedPct, chaseTotal, fmtPct, safeRag } from './format'

const MAJLIS_INITIAL = 8

function Row({
  label,
  sub,
  counts,
  rag,
  active,
  onClick,
}: {
  label: string
  sub?: string | null
  counts: ComplianceCounts
  rag?: RegionRow['rag']
  active: boolean
  onClick: () => void
}) {
  const r = safeRag(rag)
  const Icon = RAG_ICON[r]
  const chase = chaseTotal(counts)
  return (
    <li>
      <button
        type="button"
        onClick={onClick}
        aria-pressed={active}
        className={cn(
          'grid w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1.5 rounded-lg px-2.5 py-2 text-start transition-colors',
          'hover:bg-gray-50 focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring',
          active && 'bg-gray-100',
        )}
      >
        <span className="flex min-w-0 items-center gap-2">
          {rag ? (
            <span className={cn('inline-flex shrink-0', TONE_CLASS[RAG_TONE[r]].text)}>
              <Icon aria-hidden="true" className="size-4" />
              <span className="sr-only">{RAG_META[r].label}: </span>
            </span>
          ) : null}
          <span className="truncate text-sm font-medium text-gray-900">{label}</span>
          {sub ? <span className="hidden truncate text-xs text-gray-400 sm:inline">{sub}</span> : null}
        </span>
        <span className="text-end text-xs tabular-nums text-gray-500">
          <span className="font-semibold text-gray-800">{fmtPct(attestedPct(counts))}</span> attested
          {chase > 0 ? <span> &middot; {chase} to chase</span> : null}
        </span>
        <StatusBar counts={counts} className="col-span-2 h-1.5" />
      </button>
    </li>
  )
}

/** By-region and by-Majlis breakdown; selecting a row filters the learners table below. */
export function Breakdown({
  byRegion,
  byMajlis,
  region,
  majlis,
  onRegion,
  onMajlis,
}: {
  byRegion: RegionRow[]
  byMajlis: MajlisRow[]
  region: string
  majlis: string
  onRegion: (v: string) => void
  onMajlis: (v: string) => void
}) {
  const [showAll, setShowAll] = useState(false)
  // Most chasing first, so the head sees problem Majalis without scrolling.
  const majalis = useMemo(
    () =>
      [...byMajlis]
        .filter((m) => !region || m.region === region)
        .sort((a, b) => chaseTotal(b) - chaseTotal(a) || a.majlis.localeCompare(b.majlis)),
    [byMajlis, region],
  )
  const regions = useMemo(
    () => [...byRegion].sort((a, b) => chaseTotal(b) - chaseTotal(a) || a.region.localeCompare(b.region)),
    [byRegion],
  )
  const shown = showAll ? majalis : majalis.slice(0, MAJLIS_INITIAL)

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <section aria-labelledby="by-region-title" className="rounded-xl bg-white p-4 nice-shadow sm:p-5">
        <h2 id="by-region-title" className="text-base font-bold text-gray-900">
          By region
        </h2>
        <p className="mb-2 text-sm text-gray-500">Most people to chase first. Select one to filter the list.</p>
        {regions.length === 0 ? (
          <p className="py-4 text-sm text-gray-500">No regional breakdown for this course.</p>
        ) : (
          <ul className="space-y-0.5">
            {regions.map((r) => (
              <Row
                key={r.region}
                label={r.region}
                counts={r}
                rag={r.rag}
                active={region === r.region}
                onClick={() => {
                  onRegion(region === r.region ? '' : r.region)
                  onMajlis('')
                }}
              />
            ))}
          </ul>
        )}
      </section>
      <section aria-labelledby="by-majlis-title" className="rounded-xl bg-white p-4 nice-shadow sm:p-5">
        <h2 id="by-majlis-title" className="text-base font-bold text-gray-900">
          By Majlis{region ? ` in ${region}` : ''}
        </h2>
        <p className="mb-2 text-sm text-gray-500">Where the most follow-up is needed.</p>
        {majalis.length === 0 ? (
          <p className="py-4 text-sm text-gray-500">No Majlis-level officeholders for this course.</p>
        ) : (
          <ul className="space-y-0.5">
            {shown.map((m) => (
              <Row
                key={m.majlis}
                label={m.majlis}
                sub={m.region}
                counts={m}
                rag={m.rag}
                active={majlis === m.majlis}
                onClick={() => onMajlis(majlis === m.majlis ? '' : m.majlis)}
              />
            ))}
          </ul>
        )}
        {majalis.length > MAJLIS_INITIAL ? (
          <button
            type="button"
            onClick={() => setShowAll((v) => !v)}
            aria-expanded={showAll}
            className="mt-2 rounded-md px-2 py-1 text-sm font-medium text-gray-600 hover:bg-gray-100 focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
          >
            {showAll ? 'Show fewer' : `Show all ${majalis.length} Majalis`}
          </button>
        ) : null}
      </section>
    </div>
  )
}
