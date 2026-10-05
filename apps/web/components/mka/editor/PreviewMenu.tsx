'use client'
// MKA fork — "Viewing as…" menu (design spec B1.4, contract §3.5).
import * as React from 'react'
import { ArrowLeft, Check, ChevronDown, Loader2, Search, SlidersHorizontal, UserSearch } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { AudienceOptions, AudienceView, MkaViewerAttributes, Persona } from '../audience/types'
import { FOCUS_RING, PRESS, ResponsivePopover, TARGET } from './audience-ui'

export type PreviewPerson = { user_id: number | string; display_name: string; email: string }

export type PreviewMenuProps = {
  view: AudienceView
  onChangeView(view: AudienceView): void
  personas: Persona[]
  canPickPerson: boolean
  searchPeople?(q: string): Promise<PreviewPerson[]>
  /** The host fetches that person's attributes and then calls onChangeView itself. */
  pickPerson?(id: number | string): void | Promise<unknown>
  options: AudienceOptions | undefined
}

export const viewLabel = (view: AudienceView) =>
  view.kind === 'author' ? 'Everything (author view)' : view.kind === 'self' ? 'As me' : view.label

type Panel = 'main' | 'person' | 'custom'

const ITEM = cn('flex w-full items-center gap-2 rounded-md px-3 text-start text-sm hover:bg-muted', TARGET, FOCUS_RING)

function MenuItem({ selected, onClick, children, hint }: { selected?: boolean; onClick(): void; children: React.ReactNode; hint?: string }) {
  return (
    <button type="button" onClick={onClick} aria-current={selected ? 'true' : undefined} className={ITEM}>
      <Check className={cn('size-4 shrink-0', selected ? 'opacity-100' : 'opacity-0')} aria-hidden />
      <span className="min-w-0 flex-1">
        <span className="block truncate">{children}</span>
        {hint ? <span className="block truncate text-xs text-muted-foreground">{hint}</span> : null}
      </span>
    </button>
  )
}

function PanelHeader({ title, onBack }: { title: string; onBack(): void }) {
  return (
    <div className="flex items-center gap-1 border-b px-2 py-1.5">
      <button type="button" onClick={onBack} aria-label="Back" className={cn('inline-flex min-h-11 min-w-11 items-center justify-center rounded-md hover:bg-muted sm:min-h-9 sm:min-w-9', FOCUS_RING)}>
        <ArrowLeft className="size-4" aria-hidden />
      </button>
      <h4 className="text-sm font-semibold">{title}</h4>
    </div>
  )
}

