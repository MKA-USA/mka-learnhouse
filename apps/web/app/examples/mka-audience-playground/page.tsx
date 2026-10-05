'use client'
// MKA fork — DEV-ONLY playground that renders every audience UI state for design review and screenshots.
// 404s unless NEXT_PUBLIC_MKA_AUDIENCE_MOCK=1 (and never in a production build). All data is synthetic.
import * as React from 'react'
import { notFound, useSearchParams } from 'next/navigation'
import { describeRule } from '@components/mka/audience/describe'
import type { AudienceCount, AudienceOptions, AudienceView, AudienceWarning, CountState, Rule } from '@components/mka/audience/types'
import { AudienceBar } from '@components/mka/editor/AudienceBar'
import { AudienceHeader, HiddenPlaceholder, ReadOnlyBadge } from '@components/mka/editor/AudienceHeader'
import { AudiencePicker, PickerBody, type AudiencePickerProps } from '@components/mka/editor/AudiencePicker'
import { MOCK_OPTIONS, MOCK_PERSONAS } from './mock-options'

const ENABLED = process.env.NEXT_PUBLIC_MKA_AUDIENCE_MOCK === '1' && process.env.NODE_ENV !== 'production'

const rule = (mode: Rule['mode'], ...groups: Rule['groups']): Rule => ({ v: 1, mode, groups })
const ready = (over: Partial<AudienceCount> = {}): CountState => ({
  state: 'ready',
  data: { count: 62, total_officeholders: 640, unrecognized: 3, by_level: { national: 0, regional: 0, local: 62 }, expected: { matching: 62, total: 64, cycle_id: 7 }, ...over },
})

/** Fake count: shrinks with each filter. Good enough to see the line update. */
function fakeCount(r: Rule): CountState {
  const g = r.groups[0] ?? {}
  let n = 640
  for (const k of ['level', 'department', 'role', 'region', 'majlis'] as const) {
    const l = g[k]
    if (Array.isArray(l) && l.length) n = Math.round(n * Math.min(1, l.length * (k === 'level' ? 0.4 : k === 'department' ? 0.06 : 0.1)))
  }
  if (r.mode === 'hide') n = 640 - n
  return ready({ count: n, expected: { matching: Math.min(64, Math.round(n / 10)), total: 64, cycle_id: 7 } })
}

function Section({ id, title, note, children }: { id: string; title: string; note?: string; children: React.ReactNode }) {
  return (
    <section id={id} className="space-y-2">
      <h2 className="text-sm font-semibold">{title}</h2>
      {note ? <p className="text-xs text-gray-600">{note}</p> : null}
      <div className="space-y-3">{children}</div>
    </section>
  )
}

function StaticPicker(p: Partial<AudiencePickerProps> & { value: Rule }) {
  const [value, setValue] = React.useState(p.value)
  return (
    <PickerBody
      onDone={() => {}} onCancel={() => {}} onRemove={() => {}} options={MOCK_OPTIONS} authorDepartment="tabligh"
      count={{ state: 'idle' }} isNew={false} {...p} value={value} onChange={(r) => { setValue(r); p.onChange?.(r) }}
    />
  )
}

function LiveDemo() {
  const [value, setValue] = React.useState<Rule>({ v: 1, mode: 'show', groups: [{}] })
  const [count, setCount] = React.useState<CountState>({ state: 'idle' })
  React.useEffect(() => {
    const t = setTimeout(() => {
      setCount({ state: 'loading' })
      setTimeout(() => setCount(fakeCount(value)), 400)
    }, 0)
    return () => clearTimeout(t)
  }, [value])
  return (
    <div className="space-y-2">
      <PickerBody value={value} onChange={setValue} onDone={() => {}} onCancel={() => {}} onRemove={() => {}} options={MOCK_OPTIONS} authorDepartment="tabligh" count={count} isNew />
      <pre className="overflow-x-auto rounded-md bg-gray-100 p-2 text-xs" data-testid="live-json">{JSON.stringify(value)}</pre>
    </div>
  )
}

