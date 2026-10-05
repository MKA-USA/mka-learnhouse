'use client'
import React, { useEffect, useState } from 'react'
import { ChevronLeft, ChevronRight, Search, TriangleAlert } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Input } from '@components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@components/ui/table'
import { useLearners } from '@services/mka/compliance'
import type {
  ComplianceCounts,
  ComplianceStatus,
  LearnerFilters,
  LearnerItem,
  LearnerLevel,
  MajlisRow,
  RegionRow,
} from '@services/mka/compliance.types'
import { StatusChip } from './badges'
import { ErrorState } from './states'
import { STATUS_META, STATUS_ORDER, fmtDate, lessonProgress } from './format'

const PAGE_SIZE = 25
const ALL = '__all__'
const LEVEL_LABEL: Record<LearnerLevel, string> = { national: 'National', regional: 'Regional', local: 'Local' }

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return v
}

function FilterSelect({
  label,
  value,
  onChange,
  options,
  allLabel,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  options: { value: string; label: string }[]
  allLabel: string
}) {
  return (
    <Select value={value || ALL} onValueChange={(v) => onChange(v === ALL ? '' : v)}>
      <SelectTrigger aria-label={label} className="h-9 w-full bg-white sm:w-44">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={ALL}>{allLabel}</SelectItem>
        {options.map((o) => (
          <SelectItem key={o.value} value={o.value}>
            {o.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

function Progress({ done, total }: { done: number; total: number }) {
  const p = lessonProgress(done, total)
  return (
    <div className="flex items-center gap-2">
      <div
        role="progressbar"
        aria-label="Lessons completed"
        aria-valuemin={0}
        aria-valuemax={total}
        aria-valuenow={done}
        className="h-1.5 w-16 overflow-hidden rounded-full bg-gray-100"
      >
        <div className="h-full rounded-full bg-gray-700" style={{ width: `${p.pct}%` }} />
      </div>
      <span className="text-xs tabular-nums text-gray-500">{p.label}</span>
    </div>
  )
}

function PersonCell({ l }: { l: LearnerItem }) {
  const where = [l.majlis, l.region].filter(Boolean).join(' · ')
  return (
    <div className="min-w-0">
      <div className="truncate text-sm font-medium text-gray-900">{l.person_name ?? l.email}</div>
      {l.person_name ? <div className="truncate text-xs text-gray-500">{l.email}</div> : null}
      <div className="truncate text-xs text-gray-500">
        {l.role_title}
        {where ? ` · ${where}` : ''}
      </div>
      {l.contact_check.mismatch === true ? (
        <div className="mt-1 inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-900 ring-1 ring-inset ring-amber-200">
          <TriangleAlert aria-hidden="true" className="size-3" />
          Contact details differ from roster
        </div>
      ) : null}
    </div>
  )
}

/** Learners table with status chips, region/Majlis/level selects, debounced search and paging. */
export function LearnersPanel({
  courseUuid,
  cycleId,
  totals,
  byRegion,
  byMajlis,
  levels,
  filters,
  onFilters,
}: {
  courseUuid: string
  cycleId: number | null
  totals: ComplianceCounts
  byRegion: RegionRow[]
  byMajlis: MajlisRow[]
  levels: LearnerLevel[]
  /** Committed filters (status/region/majlis/level) owned by the parent so the summary can drive them. */
  filters: LearnerFilters
  onFilters: (patch: Partial<LearnerFilters>) => void
}) {
  const search = filters.q ?? ''
  const q = useDebounced(search, 300)

  // Any filter change returns to page 1 (page is keyed to the filters it was chosen under).
  const filterKey = [filters.status, filters.region, filters.majlis, filters.level, q].join('|')
  const [pageState, setPageState] = useState({ key: filterKey, page: 1 })
  const page = pageState.key === filterKey ? pageState.page : 1
  const setPage = (fn: (p: number) => number) => setPageState({ key: filterKey, page: fn(page) })

  const query: LearnerFilters = { ...filters, q, page, page_size: PAGE_SIZE }
  const { data, error, isLoading, isFetching, refetch } = useLearners(courseUuid, query, cycleId)
  const total = data?.total ?? 0
  const from = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1
  const to = Math.min(total, page * PAGE_SIZE)
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  const majlisOptions = byMajlis
    .filter((m) => !filters.region || m.region === filters.region)
    .map((m) => ({ value: m.majlis, label: m.majlis }))
    .sort((a, b) => a.label.localeCompare(b.label))

  return (
    <section aria-labelledby="learners-title" className="rounded-xl bg-white p-4 nice-shadow sm:p-5">
      <h2 id="learners-title" className="text-base font-bold text-gray-900">
        Learners
      </h2>
      <p className="mb-3 text-sm text-gray-500">Everyone expected to complete this course, including people who have never signed in.</p>

      <div className="mb-3 flex flex-wrap gap-1.5" role="group" aria-label="Filter by status">
        <button
          type="button"
          aria-pressed={!filters.status}
          onClick={() => onFilters({ status: '' })}
          className={cn(
            'rounded-full px-3 py-1 text-xs font-medium ring-1 ring-inset transition-colors focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring',
            !filters.status ? 'bg-gray-900 text-white ring-gray-900' : 'bg-white text-gray-700 ring-gray-200 hover:bg-gray-50',
          )}
        >
          All <span className="tabular-nums opacity-70">{totals.expected}</span>
        </button>
        {STATUS_ORDER.map((s: ComplianceStatus) => (
          <button
            key={s}
            type="button"
            aria-pressed={filters.status === s}
            onClick={() => onFilters({ status: filters.status === s ? '' : s })}
            className={cn(
              'rounded-full px-3 py-1 text-xs font-medium ring-1 ring-inset transition-colors focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring',
              filters.status === s ? 'bg-gray-900 text-white ring-gray-900' : 'bg-white text-gray-700 ring-gray-200 hover:bg-gray-50',
            )}
          >
            {STATUS_META[s].label} <span className="tabular-nums opacity-70">{totals[s]}</span>
          </button>
        ))}
      </div>

      <div className="mb-4 grid grid-cols-1 gap-2 sm:flex sm:flex-wrap sm:items-center">
        <div className="relative sm:w-64">
          <Search aria-hidden="true" className="pointer-events-none absolute start-2.5 top-1/2 size-4 -translate-y-1/2 text-gray-400" />
          <Input
            type="search"
            value={search}
            onChange={(e) => onFilters({ q: e.target.value })}
            placeholder="Search name, email or role"
            aria-label="Search learners"
            maxLength={100}
            className="h-9 bg-white ps-8"
          />
        </div>
        <FilterSelect
          label="Region"
          value={filters.region ?? ''}
          allLabel="All regions"
          options={byRegion.map((r) => ({ value: r.region, label: r.region }))}
          onChange={(v) => onFilters({ region: v, majlis: '' })}
        />
        <FilterSelect
          label="Majlis"
          value={filters.majlis ?? ''}
          allLabel="All Majalis"
          options={majlisOptions}
          onChange={(v) => onFilters({ majlis: v })}
        />
        {levels.length > 1 ? (
          <FilterSelect
            label="Level"
            value={filters.level ?? ''}
            allLabel="All levels"
            options={levels.map((l) => ({ value: l, label: LEVEL_LABEL[l] }))}
            onChange={(v) => onFilters({ level: v as LearnerLevel | '' })}
          />
        ) : null}
      </div>

      {error && !data ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : (
        <div aria-busy={isLoading || isFetching} className={cn('transition-opacity', isFetching && !isLoading && 'opacity-60')}>
          <div className="min-h-[200px] overflow-hidden rounded-lg border border-gray-100">
            <Table>
              <TableHeader>
                <TableRow className="bg-gray-50/70 hover:bg-gray-50/70">
                  <TableHead className="min-w-56">Person</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Progress</TableHead>
                  <TableHead className="hidden md:table-cell">Last activity</TableHead>
                  <TableHead className="hidden lg:table-cell">Attested</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {isLoading
                  ? Array.from({ length: 8 }).map((_, i) => (
                      <TableRow key={i} aria-hidden="true">
                        <TableCell colSpan={5}>
                          <div className="h-9 animate-pulse rounded bg-gray-100" />
                        </TableCell>
                      </TableRow>
                    ))
                  : (data?.items ?? []).map((l) => (
                      <TableRow key={`${l.email}:${l.role_title}:${l.department}`}>
                        <TableCell className="max-w-72 align-top">
                          <PersonCell l={l} />
                        </TableCell>
                        <TableCell className="align-top">
                          <StatusChip status={l.status} />
                        </TableCell>
                        <TableCell className="align-top">
                          <Progress done={l.lessons_done} total={l.lessons_total} />
                        </TableCell>
                        <TableCell className="hidden align-top text-sm text-gray-600 md:table-cell">{fmtDate(l.last_activity_at)}</TableCell>
                        <TableCell className="hidden align-top text-sm text-gray-600 lg:table-cell">{fmtDate(l.attested_at)}</TableCell>
                      </TableRow>
                    ))}
              </TableBody>
            </Table>
            {!isLoading && total === 0 ? (
              <p className="px-4 py-10 text-center text-sm text-gray-500">No learners match these filters.</p>
            ) : null}
          </div>
          <div className="mt-3 flex items-center justify-between gap-3">
            <p className="text-sm text-gray-500" role="status" aria-live="polite">
              {isLoading ? 'Loading\u2026' : total === 0 ? '0 results' : `${from}–${to} of ${total}`}
            </p>
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1}
                aria-label="Previous page"
                className="rounded-md p-1.5 text-gray-600 hover:bg-gray-100 focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-30"
              >
                <ChevronLeft className="size-4" aria-hidden="true" />
              </button>
              <span className="px-1 text-xs tabular-nums text-gray-500">
                {page} / {pages}
              </span>
              <button
                type="button"
                onClick={() => setPage((p) => Math.min(pages, p + 1))}
                disabled={page >= pages}
                aria-label="Next page"
                className="rounded-md p-1.5 text-gray-600 hover:bg-gray-100 focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-30"
              >
                <ChevronRight className="size-4" aria-hidden="true" />
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  )
}
