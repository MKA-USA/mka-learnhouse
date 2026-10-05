'use client'
// MKA fork — shared presentational pieces for the audience picker, header and preview bar.
import * as React from 'react'
import * as DialogPrimitive from '@radix-ui/react-dialog'
import { Check, ChevronDown, Plus, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Popover, PopoverContent, PopoverTrigger } from '@components/ui/popover'
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '@components/ui/command'
import type { LevelTone } from '../audience/describe'

/** Under 640px we present overlays as bottom sheets. */
export function useIsNarrow(): boolean {
  return React.useSyncExternalStore(
    (cb) => {
      const mq = window.matchMedia('(max-width: 639px)')
      mq.addEventListener('change', cb)
      return () => mq.removeEventListener('change', cb)
    },
    () => window.matchMedia('(max-width: 639px)').matches,
    () => false,
  )
}

/** Literal class strings so Tailwind sees them. Colour is never the only signal: labels and icons always accompany it. */
export const TONE_STYLE: Record<LevelTone, { bar: string; chip: string; text: string }> = {
  national: { bar: 'bg-violet-600 dark:bg-violet-400', chip: 'bg-violet-100 text-violet-900 border-violet-300 dark:bg-violet-950 dark:text-violet-100 dark:border-violet-700', text: 'text-violet-800 dark:text-violet-200' },
  regional: { bar: 'bg-blue-600 dark:bg-blue-400', chip: 'bg-blue-100 text-blue-900 border-blue-300 dark:bg-blue-950 dark:text-blue-100 dark:border-blue-700', text: 'text-blue-800 dark:text-blue-200' },
  local: { bar: 'bg-emerald-600 dark:bg-emerald-400', chip: 'bg-emerald-100 text-emerald-900 border-emerald-300 dark:bg-emerald-950 dark:text-emerald-100 dark:border-emerald-700', text: 'text-emerald-800 dark:text-emerald-200' },
  mixed: { bar: 'bg-slate-500 dark:bg-slate-400', chip: 'bg-slate-100 text-slate-900 border-slate-300 dark:bg-slate-800 dark:text-slate-100 dark:border-slate-600', text: 'text-slate-700 dark:text-slate-200' },
  hide: { bar: 'text-slate-500 dark:text-slate-400', chip: 'bg-slate-100 text-slate-900 border-slate-300 dark:bg-slate-800 dark:text-slate-100 dark:border-slate-600', text: 'text-slate-700 dark:text-slate-200' },
}

/** Hatched bar for "Hide from"; colours via currentColor so it works in both themes. */
export const HATCH_STYLE: React.CSSProperties = {
  backgroundImage: 'repeating-linear-gradient(135deg, currentColor 0 3px, transparent 3px 6px)',
}

export const FOCUS_RING = 'focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background'
/** 44px touch targets on narrow screens, 36px on desktop where a pointer is precise. */
export const TARGET = 'min-h-11 sm:min-h-9'
export const PRESS = 'transition-[transform,background-color,color,border-color] duration-150 ease-out active:scale-[0.97] motion-reduce:transition-none motion-reduce:active:scale-100'

// ───────────────────────── Bottom sheet ─────────────────────────

export function Sheet({
  open,
  onOpenChange,
  title,
  children,
  className,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  children: React.ReactNode
  className?: string
}) {
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay
          className="fixed inset-0 bg-black/45 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=open]:fade-in-0 data-[state=closed]:fade-out-0 duration-200"
          style={{ zIndex: 'var(--z-modal-backdrop)' }}
        />
        <DialogPrimitive.Content
          aria-describedby={undefined}
          style={{ zIndex: 'var(--z-modal)' }}
          className={cn(
            'fixed inset-x-0 bottom-0 flex max-h-[92dvh] flex-col rounded-t-2xl border-t bg-background text-foreground shadow-2xl outline-hidden',
            'data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=open]:slide-in-from-bottom data-[state=closed]:slide-out-to-bottom duration-200 ease-out',
            className,
          )}
        >
          <DialogPrimitive.Title className="sr-only">{title}</DialogPrimitive.Title>
          <div aria-hidden className="mx-auto mt-2 h-1 w-10 shrink-0 rounded-full bg-muted-foreground/30" />
          <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain pb-[env(safe-area-inset-bottom)]">{children}</div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  )
}