function Header({ r, warnings = [], count = ready(), collapsed = false, label }: { r: Rule; warnings?: AudienceWarning[]; count?: CountState; collapsed?: boolean; label?: string }) {
  const [c, setC] = React.useState(collapsed)
  return (
    <div className="overflow-hidden rounded-md border border-gray-200">
      <AudienceHeader rule={r} label={label ?? describeRule(r, MOCK_OPTIONS)} count={count} onEdit={() => {}} onPreview={() => {}} onToggleCollapse={() => setC((x) => !x)} collapsed={c} blockCount={4} warnings={warnings} />
      {!c ? <p className="px-4 py-3 text-sm">As a local Nazim Tabligh in your Majlis, submit your monthly report to the regional Qaid by the 5th.</p> : null}
    </div>
  )
}

function BarDemo({ initial, canPickPerson = true }: { initial: AudienceView; canPickPerson?: boolean }) {
  const [view, setView] = React.useState<AudienceView>(initial)
  const people = [
    { user_id: 1, display_name: 'Sample Person One', email: 'one@example.invalid' },
    { user_id: 2, display_name: 'Sample Person Two', email: 'two@example.invalid' },
  ]
  return (
    <div className="overflow-hidden rounded-md border border-gray-200">
      <AudienceBar
        sectionCount={5} view={view} onChangeView={setView} personas={MOCK_PERSONAS} canPickPerson={canPickPerson} options={MOCK_OPTIONS}
        searchPeople={async (q) => { await new Promise((r) => setTimeout(r, 250)); return people.filter((p) => p.display_name.toLowerCase().includes(q.toLowerCase()) || p.email.includes(q.toLowerCase())) }}
        pickPerson={async (id) => { await new Promise((r) => setTimeout(r, 300)); const p = people.find((x) => x.user_id === id)!; setView({ kind: 'persona', label: p.display_name, attributes: MOCK_PERSONAS[0].attributes }) }}
      />
      <div className="space-y-2 p-3 text-sm">
        <p>Editor content scrolls here.</p>
        {view.kind === 'persona' ? <HiddenPlaceholder label="Regional Qaids" /> : null}
      </div>
    </div>
  )
}

function SheetDemo({ open, setOpen }: { open: boolean; setOpen: (o: boolean) => void }) {
  const [value, setValue] = React.useState<Rule>({ v: 1, mode: 'show', groups: [{}] })
  if (!open) return <button type="button" className="min-h-11 rounded-md border px-4 text-sm font-medium" onClick={() => setOpen(true)}>Open picker (sheet under 640px)</button>
  return <AudiencePicker value={value} onChange={setValue} onDone={() => setOpen(false)} onCancel={() => setOpen(false)} onRemove={() => setOpen(false)} options={MOCK_OPTIONS} authorDepartment="tabligh" count={ready()} isNew />
}

