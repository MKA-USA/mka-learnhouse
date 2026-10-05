'use client'
// MKA fork — header chrome for an audience section (design spec B1.3, contract §3.5).
import * as React from 'react'
import { ChevronDown, CircleAlert, Eye, EyeOff, Pencil, ScanEye, TriangleAlert, Users } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@components/ui/tooltip'
import { isDescribable, levelTone } from '../audience/describe'
import type { AudienceWarning, CountState, Rule } from '../audience/types'
import { FOCUS_RING, HATCH_STYLE, PRESS, TONE_STYLE } from './audience-ui'

export type AudienceHeaderProps = {
  rule: Rule
  label: string
  count: CountState
  /** Omitted when the rule cannot be edited here (written by a newer editor). */
  onEdit?(): void
  onPreview(): void
  onToggleCollapse(): void
  collapsed: boolean
  blockCount: number
  warnings: AudienceWarning[]
}

const WARN_AMBER = 'text-amber-900'
const WARN_RED = 'text-red-800'

export function warningText(w: AudienceWarning): { text: string; tone: 'amber' | 'red' | 'slate' } {
  switch (w.kind) {
    case 'zero': return { text: 'Nobody currently matches this. Check the filters.', tone: 'amber' }
    case 'only_unclassified': return { text: "Only accounts we couldn't classify.", tone: 'amber' }
    case 'unknown_values': return { text: w.values.map((v) => `Unknown: '${v}'`).join(', '), tone: 'red' }
    case 'invalid': return { text: "This section's audience is damaged. Choose who should see it.", tone: 'red' }
    case 'newer_version': return { text: 'Made with a newer editor', tone: 'slate' }
  }
}

export function ColourBar({ rule, className }: { rule: Rule; className?: string }) {
  const tone = levelTone(rule)
  return (
    <span
      aria-hidden
      data-tone={tone}
      className={cn('w-1 shrink-0 self-stretch rounded-full', TONE_STYLE[tone].bar, tone === 'hide' && 'opacity-80', className)}
      style={tone === 'hide' ? HATCH_STYLE : undefined}
    />
  )
}

export function CountBadge({ count }: { count: CountState }) {
  if (count.state === 'idle') return null
  if (count.state === 'loading') {
    return <span aria-label="Counting" className="inline-block h-6 w-12 animate-pulse rounded-full bg-gray-100 motion-reduce:animate-none" />
  }
  if (count.state === 'error' || !count.data) {
    return <span className="rounded-full border border-gray-200 px-2 py-0.5 text-xs text-gray-600">Count unavailable</span>
  }
  const n = count.data.count
  return (
    <span
      aria-label={`About ${n} ${n === 1 ? 'person' : 'people'}`}
      className="inline-flex items-center gap-1 rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium tabular-nums text-gray-900"
    >
      <Users className="size-3" aria-hidden />≈{n}
    </span>
  )
}

function HeaderButton({ icon: Icon, label, onClick, expanded }: { icon: typeof Pencil; label: string; onClick(): void; expanded?: boolean }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-expanded={expanded}
      aria-label={label}
      className={cn(
        'inline-flex items-center justify-center gap-1.5 rounded-md px-2.5 text-sm font-medium text-gray-600 hover:bg-gray-100 hover:text-gray-900',
        'min-h-11 min-w-11 sm:min-h-8 sm:min-w-0',
        PRESS, FOCUS_RING,
      )}
    >
      <Icon className="size-4" aria-hidden />
      <span className="hidden sm:inline">{label}</span>
    </button>
  )
}

