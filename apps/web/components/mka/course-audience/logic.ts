// MKA fork — pure logic for CourseAudiencePanel (payload, preview copy, validation). No React, no I/O.
import type {
  AudiencePreview,
  CourseAudienceBody,
  CourseAudienceKind,
  CourseAudienceMode,
  CourseAudienceState,
  CustomRule,
  RawOptions,
} from '@services/mka/courseAudience'

export type Draft = { audience: CourseAudienceKind; mode: CourseAudienceMode; rule: CustomRule }
export type Option = { key: string; label: string }
export type NormalizedOptions = { departments: Option[]; levels: Option[]; roles: Option[] }

export const EMPTY_RULE: CustomRule = { departments: [], levels: [], roles: [] }
export const DEFAULT_DRAFT: Draft = { audience: 'officeholders', mode: 'optin', rule: EMPTY_RULE }

const uniq = (xs: string[]) => Array.from(new Set(xs.filter((x) => typeof x === 'string' && x.length > 0)))

export function draftFromState(state: CourseAudienceState | null | undefined): Draft | null {
  if (!state || state.audience === null) return null
  const r = state.rule ?? {}
  return {
    audience: state.audience,
    mode: state.mode,
    rule: { departments: uniq(r.departments ?? []), levels: uniq(r.levels ?? []), roles: uniq(r.roles ?? []) },
  }
}

/** Request body for preview/PUT. Non-custom audiences always send an empty rule. */
export function buildPayload(d: Draft): CourseAudienceBody {
  if (d.audience !== 'custom') return { audience: d.audience, mode: d.mode, rule: {} }
  const rule: Partial<CustomRule> = {}
  const departments = uniq(d.rule.departments)
  const levels = uniq(d.rule.levels)
  const roles = uniq(d.rule.roles)
  if (departments.length) rule.departments = departments
  if (levels.length) rule.levels = levels
  if (roles.length) rule.roles = roles
  return { audience: 'custom', mode: d.mode, rule }
}

/** A custom audience with no filter would silently equal "all office holders", so require at least one value. */
export function validateDraft(d: Draft): string | null {
  if (d.audience !== 'custom') return null
  const p = buildPayload(d).rule
  if (!p.departments && !p.levels && !p.roles) return 'Pick at least one department, level or role.'
  return null
}

export function toggleValue(list: string[], value: string): string[] {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value]
}

export function draftsEqual(a: Draft | null, b: Draft | null): boolean {
  if (!a || !b) return a === b
  return JSON.stringify(buildPayload(a)) === JSON.stringify(buildPayload(b))
}

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`

export function previewText(p: AudiencePreview, mode: CourseAudienceMode): string {
  const people = plural(p.matched_count, 'person matches', 'people match')
  if (mode === 'required') return `${people} · ${p.would_enroll} will be enrolled now`
  return `${people} · nobody is enrolled automatically`
}

export function sampleText(p: AudiencePreview): string {
  const names = p.sample.slice(0, 10).map((s) => s.name || s.email).filter(Boolean)
  if (!names.length) return ''
  const extra = p.matched_count - names.length
  return extra > 0 ? `${names.join(', ')} and ${extra} more` : names.join(', ')
}

/** Confirmation is only needed when saving will enroll people right now. */
export function needsEnrollConfirm(d: Draft, p: AudiencePreview | null): boolean {
  return d.mode === 'required' && (p?.would_enroll ?? 0) > 0
}

export function confirmText(p: AudiencePreview): string {
  return `Enroll ${plural(p.would_enroll, 'person', 'people')} now?`
}

export function resultText(r: { enrolled: number; memberships_added: number; memberships_removed: number; matched_count: number }): string {
  const parts = [`${r.matched_count} matched`]
  if (r.enrolled) parts.push(`${r.enrolled} enrolled`)
  if (r.memberships_added) parts.push(`${r.memberships_added} given access`)
  if (r.memberships_removed) parts.push(`${r.memberships_removed} access removed`)
  return `Audience saved: ${parts.join(', ')}.`
}

const titleCase = (k: string) => k.replace(/[_-]+/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())

function normList(xs: unknown[] | undefined, labelKeys: string[]): Option[] {
  const out: Option[] = []
  for (const x of xs ?? []) {
    if (typeof x === 'string') out.push({ key: x, label: titleCase(x) })
    else if (x && typeof x === 'object') {
      const o = x as Record<string, unknown>
      const key = String(o.key ?? o.value ?? '')
      if (!key) continue
      const label = labelKeys.map((k) => o[k]).find((v) => typeof v === 'string' && v) as string | undefined
      out.push({ key, label: label ?? titleCase(key) })
    }
  }
  return out
}

/** Accepts both [{key, name|label|title}] and plain string arrays. */
export function normalizeOptions(raw: RawOptions | null | undefined): NormalizedOptions {
  return {
    departments: normList(raw?.departments, ['name', 'label', 'title']),
    levels: normList(raw?.levels, ['label', 'name', 'title']),
    roles: normList(raw?.roles, ['title', 'label', 'name']),
  }
}
