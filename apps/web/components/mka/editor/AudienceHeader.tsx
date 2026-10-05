// PLACEHOLDER — replaced by seam c
'use client'
import React from 'react'
import type { AudienceWarning, CountState, Rule } from '../audience/types'

export type AudienceHeaderProps = {
  rule: Rule
  label: string
  count: CountState
  onEdit?: () => void
  onPreview?: () => void
  onToggleCollapse: () => void
  collapsed: boolean
  blockCount: number
  warnings: AudienceWarning[]
}

export function AudienceHeader({ label, count, onEdit, onPreview, onToggleCollapse, collapsed, blockCount, warnings }: AudienceHeaderProps) {
  return (
    <div data-testid="mka-audience-header" className="flex items-center gap-2 border-l-4 border-slate-400 px-2 py-1 text-xs">
      <span>Visible to: {label}</span>
      {count.state === 'ready' && count.data && <span>≈{count.data.count}</span>}
      {warnings.map((w) => (
        <span key={w.kind} role="alert">{w.kind}</span>
      ))}
      {onEdit && <button type="button" onClick={onEdit}>Edit</button>}
      {onPreview && <button type="button" onClick={onPreview}>Preview</button>}
      <button type="button" onClick={onToggleCollapse} aria-expanded={!collapsed}>
        {collapsed ? `${blockCount} blocks hidden` : 'Collapse'}
      </button>
    </div>
  )
}

export default AudienceHeader