/** Popover on desktop, bottom sheet under 640px. */
export function ResponsivePopover({
  open,
  onOpenChange,
  title,
  trigger,
  children,
  align = 'start',
  className,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
  title: string
  trigger: React.ReactNode
  children: React.ReactNode
  align?: 'start' | 'center' | 'end'
  className?: string
}) {
  const narrow = useIsNarrow()
  if (narrow) {
    return (
      <>
        {trigger}
        <Sheet open={open} onOpenChange={onOpenChange} title={title}>
          {children}
        </Sheet>
      </>
    )
  }
  return (
    <Popover open={open} onOpenChange={onOpenChange}>
      <PopoverTrigger asChild>{trigger}</PopoverTrigger>
      <PopoverContent align={align} className={cn('w-[min(24rem,calc(100vw-2rem))] p-0 origin-(--radix-popover-content-transform-origin)', className)}>
        {children}
      </PopoverContent>
    </Popover>
  )
}

// ───────────────────────── Chips ─────────────────────────

export function Chip({
  label,
  onRemove,
  onReplace,
  unknown,
  disabled,
  tone,
}: {
  label: string
  onRemove?: () => void
  onReplace?: () => void
  unknown?: boolean
  disabled?: boolean
  tone?: string
}) {
  const shown = unknown ? `Unknown: '${label}'` : label
  const onKey = (e: React.KeyboardEvent) => {
    if (disabled || !onRemove) return
    if (e.key === 'Backspace' || e.key === 'Delete') {
      e.preventDefault()
      onRemove()
    }
  }
  return (
    <span
      role="group"
      aria-label={shown}
      className={cn(
        'inline-flex max-w-full items-center gap-0.5 rounded-full border ps-3 text-sm font-medium',
        TARGET,
        unknown
          ? 'border-red-300 bg-red-50 text-red-900 dark:border-red-800 dark:bg-red-950/70 dark:text-red-100'
          : (tone ?? 'border-primary/25 bg-primary/10 text-foreground'),
      )}
    >
      <span className="truncate" title={shown}>{shown}</span>
      {unknown && onReplace && !disabled ? (
        <button
          type="button"
          onClick={onReplace}
          onKeyDown={onKey}
          className={cn('ms-1 rounded-full px-2 text-xs font-semibold underline underline-offset-2', TARGET, FOCUS_RING)}
        >
          Replace
        </button>
      ) : null}
      {!disabled && onRemove ? (
        <button
          type="button"
          aria-label={`Remove ${shown}`}
          onClick={onRemove}
          onKeyDown={onKey}
          className={cn('inline-flex min-w-9 items-center justify-center self-stretch rounded-full pe-1 opacity-70 hover:opacity-100', PRESS, FOCUS_RING)}
        >
          <X className="size-3.5" aria-hidden />
        </button>
      ) : (
        <span className="pe-3" />
      )}
    </span>
  )
}

// ───────────────────────── Chip list with searchable add ─────────────────────────

export type PickItem = { value: string; label: string; keywords?: string[] }
export type PickGroup = { heading?: string; items: PickItem[]; action?: { label: string; onSelect: () => void } }

