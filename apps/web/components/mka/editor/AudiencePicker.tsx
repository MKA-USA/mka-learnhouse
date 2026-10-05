'use client'
// MKA fork — the "who should see this?" picker (design spec B1.1–B1.7, contract §3.5). Pure and prop-driven.
import * as React from 'react'
import { CircleAlert, Eye, EyeOff, Info, Loader2, Lock, TriangleAlert } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@components/ui/popover'
import { ToggleGroup, ToggleGroupItem } from '@components/ui/toggle-group'
import { describeRule, isDescribable } from '../audience/describe'
import {
  applyPreset, emptyRule, hasRoleKey, listOf, normalizeRule, replaceValue, resolvePresets, sameGroups,
  selectWholeRegion, setMode, toggleValue,
} from '../audience/rule-edit'
import type { AudienceOptions, CountState, Rule, RuleListKey } from '../audience/types'
import { FOCUS_RING, MultiPick, PRESS, Sheet, TARGET, TONE_STYLE, useIsNarrow, type PickGroup } from './audience-ui'

export type AudiencePickerProps = {
  value: Rule
  onChange(rule: Rule): void
  onDone(): void
  onCancel(): void
  onRemove?(): void
  options: AudienceOptions | undefined
  authorDepartment: string | null
  count: CountState
  isNew: boolean
}

const EMPTY_NOTE = 'Nobody currently matches this. Check the filters.'
const UNKNOWN_CHIP =
  'border-red-300 bg-red-50 text-red-900'

const plural = (n: number, one: string, many: string) => (n === 1 ? one : many)

export function CountLine({ count, options, rule }: { count: CountState; options?: AudienceOptions; rule: Rule }) {
  const [infoOpen, setInfoOpen] = React.useState(false)
  let body: React.ReactNode = null
  if (count.state === 'loading') {
    body = (
      <span className="inline-flex items-center gap-1.5 text-gray-600">
        <Loader2 className="size-3.5 animate-spin motion-reduce:animate-none" aria-hidden /> Counting…
      </span>
    )
  } else if (count.state === 'error') {
    body = <span className="text-gray-600">Count unavailable. You can keep editing.</span>
  } else if (count.state === 'ready' && count.data) {
    const d = count.data
    const showExpected = d.expected && !hasRoleKey(rule)
    body = (
      <>
        <span className="font-medium text-gray-900">
          ≈ {d.count} {plural(d.count, 'person', 'people')} {plural(d.count, 'sees', 'see')} this
        </span>
        {d.unrecognized > 0 ? (
          <span className="text-gray-600">
            {' · '}
            {d.unrecognized} unrecognized {plural(d.unrecognized, 'account', 'accounts')} not counted
          </span>
        ) : null}
        {showExpected ? (
          <span className="mt-0.5 block text-xs text-gray-600">
            {d.expected!.matching} of {d.expected!.total} on this year&apos;s roster
          </span>
        ) : null}
      </>
    )
  }
  return (
    <div className="flex min-h-9 items-start gap-1.5 text-sm" data-testid="audience-count">
      {/* The live region stays mounted so screen readers hear every update. */}
      <p aria-live="polite" className="min-w-0 flex-1 py-1.5">
        {body}
      </p>
      {options?.copy.count_tooltip && count.state !== 'idle' ? (
        <Popover open={infoOpen} onOpenChange={setInfoOpen}>
          <PopoverTrigger asChild>
            <button
              type="button"
              aria-label="About this count"
              className={cn('inline-flex min-h-11 min-w-11 items-center justify-center rounded-full text-gray-600 hover:text-gray-900 sm:min-h-9 sm:min-w-9', FOCUS_RING)}
            >
              <Info className="size-4" aria-hidden />
            </button>
          </PopoverTrigger>
          <PopoverContent className="w-72 border-gray-200 bg-white text-sm leading-relaxed text-gray-900" side="top" align="end">
            {options.copy.count_tooltip}
          </PopoverContent>
        </Popover>
      ) : null}
    </div>
  )
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5 sm:flex-row sm:items-start sm:gap-3">
      <div className="shrink-0 text-sm font-medium text-gray-600 sm:w-28 sm:pt-2">{label}</div>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  )
}

