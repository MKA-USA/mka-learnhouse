// PLACEHOLDER — replaced by seam c
'use client'
import React from 'react'
import type { AudienceOptions, AudienceView, MkaViewerAttributes, Persona } from '../audience/types'

export type AudienceBarProps = {
  sectionCount: number
  view: AudienceView
  onChangeView: (view: AudienceView) => void
  personas: Persona[]
  canPickPerson: boolean
  searchPeople: (q: string) => Promise<{ user_id: number; display_name: string; email: string }[]>
  pickPerson: (id: number) => void
  options: AudienceOptions | undefined
}

export function AudienceBar({ sectionCount, view, onChangeView, personas }: AudienceBarProps) {
  return (
    <div data-testid="mka-audience-bar" className="flex items-center gap-2 border-b px-2 py-1 text-xs">
      <span>Viewing:</span>
      <select
        aria-label="Viewing as"
        value={view.kind === 'persona' ? view.label : view.kind}
        onChange={(e) => {
          const v = e.target.value
          if (v === 'author' || v === 'self') return onChangeView({ kind: v })
          const p = personas.find((x) => x.label === v)
          if (p) onChangeView({ kind: 'persona', label: p.label, attributes: p.attributes as MkaViewerAttributes })
        }}
      >
        <option value="author">Everything (author view)</option>
        <option value="self">As me</option>
        {personas.map((p) => (
          <option key={p.id} value={p.label}>{p.label}</option>
        ))}
      </select>
      <span>{sectionCount} audience sections</span>
    </div>
  )
}

export default AudienceBar
