'use client'
import React, { useState } from 'react'
import Link from 'next/link'
import { ShieldCheck } from '@phosphor-icons/react'
import { ArrowRight } from 'lucide-react'
import { Breadcrumbs } from '@components/Objects/Breadcrumbs/Breadcrumbs'
import {
  complianceToday,
  useComplianceOverview,
  useComplianceScopeQuery,
  useCourseSummary,
} from '@services/mka/compliance'
import type { ScopeCourse } from '@services/mka/compliance.types'
import { AttentionList } from './AttentionList'
import { CyclePicker } from './CyclePicker'
import { Heatmap } from './Heatmap'
import { RagBadge, StatusBar } from './badges'
import { SummaryCards } from './SummaryCards'
import { ErrorState, NoAccessState, NoCycleState, NoExpectedState, PageLoading } from './states'
import { attestedPct, chaseTotal, fmtPct } from './format'
import { courseTabHref } from './links'

/** Scope `own`: one card per course the viewer authors, each with its own RAG + headline numbers. */
function OwnCourseCard({ course, cycleId, orgslug }: { course: ScopeCourse; cycleId: number | null; orgslug: string }) {
  const { data, isPending: isLoading, error } = useCourseSummary(course.course_uuid, cycleId)
  const chase = data ? chaseTotal(data.totals) : 0
  return (
    <li className="rounded-xl bg-white p-4 nice-shadow sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate text-base font-bold text-gray-900">{course.name}</h3>
          <p className="text-sm text-gray-500">{course.kind === 'general' ? 'General course' : `${course.department ?? 'Department'} course`}</p>
        </div>
        {data ? <RagBadge rag={data.rag} /> : null}
      </div>
      {isLoading ? (
        <div className="mt-4 h-24 animate-pulse rounded-lg bg-gray-100" aria-hidden="true" />
      ) : error || !data ? (
        <p className="mt-4 text-sm text-gray-500">Couldn&apos;t load this course right now.</p>
      ) : data.totals.expected === 0 ? (
        <p className="mt-4 text-sm text-gray-500">0 expected learners in this cycle.</p>
      ) : (
        <>
          <div className="mt-4 flex flex-wrap items-baseline gap-x-6 gap-y-1">
            <p>
              <span className="text-2xl font-bold tabular-nums text-gray-900">{fmtPct(attestedPct(data.totals))}</span>{' '}
              <span className="text-sm text-gray-500">attested of {data.totals.expected}</span>
            </p>
            <p className="text-sm font-medium text-gray-800">
              {chase} to chase
              <span className="font-normal text-gray-500">
                {' '}
                ({data.totals.overdue} overdue, {data.totals.not_signed_in} not signed in, {data.totals.not_started} not started)
              </span>
            </p>
          </div>
          <StatusBar counts={data.totals} className="mt-3" />
          {data.reasons?.length ? <p className="mt-3 text-sm text-gray-600">{data.reasons.join('; ')}</p> : null}
        </>
      )}
      <Link
        href={courseTabHref(orgslug, course.course_uuid)}
        className="mt-4 inline-flex items-center gap-1 rounded-md px-2 py-1 text-sm font-medium text-gray-800 ring-1 ring-inset ring-gray-200 hover:bg-gray-50 focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
      >
        Open chase list
        <ArrowRight aria-hidden="true" className="size-4" />
      </Link>
    </li>
  )
}

