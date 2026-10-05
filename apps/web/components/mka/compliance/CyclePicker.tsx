'use client'
import React from 'react'
import { CalendarDays } from 'lucide-react'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@components/ui/select'
import type { ComplianceCycle } from '@services/mka/compliance.types'
import { deadlineLabel, fmtDate } from './format'

/**
 * Cycle picker. The frozen contract has no "list cycles" endpoint, so the list
 * is optional (`ScopeResponse.cycles`, tolerated when present). With one or no
 * known cycle this degrades to a read-only label that still shows the deadline.
 */
export function CyclePicker({
  cycle,
  cycles,
  onChange,
  today,
}: {
  cycle: ComplianceCycle
  cycles?: ComplianceCycle[]
  onChange: (id: number) => void
  today: string
}) {
  const many = (cycles?.length ?? 0) > 1
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
      {many ? (
        <Select value={String(cycle.id)} onValueChange={(v) => onChange(Number(v))}>
          <SelectTrigger aria-label="Compliance cycle" className="h-9 w-40 bg-white">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {cycles!.map((c) => (
              <SelectItem key={c.id} value={String(c.id)}>
                Cycle {c.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      ) : (
        <span className="inline-flex h-9 items-center rounded-md bg-white px-3 text-sm font-medium text-gray-800 nice-shadow">
          Cycle {cycle.label}
        </span>
      )}
      <span className="inline-flex items-center gap-1.5 text-sm text-gray-500">
        <CalendarDays aria-hidden="true" className="size-4" />
        Deadline {fmtDate(cycle.deadline_on)}
        <span className="text-gray-400">&middot; {deadlineLabel(cycle.deadline_on, today)}</span>
      </span>
    </div>
  )
}