export function AudienceHeader({
  rule, label, count, onEdit, onPreview, onToggleCollapse, collapsed, blockCount, warnings,
}: AudienceHeaderProps) {
  const tone = levelTone(rule)
  const hide = isDescribable(rule) && rule.mode === 'hide'
  const Icon = hide ? EyeOff : Eye
  const prefix = hide ? 'Hidden from' : 'Visible to'
  // describeRule says "Everyone except X" for hide rules; the header reads "Hidden from: X" instead.
  const stripped = hide ? label.replace(/^Everyone except /, '') : label
  const shownLabel = stripped.charAt(0).toUpperCase() + stripped.slice(1)
  const fullLabel = `${prefix}: ${shownLabel}`
  return (
    <TooltipProvider delayDuration={400}>
      <div className="flex items-stretch gap-3 border-b border-gray-100 bg-white px-3 py-1.5 text-gray-900">
        <ColourBar rule={rule} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <Tooltip>
              <TooltipTrigger asChild>
                <p className="flex min-w-0 max-w-full flex-1 basis-40 items-start gap-2 text-sm font-medium" title={fullLabel}>
                  <Icon className={cn('mt-0.5 size-4 shrink-0', TONE_STYLE[tone].text)} aria-hidden />
                  <span className="shrink-0 text-gray-600">{prefix}:</span>
                  <span className="line-clamp-2 min-w-0 sm:line-clamp-1">{shownLabel}</span>
                </p>
              </TooltipTrigger>
              <TooltipContent side="bottom" className="max-w-xs bg-white text-gray-900">{fullLabel}</TooltipContent>
            </Tooltip>
            <CountBadge count={count} />
            <div className="ms-auto flex items-center gap-1.5">
              {onEdit ? <HeaderButton icon={Pencil} label="Edit" onClick={onEdit} /> : null}
              <HeaderButton icon={ScanEye} label="Preview" onClick={onPreview} />
              <button
                type="button"
                onClick={onToggleCollapse}
                aria-expanded={!collapsed}
                aria-label={collapsed ? 'Expand section' : 'Collapse section'}
                className={cn('inline-flex min-h-11 min-w-11 items-center justify-center rounded-md hover:bg-gray-100 sm:min-h-8 sm:min-w-8', PRESS, FOCUS_RING)}
              >
                <ChevronDown className={cn('size-4 transition-transform duration-200 ease-out motion-reduce:transition-none', collapsed && '-rotate-90')} aria-hidden />
              </button>
            </div>
          </div>
          {warnings.length > 0 || collapsed ? (
            <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
              {warnings.map((w, i) => {
                const { text, tone: t } = warningText(w)
                const WIcon = t === 'red' ? TriangleAlert : CircleAlert
                return (
                  <p key={i} role={t === 'red' ? 'alert' : undefined} className={cn('flex items-center gap-1.5', t === 'amber' && WARN_AMBER, t === 'red' && WARN_RED, t === 'slate' && 'text-gray-600')}>
                    <WIcon className="size-3.5 shrink-0" aria-hidden />
                    {text}
                  </p>
                )
              })}
              {collapsed ? (
                <p className="text-gray-600">
                  {blockCount} {blockCount === 1 ? 'block' : 'blocks'} hidden
                </p>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>
    </TooltipProvider>
  )
}

/** Dashed stand-in shown when the previewed viewer would not see a section. */
export function HiddenPlaceholder({ label, className }: { label: string; className?: string }) {
  return (
    <div
      role="note"
      className={cn('flex min-h-11 items-center gap-2 rounded-md border border-dashed border-gray-500 px-3 py-2 text-sm text-gray-600', className)}
    >
      <EyeOff className="size-4 shrink-0" aria-hidden />
      <span className="min-w-0">
        <span className="font-medium text-gray-900">Hidden for this viewer</span>
        <span aria-hidden> · </span>
        <span className="sr-only">. </span>
        Visible to {label}
      </span>
    </div>
  )
}

/** Quiet badge for people who can see every section (admins, authors) on the learner page. */
export function ReadOnlyBadge({ rule, label, className }: { rule: Rule; label: string; className?: string }) {
  const tone = levelTone(rule)
  const hide = isDescribable(rule) && rule.mode === 'hide'
  return (
    <div className={cn('inline-flex max-w-full items-center gap-2 rounded-full border border-gray-200 bg-gray-50 py-1 ps-2 pe-3 text-xs', className)}>
      <ColourBarDot tone={tone} />
      <span className="truncate" title={label}>
        <span className="font-medium">{hide ? 'Hidden from' : 'Visible to'}:</span> {label}
        <span className="text-gray-600"> · you can see this because of your role</span>
      </span>
    </div>
  )
}

function ColourBarDot({ tone }: { tone: ReturnType<typeof levelTone> }) {
  return <span aria-hidden className={cn('size-2 shrink-0 rounded-full', TONE_STYLE[tone].text)} style={tone === 'hide' ? HATCH_STYLE : { backgroundColor: 'currentColor' }} />
}

export default AudienceHeader
