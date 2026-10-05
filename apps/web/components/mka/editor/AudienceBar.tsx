'use client'
// MKA fork — sticky "Viewing: …" bar at the top of the editor scroll area (design spec B1.4, contract §3.5).
import * as React from 'react'
import { Eye, ScanEye, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { AudienceOptions, AudienceView, Persona } from '../audience/types'
import { FOCUS_RING, PRESS, TARGET } from './audience-ui'
import { PreviewMenu, type PreviewPerson } from './PreviewMenu'

export type AudienceBarProps = {
  sectionCount: number
  view: AudienceView
  onChangeView(view: AudienceView): void
  personas: Persona[]
  canPickPerson: boolean
  searchPeople?(q: string): Promise<PreviewPerson[]>
  pickPerson?(id: number | string): void | Promise<unknown>
  options: AudienceOptions | undefined
}

export function AudienceBar({ sectionCount, view, onChangeView, personas, canPickPerson, searchPeople, pickPerson, options }: AudienceBarProps) {
  if (sectionCount <= 0) return null
  const previewing = view.kind !== 'author'
  return (
    <div
      role="region"
      aria-label="Audience preview"
      style={{ zIndex: 'var(--z-sticky-header)' }}
      className={cn(
        'sticky top-0 flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-gray-200 px-3 py-2 backdrop-blur transition-colors duration-200 motion-reduce:transition-none',
        previewing ? 'border-amber-300 bg-amber-50/95 text-amber-950' : 'bg-white/95',
      )}
    >
      <span aria-hidden className="hidden text-gray-600 sm:inline">
        {previewing ? <ScanEye className="size-4" /> : <Eye className="size-4" />}
      </span>
      <PreviewMenu view={view} onChangeView={onChangeView} personas={personas} canPickPerson={canPickPerson} searchPeople={searchPeople} pickPerson={pickPerson} options={options} />
      <p className="text-sm text-gray-600">
        {sectionCount} audience {sectionCount === 1 ? 'section' : 'sections'}
      </p>
      {previewing ? (
        <div className="ms-auto flex items-center gap-2" aria-live="polite">
          <button
            type="button"
            onClick={() => onChangeView({ kind: 'author' })}
            className={cn('inline-flex items-center gap-1.5 rounded-full bg-amber-900 px-4 text-sm font-semibold text-amber-50 hover:bg-amber-800', TARGET, PRESS, FOCUS_RING)}
          >
            <X className="size-4" aria-hidden />
            Exit preview
          </button>
        </div>
      ) : null}
    </div>
  )
}

export default AudienceBar
