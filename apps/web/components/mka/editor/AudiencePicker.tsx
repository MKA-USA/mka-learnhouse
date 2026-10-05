// PLACEHOLDER — replaced by seam c
'use client'
import React from 'react'
import type { AudienceOptions, CountState, Rule } from '../audience/types'

export type AudiencePickerProps = {
  value: Rule
  onChange: (rule: Rule) => void
  onDone: () => void
  onCancel: () => void
  onRemove?: () => void
  options: AudienceOptions | undefined
  authorDepartment: string | null
  count: CountState
  isNew: boolean
}

export function AudiencePicker({ value, onChange, onDone, onCancel, onRemove, options }: AudiencePickerProps) {
  const group = value.groups[0] ?? {}
  const levels = (group.level as string[] | undefined) ?? []
  const departments = (group.department as string[] | undefined) ?? []
  const toggle = (key: 'level' | 'department', v: string, cur: string[]) => {
    const next = cur.includes(v) ? cur.filter((x) => x !== v) : [...cur, v]
    const g = { ...group }
    if (next.length) g[key] = next
    else delete g[key]
    onChange({ ...value, groups: [g, ...value.groups.slice(1)] })
  }
  if (!options) return <div role="status">Loading…</div>
  return (
    <div data-testid="mka-audience-picker" className="space-y-2 text-sm">
      <p className="font-medium">Who should see this?</p>
      <div className="flex flex-wrap gap-2">
        {options.levels.map((l) => (
          <label key={l.key} className="flex items-center gap-1">
            <input type="checkbox" checked={levels.includes(l.key)} onChange={() => toggle('level', l.key, levels)} />
            {l.label}
          </label>
        ))}
      </div>
      <div className="flex max-h-32 flex-wrap gap-2 overflow-auto">
        {options.departments.map((d) => (
          <label key={d.key} className="flex items-center gap-1">
            <input type="checkbox" checked={departments.includes(d.key)} onChange={() => toggle('department', d.key, departments)} />
            {d.name}
          </label>
        ))}
      </div>
      <div className="flex gap-2">
        <button type="button" onClick={onCancel}>Cancel</button>
        {onRemove && <button type="button" onClick={onRemove}>Remove section</button>}
        <button type="button" onClick={onDone}>Done</button>
      </div>
    </div>
  )
}

export default AudiencePicker
