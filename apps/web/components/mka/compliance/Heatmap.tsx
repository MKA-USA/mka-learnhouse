'use client'
import React, { useMemo } from 'react'
import Link from 'next/link'
import { cn } from '@/lib/utils'
import type { CellRow, ComplianceRag, DepartmentRow, ScopeCourse } from '@services/mka/compliance.types'
import { RAG_ICON, RagBadge } from './badges'
import { RAG_META, attestedPct, buildHeatmap, cellLabel, chaseTotal, fmtPct, safeRag } from './format'
import { courseTabHref } from './links'

const CELL_TONE: Record<ComplianceRag, string> = {
  red: 'bg-red-50 text-red-900 ring-red-200 hover:bg-red-100',
  amber: 'bg-amber-50 text-amber-900 ring-amber-200 hover:bg-amber-100',
  green: 'bg-emerald-50 text-emerald-900 ring-emerald-200 hover:bg-emerald-100',
  none: 'bg-gray-50 text-gray-400 ring-gray-100',
}

function Cell({
  department,
  region,
  cell,
  href,
}: {
  department: string
  region: string
  cell: CellRow | undefined
  href: string | null
}) {
  if (!cell || !cell.expected) {
    return (
      <span className="flex h-12 items-center justify-center text-sm text-gray-300" aria-label={cellLabel(department, region, cell)}>
        &ndash;
      </span>
    )
  }
  const rag = safeRag(cell.rag)
  const Icon = RAG_ICON[rag]
  const classes = cn(
    'flex h-12 w-full flex-col items-center justify-center gap-0.5 rounded-md text-xs font-semibold ring-1 ring-inset transition-colors',
    'focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring',
    CELL_TONE[rag],
  )
  const inner = (
    <>
      <span className="inline-flex items-center gap-1">
        <Icon aria-hidden="true" className="size-3.5" />
        <span className="tabular-nums">{fmtPct(attestedPct(cell))}</span>
      </span>
      <span className="sr-only">{RAG_META[rag].label}</span>
      <span aria-hidden="true" className="text-[10px] font-medium opacity-70">
        {cell.overdue ? `${cell.overdue} overdue` : `${cell.expected} exp.`}
      </span>
    </>
  )
  const label = cellLabel(department, region, cell)
  const title = cell.reasons?.length ? `${label}. ${cell.reasons.join('; ')}` : label
  return href ? (
    <Link href={href} className={classes} aria-label={label} title={title}>
      {inner}
    </Link>
  ) : (
    <span className={classes} aria-label={label} title={title}>
      {inner}
    </span>
  )
}

/** Department x region heatmap. A real <table>: row/column headers, RAG as icon + label + number, never colour alone. */
export function Heatmap({
  departments,
  cells,
  courses,
  orgslug,
}: {
  departments: DepartmentRow[]
  cells: CellRow[]
  courses: ScopeCourse[]
  orgslug: string
}) {
  const map = useMemo(() => buildHeatmap(departments, cells), [departments, cells])
  const courseOf = (dept: string) => courses.find((c) => c.kind === 'department' && c.department === dept)

  return (
    <section aria-labelledby="heatmap-title" className="rounded-xl bg-white p-4 nice-shadow sm:p-5">
      <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h2 id="heatmap-title" className="text-base font-bold text-gray-900">
            Department by region
          </h2>
          <p className="text-sm text-gray-500">Share attested in each cell. Worst departments first; select a cell to see who to chase.</p>
        </div>
        <ul className="flex flex-wrap gap-1.5" aria-label="Legend">
          {(['red', 'amber', 'green'] as ComplianceRag[]).map((r) => (
            <li key={r}>
              <RagBadge rag={r} size="sm" />
            </li>
          ))}
        </ul>
      </div>
      <div className="-mx-4 overflow-x-auto px-4 sm:-mx-5 sm:px-5">
        <table className="w-full min-w-[960px] border-separate border-spacing-x-1 border-spacing-y-1 text-sm">
          <caption className="sr-only">
            Attested share by department and region. Each cell shows the RAG status, the attested percentage and the overdue count.
          </caption>
          <thead>
            <tr>
              <th scope="col" className="sticky start-0 z-10 w-48 bg-white pb-1 text-start text-xs font-medium text-gray-500">
                Department
              </th>
              <th scope="col" className="w-20 pb-1 text-center text-xs font-medium text-gray-500">
                All regions
              </th>
              {map.regions.map((r) => (
                <th key={r} scope="col" className="pb-1 text-center text-xs font-medium leading-tight text-gray-500">
                  {r}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {map.rows.map((row) => {
              const course = courseOf(row.department)
              const s = row.summary
              return (
                <tr key={row.department}>
                  <th scope="row" className="sticky start-0 z-10 bg-white pe-2 text-start align-middle font-medium text-gray-900">
                    <div className="flex flex-col">
                      {course ? (
                        <Link
                          href={courseTabHref(orgslug, course.course_uuid)}
                          className="rounded-sm underline-offset-2 hover:underline focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring"
                        >
                          {row.department}
                        </Link>
                      ) : (
                        row.department
                      )}
                      {s ? (
                        <span className="text-xs font-normal text-gray-500">
                          {chaseTotal(s)} to chase &middot; {s.expected} expected
                        </span>
                      ) : null}
                    </div>
                  </th>
                  <td className="align-middle">
                    {s ? (
                      <Cell
                        department={row.department}
                        region="all regions"
                        cell={{ ...s, region: 'all regions' }}
                        href={course ? courseTabHref(orgslug, course.course_uuid) : null}
                      />
                    ) : null}
                  </td>
                  {map.regions.map((region) => (
                    <td key={region} className="align-middle">
                      <Cell
                        department={row.department}
                        region={region}
                        cell={row.cells[region]}
                        href={course && row.cells[region]?.expected ? courseTabHref(orgslug, course.course_uuid, { region }) : null}
                      />
                    </td>
                  ))}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </section>
  )
}