function CourseLinks({ courses, orgslug }: { courses: ScopeCourse[]; orgslug: string }) {
  return (
    <section aria-labelledby="courses-title" className="rounded-xl bg-white p-4 nice-shadow sm:p-5">
      <h2 id="courses-title" className="text-base font-bold text-gray-900">
        Courses in this cycle
      </h2>
      <p className="mb-2 text-sm text-gray-500">Open a course for its regional breakdown and chase list.</p>
      <ul className="grid grid-cols-1 gap-x-6 sm:grid-cols-2 xl:grid-cols-3">
        {courses.map((c) => (
          <li key={c.course_uuid} className="border-b border-gray-100 last:border-b-0">
            <Link
              href={courseTabHref(orgslug, c.course_uuid)}
              className="flex items-center justify-between gap-2 rounded-md px-1 py-2 text-sm text-gray-800 hover:bg-gray-50 focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
            >
              <span className="truncate">{c.name}</span>
              <span className="shrink-0 text-xs text-gray-400">{c.kind === 'general' ? 'General' : 'Department'}</span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  )
}

export default function MkaCompliancePage({ orgslug }: { orgslug: string }) {
  const [cycleId, setCycleId] = useState<number | null>(null)
  const today = complianceToday()
  const scopeQ = useComplianceScopeQuery()
  const scope = scopeQ.data?.scope
  const overview = useComplianceOverview(cycleId, scope === 'all')
  // Own scope has no overview endpoint; the cycle comes from the first course summary.
  const firstOwn = scope === 'own' ? scopeQ.data?.courses[0] : undefined
  const ownSummary = useCourseSummary(firstOwn?.course_uuid ?? '', cycleId, !!firstOwn)
  const cycle = scope === 'all' ? overview.data?.cycle : ownSummary.data?.cycle

  let body: React.ReactNode
  if (scopeQ.isPending) body = <PageLoading />
  else if (scopeQ.error) body = <ErrorState error={scopeQ.error} onRetry={() => void scopeQ.refetch()} />
  else if (scope === 'none' || !scopeQ.data) body = <NoAccessState />
  else if (scope === 'all') {
    if (overview.isPending) body = <PageLoading />
    else if (overview.error || !overview.data) {
      body = <ErrorState error={overview.error} onRetry={() => void overview.refetch()} />
    } else if (!overview.data.cycle) body = <NoCycleState />
    else if (overview.data.totals.expected === 0) body = <NoExpectedState label={overview.data.cycle.label} />
    else {
      const o = overview.data
      body = (
        <div className="space-y-5">
          <SummaryCards totals={o.totals} showChaseCallout />
          <AttentionList items={o.attention} courses={scopeQ.data.courses} orgslug={orgslug} />
          <Heatmap departments={o.departments} cells={o.cells} courses={scopeQ.data.courses} orgslug={orgslug} />
          <CourseLinks courses={scopeQ.data.courses} orgslug={orgslug} />
        </div>
      )
    }
  } else if (scopeQ.data.courses.length === 0) {
    body = <NoAccessState />
  } else {
    body = (
      <ul className="space-y-4" aria-label="Your courses">
        {scopeQ.data.courses.map((c) => (
          <OwnCourseCard key={c.course_uuid} course={c} cycleId={cycleId} orgslug={orgslug} />
        ))}
      </ul>
    )
  }

  return (
    <div className="flex h-full w-full flex-col bg-[#f8f8f8]">
      <div className="relative z-10 flex-shrink-0 bg-[#fcfbfc] ps-4 pe-4 tracking-tight nice-shadow sm:ps-10 sm:pe-10">
        <div className="pb-4 pt-6">
          <Breadcrumbs items={[{ label: 'Compliance', href: '/dash/compliance', icon: <ShieldCheck size={14} /> }]} />
        </div>
        <div className="my-2 py-2 pb-5">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
            <div className="flex flex-col space-y-1">
              <h1 className="pt-3 text-4xl font-bold tracking-tighter">Compliance</h1>
              <p className="text-md font-medium text-gray-400">
                {scope === 'own'
                  ? 'Where your courses stand this cycle, and who to chase.'
                  : 'Where each department and region stands this cycle, and who to chase.'}
              </p>
            </div>
            {cycle ? <CyclePicker cycle={cycle} cycles={scopeQ.data?.cycles} onChange={setCycleId} today={today} /> : <div className="h-9" aria-hidden="true" />}
          </div>
        </div>
      </div>
      <div className="h-6 flex-shrink-0" />
      <main className="flex-1 overflow-y-auto overflow-x-hidden px-4 pb-10 sm:px-10" aria-busy={scopeQ.isPending || overview.isFetching}>
        {body}
      </main>
    </div>
  )
}
