'use client'
import React, { useState } from 'react'
import Link from 'next/link'
import { ArrowRight, CircleCheck } from 'lucide-react'
import type { AttentionItem, ScopeCourse } from '@services/mka/compliance.types'
import { RagBadge } from './badges'
import { attentionTitle, safeRag } from './format'
import { courseTabHref } from './links'

const INITIAL = 6

/** Ranked "Needs attention": what's wrong, in words, with a way in. Server order is kept (it ranks). */
export function AttentionList({
  items,
  courses,
  orgslug,
}: {
  items: AttentionItem[]
  courses: ScopeCourse[]
  orgslug: string
}) {
  const [all, setAll] = useState(false)
  const shown = all ? items : items.slice(0, INITIAL)
  const courseOf = (dept: string) => courses.find((c) => c.kind === 'department' && c.department === dept)

  return (
    <section aria-labelledby="attention-title" className="rounded-xl bg-white p-4 nice-shadow sm:p-5">
      <div className="mb-3">
        <h2 id="attention-title" className="text-base font-bold text-gray-900">
          Needs attention
        </h2>
        <p className="text-sm text-gray-500">Ranked: the places most behind the expected pace, with why.</p>
      </div>
      {items.length === 0 ? (
        <p className="flex items-center gap-2 rounded-lg bg-emerald-50 px-3 py-3 text-sm text-emerald-900">
          <CircleCheck aria-hidden="true" className="size-4" />
          Nothing needs attention right now.
        </p>
      ) : (
        <ol className="divide-y divide-gray-100">
          {shown.map((a, i) => {
            const course = courseOf(a.department)
            return (
              <li key={`${a.department}:${a.region ?? ''}`} className="flex flex-wrap items-start gap-x-3 gap-y-1 py-3 sm:flex-nowrap">
                <span aria-hidden="true" className="mt-0.5 w-5 shrink-0 text-end text-xs font-semibold tabular-nums text-gray-400">
                  {i + 1}
                </span>
                <div className="min-w-0 flex-1 basis-[calc(100%-2rem)] sm:basis-auto">
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    <span className="font-semibold text-gray-900">{attentionTitle(a)}</span>
                    <RagBadge rag={safeRag(a.rag)} size="sm" />
                  </div>
                  {a.reasons?.length ? (
                    <p className="mt-1 text-sm text-gray-600">{a.reasons.join(' \u00b7 ')}</p>
                  ) : null}
                </div>
                {course ? (
                  <Link
                    href={courseTabHref(orgslug, course.course_uuid, { region: a.region ?? undefined })}
                    className="ms-8 inline-flex shrink-0 items-center gap-1 rounded-md px-2 py-1 sm:ms-0 text-sm font-medium text-gray-700 hover:bg-gray-100 focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
                    aria-label={`Open ${attentionTitle(a)} chase list`}
                  >
                    Who to chase
                    <ArrowRight aria-hidden="true" className="size-4" />
                  </Link>
                ) : null}
              </li>
            )
          })}
        </ol>
      )}
      {items.length > INITIAL ? (
        <button
          type="button"
          onClick={() => setAll((v) => !v)}
          aria-expanded={all}
          className="mt-2 rounded-md px-2 py-1 text-sm font-medium text-gray-600 hover:bg-gray-100 focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
        >
          {all ? 'Show fewer' : `Show all ${items.length}`}
        </button>
      ) : null}
    </section>
  )
}