function PersonSearch({ searchPeople, pickPerson, onDone, onBack }: { searchPeople?: PreviewMenuProps['searchPeople']; pickPerson?: PreviewMenuProps['pickPerson']; onDone(): void; onBack(): void }) {
  const [q, setQ] = React.useState('')
  const [state, setState] = React.useState<{ s: 'idle' | 'loading' | 'error' | 'ready'; people: PreviewPerson[] }>({ s: 'idle', people: [] })
  const [picking, setPicking] = React.useState<number | string | null>(null)
  const [pickError, setPickError] = React.useState(false)

  React.useEffect(() => {
    const term = q.trim()
    if (term.length < 2 || !searchPeople) {
      setState({ s: 'idle', people: [] })
      return
    }
    let live = true
    setState((p) => ({ ...p, s: 'loading' }))
    const t = setTimeout(() => {
      searchPeople(term)
        .then((people) => live && setState({ s: 'ready', people }))
        .catch(() => live && setState({ s: 'error', people: [] }))
    }, 300)
    return () => {
      live = false
      clearTimeout(t)
    }
  }, [q, searchPeople])

  const pick = async (id: number | string) => {
    setPicking(id)
    setPickError(false)
    try {
      await pickPerson?.(id)
      onDone()
    } catch {
      setPickError(true)
    } finally {
      setPicking(null)
    }
  }

  return (
    <div>
      <PanelHeader title="Preview as a specific person" onBack={onBack} />
      <div className="space-y-2 p-3">
        <label className="relative block">
          <span className="sr-only">Search by name or email</span>
          <Search className="pointer-events-none absolute start-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <input
            autoFocus
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search by name or email"
            className={cn('w-full rounded-md border bg-background ps-9 pe-3 text-sm', TARGET, FOCUS_RING)}
          />
        </label>
        <p className="text-xs text-muted-foreground">Previewing a specific person is recorded in the audit log.</p>
        <div aria-live="polite" className="min-h-6 text-sm">
          {state.s === 'loading' ? <span className="inline-flex items-center gap-1.5 text-muted-foreground"><Loader2 className="size-3.5 animate-spin motion-reduce:animate-none" aria-hidden /> Searching…</span> : null}
          {state.s === 'error' ? <span className="text-red-800 dark:text-red-200">Search failed. Try again.</span> : null}
          {state.s === 'ready' && state.people.length === 0 ? <span className="text-muted-foreground">No one found.</span> : null}
          {q.trim().length > 0 && q.trim().length < 2 ? <span className="text-muted-foreground">Keep typing…</span> : null}
          {pickError ? <span className="text-red-800 dark:text-red-200">Could not load that person. Try again.</span> : null}
        </div>
        <ul className="max-h-60 overflow-y-auto">
          {state.people.map((p) => (
            <li key={p.user_id}>
              <button type="button" disabled={picking !== null} onClick={() => pick(p.user_id)} className={cn(ITEM, 'disabled:opacity-60')}>
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium">{p.display_name}</span>
                  <span className="block truncate text-xs text-muted-foreground">{p.email}</span>
                </span>
                {picking === p.user_id ? <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden /> : null}
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}

const SELECT = cn('w-full rounded-md border bg-background px-3 text-sm', TARGET, FOCUS_RING)

function CustomPanel({ options, onApply, onBack }: { options: AudienceOptions | undefined; onApply(v: AudienceView): void; onBack(): void }) {
  const [level, setLevel] = React.useState('local')
  const [department, setDepartment] = React.useState('')
  const [role, setRole] = React.useState('')
  const [region, setRegion] = React.useState('')
  const [majlis, setMajlis] = React.useState('')
  if (!options) return <div className="p-4 text-sm text-muted-foreground">Loading options…</div>

  const regions = Array.from(new Set(options.majlis.map((m) => m.region)))
  const apply = () => {
    const m = options.majlis.find((x) => x.name === majlis)
    const attrs: MkaViewerAttributes = {
      status: 'matched',
      is_officeholder: true,
      level: level as MkaViewerAttributes['level'],
      department: department || null,
      role: role || null,
      role_title: options.roles.find((r) => r.key === role)?.title ?? null,
      majlis: majlis || null,
      region: m?.region ?? (region || null),
    }
    const parts = [
      options.levels.find((l) => l.key === level)?.label ?? level,
      options.departments.find((d) => d.key === department)?.name,
      options.roles.find((r) => r.key === role)?.title,
      attrs.region,
      majlis || undefined,
    ].filter(Boolean)
    onApply({ kind: 'persona', label: `Custom · ${parts.join(' · ')}`, attributes: attrs })
  }
  const field = (label: string, control: React.ReactNode) => (
    <label className="block space-y-1">
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      {control}
    </label>
  )
  return (
    <div>
      <PanelHeader title="Custom viewer" onBack={onBack} />
      <div className="space-y-3 p-3">
        {field('Level', (
          <select className={SELECT} value={level} onChange={(e) => setLevel(e.target.value)}>
            {options.levels.map((l) => <option key={l.key} value={l.key}>{l.label}</option>)}
          </select>
        ))}
        {field('Department', (
          <select className={SELECT} value={department} onChange={(e) => setDepartment(e.target.value)}>
            <option value="">No department</option>
            {options.departments.map((d) => <option key={d.key} value={d.key}>{d.name}</option>)}
          </select>
        ))}
        {field('Role', (
          <select className={SELECT} value={role} onChange={(e) => setRole(e.target.value)}>
            <option value="">No specific role</option>
            {options.roles.map((r) => <option key={r.key} value={r.key}>{r.title}</option>)}
          </select>
        ))}
        {field('Majlis', (
          <select className={SELECT} value={majlis} onChange={(e) => setMajlis(e.target.value)}>
            <option value="">No Majlis</option>
            {regions.map((r) => (
              <optgroup key={r} label={r}>
                {options.majlis.filter((m) => m.region === r).map((m) => <option key={m.name} value={m.name}>{m.name}</option>)}
              </optgroup>
            ))}
          </select>
        ))}
        {!majlis ? field('Region', (
          <select className={SELECT} value={region} onChange={(e) => setRegion(e.target.value)}>
            <option value="">No region</option>
            {options.regions.map((r) => <option key={r.name} value={r.name}>{r.name}</option>)}
          </select>
        )) : <p className="text-xs text-muted-foreground">Region is taken from the Majlis.</p>}
        <button type="button" onClick={apply} className={cn('w-full rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90', TARGET, PRESS, FOCUS_RING)}>
          Preview as this viewer
        </button>
      </div>
    </div>
  )
}

export function PreviewMenu({ view, onChangeView, personas, canPickPerson, searchPeople, pickPerson, options }: PreviewMenuProps) {
  const [open, setOpen] = React.useState(false)
  const [panel, setPanel] = React.useState<Panel>('main')
  const close = () => {
    setOpen(false)
    setPanel('main')
  }
  const choose = (v: AudienceView) => {
    onChangeView(v)
    close()
  }
  const trigger = (
    <button
      type="button"
      aria-haspopup="dialog"
      aria-expanded={open}
      className={cn('inline-flex max-w-full items-center gap-2 rounded-md border bg-background px-3 text-sm font-medium hover:bg-muted', TARGET, PRESS, FOCUS_RING)}
    >
      <span className="text-muted-foreground">Viewing:</span>
      <span className="truncate">{viewLabel(view)}</span>
      <ChevronDown className="size-4 shrink-0" aria-hidden />
    </button>
  )
  return (
    <ResponsivePopover open={open} onOpenChange={(o) => (o ? setOpen(true) : close())} title="Choose who to view as" trigger={trigger}>
      {panel === 'person' ? (
        <PersonSearch searchPeople={searchPeople} pickPerson={pickPerson} onDone={close} onBack={() => setPanel('main')} />
      ) : panel === 'custom' ? (
        <CustomPanel options={options} onApply={choose} onBack={() => setPanel('main')} />
      ) : (
        <div className="max-h-[70dvh] space-y-1 overflow-y-auto p-2">
          <MenuItem selected={view.kind === 'author'} onClick={() => choose({ kind: 'author' })} hint="Every section, as you edit it">Everything (author view)</MenuItem>
          <MenuItem selected={view.kind === 'self'} onClick={() => choose({ kind: 'self' })} hint="Exactly what your own account sees">As me</MenuItem>
          {personas.length > 0 ? <p className="px-3 pt-2 text-xs font-medium text-muted-foreground">Personas</p> : null}
          {personas.map((p) => (
            <MenuItem key={p.id} selected={view.kind === 'persona' && view.label === p.label} onClick={() => choose({ kind: 'persona', label: p.label, attributes: p.attributes })}>
              {p.label}
            </MenuItem>
          ))}
          <div className="my-1 h-px bg-border" />
          {canPickPerson ? (
            <button type="button" onClick={() => setPanel('person')} className={ITEM}>
              <UserSearch className="size-4 shrink-0" aria-hidden />A specific person…
            </button>
          ) : null}
          <button type="button" onClick={() => setPanel('custom')} className={ITEM}>
            <SlidersHorizontal className="size-4 shrink-0" aria-hidden />Custom…
          </button>
        </div>
      )}
    </ResponsivePopover>
  )
}

export default PreviewMenu