function Skeleton() {
  return (
    <div className="space-y-3 p-4" aria-busy="true" aria-label="Loading audience options">
      {[0, 1, 2].map((i) => (
        <div key={i} className="h-9 animate-pulse rounded-full bg-gray-100 motion-reduce:animate-none" style={{ width: `${70 - i * 15}%` }} />
      ))}
    </div>
  )
}

export function PickerBody({
  value, onChange, onDone, onCancel, onRemove, options, authorDepartment, count, isNew, inSheet,
}: AudiencePickerProps & { inSheet?: boolean }) {
  const [moreOpen, setMoreOpen] = React.useState(false)
  const describable = isDescribable(value)
  const readOnly = describable && value.v > 1
  const damaged = !describable
  const rule: Rule = damaged ? emptyRule() : value
  const dopts = options

  // Reveal the advanced rows whenever the rule already uses them, so nothing is hidden from the author.
  const usesMore = listOf(rule, 'role').length + listOf(rule, 'region').length + listOf(rule, 'majlis').length > 0
  const showMore = moreOpen || usesMore

  const emit = (next: Rule) => onChange(normalizeRule(next, dopts))
  const toggle = (key: RuleListKey) => (v: string) => emit(toggleValue(rule, key, v))
  const replace = (key: RuleListKey) => (from: string, to: string) => emit(replaceValue(rule, key, from, to))

  const presets = React.useMemo(
    () => (dopts ? resolvePresets(dopts.presets, authorDepartment, dopts.departments.map((d) => d.key)) : []),
    [dopts, authorDepartment],
  )

  const deptGroups: PickGroup[] = React.useMemo(
    () => [{ items: (dopts?.departments ?? []).map((d) => ({ value: d.key, label: d.name, keywords: [d.name, ...d.aka] })) }],
    [dopts],
  )
  const roleGroups: PickGroup[] = React.useMemo(
    () => [{ items: (dopts?.roles ?? []).map((r) => ({ value: r.key, label: r.title })) }],
    [dopts],
  )
  const regionGroups: PickGroup[] = React.useMemo(
    () => [{ items: (dopts?.regions ?? []).map((r) => ({ value: r.name, label: r.name })) }],
    [dopts],
  )
  const majlisGroups: PickGroup[] = dopts
    ? Array.from(
        dopts.majlis.reduce((acc, m) => acc.set(m.region, [...(acc.get(m.region) ?? []), m.name]), new Map<string, string[]>()),
      ).map(([region, names]) => ({
        heading: region,
        items: names.map((n) => ({ value: n, label: n, keywords: [n, region] })),
        action: { label: `Select whole ${region} region`, onSelect: () => emit(selectWholeRegion(rule, region, names)) },
      }))
    : []

  const level = listOf(rule, 'level')
  const reads = !dopts ? '' : damaged ? 'Nobody until you choose an audience' : describeRule(rule, dopts)
  const zero = count.state === 'ready' && count.data?.count === 0
  const modeWord = rule.mode === 'hide' ? 'Hide from' : 'Show this to'

  const onKeyDown = (e: React.KeyboardEvent) => {
    // Radix layers (popovers) preventDefault their own Escape first, so this only fires for the picker itself.
    if (e.key === 'Escape' && !e.defaultPrevented && !inSheet) {
      e.preventDefault()
      onCancel()
    }
  }

  return (
    <div
      role="group"
      aria-label="Who should see this section?"
      onKeyDown={onKeyDown}
      className="w-full max-w-[40rem] rounded-xl border border-gray-200 bg-white text-gray-900 shadow-sm"
    >
      <div className="px-4 pt-4">
        <h3 className="text-base font-semibold leading-tight">Who should see this?</h3>
      </div>

      {!dopts ? (
        <Skeleton />
      ) : (
        <div className="space-y-4 p-4">
          {damaged ? (
            <div role="alert" className={cn('flex gap-2 rounded-lg border border-gray-200 p-3 text-sm', UNKNOWN_CHIP)}>
              <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
              <div>
                <p className="font-medium">This section&apos;s audience is damaged. Choose who should see it.</p>
                <p className="mt-0.5">Until then, learners will not see it.</p>
              </div>
            </div>
          ) : null}

          {readOnly ? (
            <div role="status" className="flex gap-2 rounded-lg border border-gray-200 bg-gray-100 p-3 text-sm">
              <Lock className="mt-0.5 size-4 shrink-0" aria-hidden />
              <div>
                <p className="font-medium">Made with a newer editor</p>
                <p className="mt-0.5 text-gray-600">
                  You can look at this audience but not change it. Learners will not see this section until the editor is updated.
                </p>
              </div>
            </div>
          ) : null}

          {(isNew || damaged) && presets.length > 0 && !readOnly ? (
            <div>
              <p className="mb-2 text-sm font-medium text-gray-600">Quick picks</p>
              <div className="flex flex-wrap gap-2" role="group" aria-label="Quick picks">
                {presets.map((p) => {
                  const active = !damaged && rule.mode === 'show' && sameGroups(rule, p.rule)
                  return (
                    <button
                      key={p.id}
                      type="button"
                      aria-pressed={active}
                      onClick={() => emit(applyPreset(p, dopts))}
                      className={cn(
                        'inline-flex items-center rounded-full border border-gray-200 px-4 text-sm font-medium',
                        TARGET, PRESS, FOCUS_RING,
                        active ? 'border-sky-700 bg-sky-700 text-white' : 'bg-white hover:bg-gray-100',
                      )}
                    >
                      {p.label}
                    </button>
                  )
                })}
              </div>
              <p className="mt-3 text-sm font-medium text-gray-600">Or build it</p>
            </div>
          ) : null}

          <ToggleGroup
            type="single"
            value={rule.mode}
            disabled={readOnly}
            aria-label="Show or hide"
            onValueChange={(v) => v && emit(setMode(rule, v as Rule['mode']))}
            className="grid w-full grid-cols-2 gap-0 rounded-full border border-gray-200 bg-gray-100 p-0.5 sm:w-72"
          >
            {(['show', 'hide'] as const).map((m) => (
              <ToggleGroupItem
                key={m}
                value={m}
                className={cn(
                  'min-h-11 gap-1.5 whitespace-nowrap rounded-full px-4 text-sm font-medium sm:min-h-8',
                  'data-[state=on]:bg-white data-[state=on]:text-gray-900 data-[state=on]:shadow-sm',
                  PRESS, FOCUS_RING,
                )}
              >
                {m === 'show' ? <Eye className="size-4" aria-hidden /> : <EyeOff className="size-4" aria-hidden />}
                {m === 'show' ? 'Show to' : 'Hide from'}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>

          <div className="space-y-3">
            <Row label={modeWord}>
              <div className="flex flex-wrap items-center gap-1.5">
                <div role="group" aria-label="Level" className="flex flex-wrap gap-1.5">
                  {dopts.levels.map((l) => {
                    const on = level.includes(l.key)
                    return (
                      <button
                        key={l.key}
                        type="button"
                        aria-pressed={on}
                        disabled={readOnly}
                        onClick={() => toggle('level')(l.key)}
                        className={cn(
                          'inline-flex items-center rounded-full border border-gray-200 px-3.5 text-sm font-medium disabled:opacity-60',
                          TARGET, PRESS, FOCUS_RING,
                          on
                            ? `${TONE_STYLE[l.key].chip} ring-1 ring-current`
                            : 'border-dashed border-gray-500 text-gray-600 hover:border-gray-600 hover:text-gray-900',
                        )}
                      >
                        {l.label}
                      </button>
                    )
                  })}
                  {level
                    .filter((k) => !dopts.levels.some((l) => l.key === k))
                    .map((k) => (
                      <button
                        key={k}
                        type="button"
                        disabled={readOnly}
                        onClick={() => toggle('level')(k)}
                        aria-label={`Remove unknown level '${k}'`}
                        className={cn('inline-flex items-center rounded-full border border-gray-200 px-3.5 text-sm font-medium', UNKNOWN_CHIP, TARGET, FOCUS_RING)}
                      >
                        Unknown: &apos;{k}&apos; ×
                      </button>
                    ))}
                </div>
                <span className="text-sm text-gray-600">{level.length === 0 ? '(any level)' : 'officeholders'}</span>
              </div>
            </Row>
            <Row label="in department">
              <MultiPick
                ariaLabel="Department"
                noun="department"
                selected={listOf(rule, 'department')}
                groups={deptGroups}
                labelFor={(v) => dopts.departments.find((d) => d.key === v)?.name ?? v}
                onToggle={toggle('department')}
                onReplace={replace('department')}
                anyLabel="Any department"
                searchPlaceholder="Search departments…"
                disabled={readOnly}
              />
            </Row>

            {showMore ? (
              <>
                <Row label="with role">
                  <MultiPick
                    ariaLabel="Role"
                    noun="role"
                    selected={listOf(rule, 'role')}
                    groups={roleGroups}
                    labelFor={(v) => dopts.roles.find((r) => r.key === v)?.title ?? v}
                    onToggle={toggle('role')}
                    onReplace={replace('role')}
                    anyLabel="Any role"
                    searchPlaceholder="Search roles…"
                    disabled={readOnly}
                  />
                </Row>
                <Row label="in region">
                  <MultiPick
                    ariaLabel="Region"
                    noun="region"
                    selected={listOf(rule, 'region')}
                    groups={regionGroups}
                    labelFor={(v) => v}
                    onToggle={toggle('region')}
                    onReplace={replace('region')}
                    anyLabel="Any region"
                    searchPlaceholder="Search regions…"
                    disabled={readOnly}
                  />
                </Row>
                <Row label="in Majlis">
                  <MultiPick
                    ariaLabel="Majlis"
                    noun="Majlis"
                    selected={listOf(rule, 'majlis')}
                    groups={majlisGroups}
                    labelFor={(v) => v}
                    onToggle={toggle('majlis')}
                    onReplace={replace('majlis')}
                    anyLabel="Any Majlis"
                    searchPlaceholder="Search Majlis or region…"
                    disabled={readOnly}
                  />
                </Row>
              </>
            ) : (
              <button
                type="button"
                aria-expanded={false}
                onClick={() => setMoreOpen(true)}
                className={cn('rounded-md px-1 text-sm font-medium text-sky-800 underline underline-offset-4 sm:ms-[7.75rem]', TARGET, FOCUS_RING)}
              >
                More filters: role, region, Majlis
              </button>
            )}

            {rule.groups.length > 1 ? (
              <p className="flex gap-2 text-sm text-gray-600 sm:ms-[7.75rem]">
                <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
                This section has {rule.groups.length} audiences. Only the first one can be edited here.
              </p>
            ) : null}
          </div>

          <div className="rounded-lg border border-gray-200 bg-gray-50 p-3">
            <p className="text-xs font-medium uppercase tracking-wide text-gray-600">Reads as</p>
            <p className="mt-0.5 text-[0.9375rem] font-medium leading-snug" data-testid="audience-reads-as">
              {reads}
            </p>
            <div className="mt-1">
              <CountLine count={count} options={dopts} rule={rule} />
            </div>
            {zero ? (
              <p role="status" className="mt-1 flex gap-2 text-sm text-amber-900">
                <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
                {EMPTY_NOTE}
              </p>
            ) : null}
          </div>

          <p className="flex gap-2 text-xs leading-relaxed text-gray-600" data-testid="audience-not-secret">
            <Lock className="mt-0.5 size-3.5 shrink-0" aria-hidden />
            {dopts.copy.not_secret}
          </p>
        </div>
      )}

      <div className="flex flex-col-reverse gap-2 border-t border-gray-200 p-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          {onRemove ? (
            <Button type="button" variant="ghost" onClick={onRemove} className="h-11 w-full text-red-700 hover:text-red-800 sm:h-9 sm:w-auto">
              Remove section
            </Button>
          ) : null}
        </div>
        <div className="flex gap-2">
          <Button type="button" variant="outline" onClick={onCancel} className="h-11 flex-1 border-gray-300 bg-white text-gray-800 hover:bg-gray-50 sm:h-9 sm:flex-none">
            Cancel
          </Button>
          <Button type="button" onClick={onDone} disabled={damaged || !dopts} className="h-11 flex-1 bg-sky-700 text-white hover:bg-sky-800 sm:h-9 sm:flex-none">
            Done
          </Button>
        </div>
      </div>
    </div>
  )
}

/** On phones the picker presents itself as a bottom sheet; elsewhere it is the card itself. */
export function AudiencePicker(props: AudiencePickerProps) {
  const narrow = useIsNarrow()
  if (narrow) {
    return (
      <Sheet open onOpenChange={(o) => !o && props.onCancel()} title="Who should see this section?">
        <PickerBody {...props} inSheet />
      </Sheet>
    )
  }
  return <PickerBody {...props} />
}

export default AudiencePicker