export function MultiPick({
  ariaLabel,
  noun,
  selected,
  groups,
  labelFor,
  onToggle,
  onReplace,
  anyLabel,
  disabled,
  searchPlaceholder,
  loading,
}: {
  ariaLabel: string
  noun: string
  selected: string[]
  groups: PickGroup[]
  labelFor: (v: string) => string
  onToggle: (v: string) => void
  onReplace: (from: string, to: string) => void
  anyLabel: string
  disabled?: boolean
  searchPlaceholder: string
  loading?: boolean
}) {
  const [open, setOpen] = React.useState(false)
  const [replacing, setReplacing] = React.useState<string | null>(null)
  const known = React.useMemo(() => new Set(groups.flatMap((g) => g.items.map((i) => i.value))), [groups])
  const close = () => {
    setOpen(false)
    setReplacing(null)
  }
  const pick = (v: string) => {
    if (replacing !== null) {
      onReplace(replacing, v)
      close()
    } else {
      onToggle(v)
    }
  }

  const trigger = selected.length === 0 ? (
    <button
      type="button"
      disabled={disabled || loading}
      aria-label={`${ariaLabel}: ${anyLabel}. Choose…`}
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border border-dashed border-muted-foreground/50 px-3 text-sm text-muted-foreground hover:border-foreground/60 hover:text-foreground disabled:opacity-50',
        TARGET, PRESS, FOCUS_RING,
      )}
    >
      {anyLabel}
      <ChevronDown className="size-3.5" aria-hidden />
    </button>
  ) : (
    <button
      type="button"
      disabled={disabled || loading}
      aria-label={`Add ${noun}`}
      className={cn(
        'inline-flex min-w-11 items-center justify-center rounded-full border border-dashed border-muted-foreground/50 text-muted-foreground hover:border-foreground/60 hover:text-foreground disabled:opacity-50 sm:min-w-9',
        TARGET, PRESS, FOCUS_RING,
      )}
    >
      <Plus className="size-4" aria-hidden />
    </button>
  )

  return (
    <div role="group" aria-label={ariaLabel} className="flex min-w-0 flex-wrap items-center gap-1.5">
      {selected.map((v) => (
        <Chip
          key={v}
          label={labelFor(v)}
          unknown={!loading && !known.has(v)}
          disabled={disabled}
          onRemove={() => onToggle(v)}
          onReplace={() => {
            setReplacing(v)
            setOpen(true)
          }}
        />
      ))}
      <ResponsivePopover
        open={open}
        onOpenChange={(o) => (o ? setOpen(true) : close())}
        title={replacing ? `Replace ${labelFor(replacing)}` : `Choose ${noun}`}
        trigger={trigger}
      >
        <Command>
          <CommandInput placeholder={searchPlaceholder} autoFocus />
          <CommandList className="max-h-72">
            <CommandEmpty>No match. Try a different word.</CommandEmpty>
            {groups.map((g, gi) => (
              <CommandGroup key={g.heading ?? gi} heading={g.heading}>
                {g.action && replacing === null ? (
                  <CommandItem
                    value={`__action__${g.heading}`}
                    keywords={[g.heading ?? '', 'whole', 'region']}
                    onSelect={() => g.action!.onSelect()}
                    className="min-h-11 font-medium text-primary sm:min-h-9"
                  >
                    {g.action.label}
                  </CommandItem>
                ) : null}
                {g.items.map((it) => {
                  const on = selected.includes(it.value)
                  return (
                    <CommandItem
                      key={it.value}
                      value={it.value}
                      keywords={it.keywords ?? [it.label]}
                      onSelect={() => pick(it.value)}
                      className="min-h-11 sm:min-h-9"
                    >
                      <Check className={cn('size-4', on ? 'opacity-100' : 'opacity-0')} aria-hidden />
                      <span className="flex-1">{it.label}</span>
                      {on ? <span className="sr-only">selected</span> : null}
                    </CommandItem>
                  )
                })}
              </CommandGroup>
            ))}
          </CommandList>
          <div className="flex items-center justify-between border-t px-3 py-2">
            <span className="text-xs text-muted-foreground">{replacing ? 'Pick one to replace it' : 'Pick as many as you like'}</span>
            <button type="button" onClick={close} className={cn('rounded-md px-3 text-sm font-medium hover:bg-accent/20', TARGET, FOCUS_RING)}>
              Done
            </button>
          </div>
        </Command>
      </ResponsivePopover>
    </div>
  )
}
