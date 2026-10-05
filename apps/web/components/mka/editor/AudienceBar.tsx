'use client'
// MKA fork — sticky "Viewing: …" bar at the top of the editor scroll area (design spec B1.4, contract §3.5).
import * as React from 'react'
import { Eye, ScanEye, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { AudienceOptions, AudienceView, Persona } from '../audience/types'
import { FOCUS_RING, PRESS, TARGET } from './audience-ui'
import { PreviewMenu, viewLabel, type PreviewPerson } from './PreviewMenu'

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
        'sticky top-0 flex flex-wrap items-center gap-x-3 gap-y-2 border-b px-3 py-2 backdrop-blur transition-colors duration-200 motion-reduce:transition-none',
        previewing ? 'border-amber-300 bg-amber-50/95 text-amber-950 dark:border-amber-700 dark:bg-amber-950/90 dark:text-amber-50' : 'bg-background/95',
      )}
    >
      <span aria-hidden className="hidden text-muted-foreground sm:inline">
        {previewing ? <ScanEye className="size-4" /> : <Eye className="size-4" />}
      </span>
      <PreviewMenu view={view} onChangeView={onChangeView} personas={personas} canPickPerson={canPickPerson} searchPeople={searchPeople} pickPerson={pickPerson} options={options} />
      <p className="text-sm text-muted-foreground">
        {sectionCount} audience {sectionCount === 1 ? 'section' : 'sections'}
      </p>
      {previewing ? (
        <div className="ms-auto flex items-center gap-2" aria-live="polite">
          <span className="hidden text-sm font-medium sm:inline">Previewing as {viewLabel(view)}</span>
          <button
            type="button"
            onClick={() => onChangeView({ kind: 'author' })}
            className={cn('inline-flex items-center gap-1.5 rounded-full bg-amber-900 px-4 text-sm font-semibold text-amber-50 hover:bg-amber-800 dark:bg-amber-100 dark:text-amber-950 dark:hover:bg-amber-200', TARGET, PRESS, FOCUS_RING)}
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
