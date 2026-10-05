'use client'
import React, { useCallback, useMemo, useState } from 'react'
import { cn } from '@/lib/utils'
import {
  complianceToday,
  useComplianceScopeQuery,
  useCourseSummary,
} from '@services/mka/compliance'
import type { ComplianceStatus, LearnerFilters, LearnerLevel } from '@services/mka/compliance.types'
import { Breakdown } from './Breakdown'
import { DownloadChaseList } from './ChaseActions'
import { RemindButton } from './RemindDialog'
import { CyclePicker } from './CyclePicker'
import { LearnersPanel } from './LearnersPanel'
import { RagBadge } from './badges'
import { SummaryCards } from './SummaryCards'
import { ErrorState, NoCycleState, NoExpectedState, PageLoading } from './states'
import { deptLabel, isStatus, nz, sameCourse } from './format'

const KINDS = { general: 'General course', department: 'Department course' } as const

/**
 * Body of the course "Compliance" tab (hook H3). Shows ONLY this course: the
 * API returns 404 for anything outside the viewer's scope, which renders the
 * generic "nothing to show" state, never a different course's numbers.
 */
export default function MkaCourseComplianceTab({ courseUUID }: { courseUUID: string }) {
  const [cycleId, setCycleId] = useState<number | null>(null)
  // One-time deep link from the org page heatmap (?region=&status=). Values are only
  // used as filter inputs, validated here and URL-encoded again on the way out.
  const [filters, setFilters] = useState<LearnerFilters>(() => {
    const sp = typeof window === 'undefined' ? new URLSearchParams() : new URLSearchParams(window.location.search)
    const status = sp.get('status')
    const region = sp.get('region')
    return { status: isStatus(status) ? status : '', region: region ? region.slice(0, 80) : '', majlis: '', level: '', q: '' }
  })
  const today = complianceToday()

  const patch = useCallback((p: Partial<LearnerFilters>) => setFilters((f) => ({ ...f, ...p })), [])

  const scope = useComplianceScopeQuery(cycleId)
  const summary = useCourseSummary(courseUUID, cycleId)
  const data = summary.data

  const course = useMemo(
    () => scope.data?.courses.find((c) => sameCourse(c.course_uuid, courseUUID)),
    [scope.data, courseUUID],
  )
  const levels = useMemo(() => (data?.by_level ?? []).map((l) => l.level as LearnerLevel), [data])

  if (summary.isPending) return <div className="px-4 py-6 sm:px-10"><PageLoading /></div>
  if (summary.error || !data) return <div className="px-4 sm:px-10"><ErrorState error={summary.error} onRetry={() => void summary.refetch()} /></div>
  if (!data.cycle) return <div className="px-4 sm:px-10"><NoCycleState /></div>

  const name = data.course?.name ?? course?.name ?? 'Course'
  const kind = data.course?.kind ?? course?.kind
  const fetching = summary.isFetching && !summary.isLoading

  return (
    <div className="space-y-5 px-4 pb-10 pt-6 sm:px-10" aria-busy={fetching}>
      <header className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0 space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-xl font-bold tracking-tight text-gray-900">Compliance</h2>
            <RagBadge rag={data.rag} />
            {kind ? (
              <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600">{KINDS[kind]}</span>
            ) : null}
          </div>
          <p className="text-sm text-gray-500">
            {name}
            {nz(data.course?.department) ? ` · ${deptLabel(data.course?.department, data.course?.department_name)}` : ''}
          </p>
          {data.reasons?.length ? <p className="text-sm text-gray-700">{data.reasons.join(' \u00b7 ')}</p> : null}
          <CyclePicker cycle={data.cycle} cycles={scope.data?.cycles} onChange={setCycleId} today={today} />
        </div>
        <div className={cn('flex flex-col gap-2 sm:flex-row sm:items-start')}>
          <RemindButton courseUuid={courseUUID} courseName={name} cycleId={data.cycle.id} disabled={data.totals.expected === 0} />
          <DownloadChaseList
            courseUuid={courseUUID}
            courseName={name}
            filters={filters}
            cycleId={data.cycle.id}
            disabled={data.totals.expected === 0}
          />
        </div>
      </header>

      {data.totals.expected === 0 ? (
        <NoExpectedState label={data.cycle.label} />
      ) : (
        <>
          <SummaryCards
            totals={data.totals}
            selected={(filters.status as ComplianceStatus | '') ?? ''}
            onSelect={(s) => patch({ status: s })}
            showChaseCallout
          />
          <Breakdown
            byRegion={data.by_region}
            byMajlis={data.by_majlis}
            region={filters.region ?? ''}
            majlis={filters.majlis ?? ''}
            onRegion={(v) => patch({ region: v })}
            onMajlis={(v) => patch({ majlis: v })}
          />
          <LearnersPanel
            courseUuid={courseUUID}
            cycleId={data.cycle.id}
            totals={data.totals}
            byRegion={data.by_region}
            byMajlis={data.by_majlis}
            levels={levels}
            filters={filters}
            onFilters={patch}
          />
        </>
      )}
    </div>
  )
}