export default function AudiencePlayground() {
  if (!ENABLED) notFound()
  const params = useSearchParams()
  const only = params.get('only')
  const [sheetOpen, setSheetOpen] = React.useState(params.get('sheet') === '1')
  const noOptions: AudienceOptions | undefined = undefined
  const show = (id: string) => !only || only === id

  return (
    <div>
      <div className="min-h-screen bg-[#f8f8f8] text-gray-900">
        <div className="mx-auto max-w-3xl space-y-10 px-4 py-6">
          <h1 className="text-lg font-semibold">Audience UI playground (dev only, synthetic data)</h1>

          {show('sheet') ? <Section id="sheet" title="Sheet presentation" note="Under 640px the picker is a bottom sheet."><SheetDemo open={sheetOpen} setOpen={setSheetOpen} /></Section> : null}
          {show('live') ? <Section id="live" title="Picker — live (new section)" note="Try it: pick a quick pick, toggle levels, add departments."><LiveDemo /></Section> : null}

          {show('picker-states') ? (
            <Section id="picker-states" title="Picker states">
              <p className="text-xs font-medium">Edited rule, count ready (with expected + unrecognized)</p>
              <StaticPicker value={rule('show', { level: ['local'], department: ['tabligh'] })} count={ready()} />
              <p className="text-xs font-medium">Hide from, advanced rows revealed (Majlis grouped by region)</p>
              <StaticPicker value={rule('hide', { level: ['national'], region: ['Northeast'], majlis: ['Houston'] })} count={ready({ count: 578, unrecognized: 1, expected: null })} />
              <p className="text-xs font-medium">Count loading</p>
              <StaticPicker value={rule('show', { level: ['regional'] })} count={{ state: 'loading' }} />
              <p className="text-xs font-medium">Count error</p>
              <StaticPicker value={rule('show', { level: ['regional'] })} count={{ state: 'error' }} />
              <p className="text-xs font-medium">Zero audience</p>
              <StaticPicker value={rule('show', { level: ['national'], majlis: ['Albany'] })} count={ready({ count: 0, unrecognized: 0, expected: null })} />
              <p className="text-xs font-medium">Unknown values (renamed department, retired Majlis)</p>
              <StaticPicker value={rule('show', { department: ['tabligh', 'rishta_nata_old'], majlis: ['Narnia'] })} count={ready({ count: 12, expected: null })} />
              <p className="text-xs font-medium">Damaged rule (invalid)</p>
              <StaticPicker value={{ v: 1, mode: 'maybe' } as unknown as Rule} isNew />
              <p className="text-xs font-medium">Newer editor version (read-only)</p>
              <StaticPicker value={{ v: 2, mode: 'show', groups: [{ level: ['local'] }] }} count={{ state: 'idle' }} />
              <p className="text-xs font-medium">Author without a department (My department hidden), isNew</p>
              <StaticPicker value={rule('show', {})} isNew authorDepartment={null} count={ready({ count: 640, expected: null })} />
              <p className="text-xs font-medium">Options loading</p>
              <StaticPicker value={rule('show', {})} options={noOptions} />
            </Section>
          ) : null}

          {show('headers') ? (
            <Section id="headers" title="Section headers">
              <Header r={rule('show', { level: ['local'], department: ['tabligh'] })} />
              <Header r={rule('show', { level: ['national'] })} />
              <Header r={rule('show', { level: ['regional'], role: ['regional_qaid'] })} />
              <Header r={rule('show', { level: ['local', 'regional'], department: ['tabligh'] })} />
              <Header r={rule('hide', { level: ['national'] })} />
              <Header r={rule('show', { level: ['local'] })} collapsed />
              <Header r={rule('show', { level: ['national'], majlis: ['Albany'] })} count={ready({ count: 0 })} warnings={[{ kind: 'zero' }]} />
              <Header r={rule('show', { department: ['rishta_old'] })} warnings={[{ kind: 'unknown_values', values: ['rishta_old'] }]} />
              <Header r={{ v: 1, mode: 'x' } as unknown as Rule} count={{ state: 'idle' }} label="Audience needs fixing" warnings={[{ kind: 'invalid' }]} />
              <Header r={{ v: 2, mode: 'show', groups: [{}] }} count={{ state: 'idle' }} label="Made with a newer editor" warnings={[{ kind: 'newer_version' }]} />
              <Header r={rule('show', { level: ['local'], department: ['tabligh', 'taleem', 'maal', 'tarbiyyat', 'ishaat'], region: ['Northeast', 'East', 'Gulf'], majlis: ['Albany', 'Boston', 'Houston'] })} />
              <Header r={rule('show', { level: ['local'] })} count={{ state: 'loading' }} />
              <Header r={rule('show', { level: ['local'] })} count={{ state: 'error' }} />
              <HiddenPlaceholder label="Regional Qaids" />
              <ReadOnlyBadge rule={rule('show', { level: ['regional'], role: ['regional_qaid'] })} label="Regional Qaids" />
            </Section>
          ) : null}

          {show('bars') ? (
            <Section id="bars" title="Audience bar">
              <BarDemo initial={{ kind: 'author' }} />
              <BarDemo initial={{ kind: 'persona', label: 'Local Nazim Tabligh · Albany', attributes: MOCK_PERSONAS[0].attributes }} />
              <BarDemo initial={{ kind: 'self' }} canPickPerson={false} />
            </Section>
          ) : null}
        </div>
      </div>
    </div>
  )
}
