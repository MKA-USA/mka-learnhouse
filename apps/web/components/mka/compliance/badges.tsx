import React from 'react'
import {
  BadgeCheck,
  CircleAlert,
  CircleCheck,
  CircleDashed,
  Loader,
  Minus,
  TriangleAlert,
  UserX,
  type LucideIcon,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import type { ComplianceCounts, ComplianceRag, ComplianceStatus } from '@services/mka/compliance.types'
import { RAG_META, STATUS_META, safeRag, segmentsLabel, statusSegments, type Tone } from './format'

/** Tone -> classes. Literal strings so Tailwind can see them. Colour is never the only signal: every use pairs it with an icon and text. */
export const TONE_CLASS: Record<Tone, { chip: string; solid: string; text: string }> = {
  red: { chip: 'bg-red-50 text-red-800 ring-red-200', solid: 'bg-red-500', text: 'text-red-700' },
  amber: { chip: 'bg-amber-50 text-amber-900 ring-amber-200', solid: 'bg-amber-400', text: 'text-amber-800' },
  slate: { chip: 'bg-slate-100 text-slate-700 ring-slate-200', solid: 'bg-slate-400', text: 'text-slate-600' },
  blue: { chip: 'bg-blue-50 text-blue-800 ring-blue-200', solid: 'bg-blue-400', text: 'text-blue-700' },
  teal: { chip: 'bg-teal-50 text-teal-800 ring-teal-200', solid: 'bg-teal-400', text: 'text-teal-700' },
  green: { chip: 'bg-emerald-50 text-emerald-800 ring-emerald-200', solid: 'bg-emerald-600', text: 'text-emerald-700' },
}

export const STATUS_ICON: Record<ComplianceStatus, LucideIcon> = {
  overdue: TriangleAlert,
  not_signed_in: UserX,
  not_started: CircleDashed,
  in_progress: Loader,
  completed: CircleCheck,
  attested: BadgeCheck,
}

export const RAG_TONE: Record<ComplianceRag, Tone> = { red: 'red', amber: 'amber', green: 'green', none: 'slate' }
export const RAG_ICON: Record<ComplianceRag, LucideIcon> = {
  red: TriangleAlert,
  amber: CircleAlert,
  green: CircleCheck,
  none: Minus,
}

const chipBase = 'inline-flex items-center gap-1 rounded-full font-medium ring-1 ring-inset whitespace-nowrap'

export function StatusChip({ status, className }: { status: ComplianceStatus; className?: string }) {
  const meta = STATUS_META[status] ?? STATUS_META.not_started
  const Icon = STATUS_ICON[status] ?? CircleDashed
  return (
    <span className={cn(chipBase, 'px-2 py-0.5 text-xs', TONE_CLASS[meta.tone].chip, className)} title={meta.hint}>
      <Icon aria-hidden="true" className="size-3.5 shrink-0" />
      {meta.label}
    </span>
  )
}

export function RagBadge({ rag, size = 'md', className }: { rag: ComplianceRag; size?: 'sm' | 'md'; className?: string }) {
  const r = safeRag(rag)
  const Icon = RAG_ICON[r]
  return (
    <span
      className={cn(
        chipBase,
        size === 'sm' ? 'px-2 py-0.5 text-xs' : 'px-2.5 py-1 text-xs',
        TONE_CLASS[RAG_TONE[r]].chip,
        className,
      )}
    >
      <Icon aria-hidden="true" className="size-3.5 shrink-0" />
      {RAG_META[r].label}
    </span>
  )
}

/** Stacked status bar. Announced as one image with its numbers; segments are not individually focusable. */
export function StatusBar({ counts, className }: { counts: ComplianceCounts; className?: string }) {
  const segs = statusSegments(counts)
  return (
    <div
      role="img"
      aria-label={segmentsLabel(counts)}
      className={cn('flex h-2 w-full overflow-hidden rounded-full bg-gray-100', className)}
    >
      {segs.map((s) => (
        <span
          key={s.status}
          className={cn('h-full border-e border-white/70 last:border-e-0', TONE_CLASS[STATUS_META[s.status].tone].solid)}
          style={{ width: `${s.pct}%` }}
        />
      ))}
    </div>
  )
}

/** Small legend for StatusBar colours (text + swatch, order matches the bar). */
export function StatusLegend({ className }: { className?: string }) {
  const order: ComplianceStatus[] = ['attested', 'completed', 'in_progress', 'not_started', 'not_signed_in', 'overdue']
  return (
    <ul className={cn('flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-500', className)}>
      {order.map((s) => (
        <li key={s} className="inline-flex items-center gap-1.5">
          <span aria-hidden="true" className={cn('size-2 rounded-full', TONE_CLASS[STATUS_META[s].tone].solid)} />
          {STATUS_META[s].label}
        </li>
      ))}
    </ul>
  )
}
