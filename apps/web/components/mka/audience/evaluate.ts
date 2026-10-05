// MKA fork — pure Audience rule validation + evaluation (contract §1.1–1.2).
// Must stay behaviour-identical to apps/api/src/services/mka/audience_eval.py; both run the
// shared vectors in apps/api/src/tests/services/mka/vectors/audience_vectors.json.
import { RULE_LIST_KEYS } from './types'
import type { Group, MkaViewerAttributes, Rule } from './types'

export * from './types'

export type ValidateResult = { ok: true; rule: Rule } | { ok: false; error: string }

/** Viewer after normalisation (contract §1.2 step 2). */
export type EffectiveViewer = {
  signedIn: boolean
  is_officeholder: boolean | null
  level: string | null
  department: string | null
  role: string | null
  role_title: string | null
  majlis: string | null
  region: string | null
}

const MAX_GROUPS = 20
const MAX_LIST = 500
const MAX_STR = 200
const MAX_LABEL = 500
const LIST_KEYS: readonly string[] = RULE_LIST_KEYS
const KNOWN_GROUP_KEYS = new Set<string>(['officeholder', ...RULE_LIST_KEYS])

const isObject = (x: unknown): x is Record<string, unknown> => typeof x === 'object' && x !== null && !Array.isArray(x)

export function validateRule(raw: unknown): ValidateResult {
  if (!isObject(raw)) return { ok: false, error: 'rule is not an object' }
  const { v, mode, groups, label } = raw
  if (typeof v !== 'number' || !Number.isSafeInteger(v) || v < 1) return { ok: false, error: 'v must be an integer >= 1' }
  if (mode !== 'show' && mode !== 'hide') return { ok: false, error: 'mode must be show or hide' }
  if (!Array.isArray(groups) || groups.length === 0 || groups.length > MAX_GROUPS) {
    return { ok: false, error: 'groups must be a non-empty array of at most 20' }
  }
  const outGroups: Group[] = []
  for (const g of groups) {
    if (!isObject(g)) return { ok: false, error: 'group is not an object' }
    const out: Group = {}
    for (const [key, val] of Object.entries(g)) {
      if (key === 'officeholder') {
        if (typeof val !== 'boolean') return { ok: false, error: 'officeholder must be boolean' }
        out[key] = val
      } else if (LIST_KEYS.includes(key)) {
        if (!Array.isArray(val) || val.length > MAX_LIST) return { ok: false, error: `${key} must be a short array` }
        for (const s of val) {
          if (typeof s !== 'string' || s.length === 0 || s.length > MAX_STR) {
            return { ok: false, error: `${key} entries must be non-empty strings` }
          }
        }
        const deduped = Array.from(new Set(val as string[]))
        if (deduped.length > 0) out[key] = deduped
      } else {
        // Unknown keys are kept (they make the group non-matching). defineProperty, not assignment: a plain
        // `out['__proto__'] = v` would set the prototype and let the group inherit list keys it never had.
        Object.defineProperty(out, key, { value: val, enumerable: true, writable: true, configurable: true })
      }
    }
    outGroups.push(out)
  }
  const rule: Rule = { v, mode, groups: outGroups }
  if (label !== undefined) {
    if (typeof label !== 'string' || label.length > MAX_LABEL) return { ok: false, error: 'label must be a short string' }
    rule.label = label
  }
  return { ok: true, rule }
}

export const NULL_VIEWER: EffectiveViewer = {
  signedIn: false,
  is_officeholder: null,
  level: null,
  department: null,
  role: null,
  role_title: null,
  majlis: null,
  region: null,
}

export function effectiveViewer(raw: unknown): EffectiveViewer {
  // Anything that is not a plain object (number, string, array, true, ...) is anonymous, same as Python.
  if (!isObject(raw)) return NULL_VIEWER
  const viewer = raw as Partial<MkaViewerAttributes>
  if (viewer.status !== 'matched' && viewer.status !== 'partial') {
    return { ...NULL_VIEWER, signedIn: true, is_officeholder: viewer.is_officeholder === false ? false : null }
  }
  return {
    signedIn: true,
    is_officeholder: viewer.is_officeholder ?? null,
    level: viewer.level ?? null,
    department: viewer.department ?? null,
    role: viewer.role ?? null,
    role_title: viewer.role_title ?? null,
    majlis: viewer.majlis ?? null,
    region: viewer.region ?? null,
  }
}

function groupMatches(g: Group, v: EffectiveViewer): boolean {
  for (const key of Object.keys(g)) if (!KNOWN_GROUP_KEYS.has(key)) return false
  const officeholder = g.officeholder === undefined ? true : g.officeholder
  if (officeholder ? v.is_officeholder !== true : !v.signedIn) return false
  for (const key of RULE_LIST_KEYS) {
    const wanted = g[key]
    if (wanted === undefined) continue
    const have = v[key]
    if (have == null || !(wanted as string[]).includes(have)) return false
  }
  return true
}

export function evaluateRule(raw: unknown, viewer: MkaViewerAttributes | null | undefined): boolean {
  const res = validateRule(raw)
  if (!res.ok) return false
  const rule = res.rule
  if (rule.v > 1) return false
  const ev = effectiveViewer(viewer)
  const any = rule.groups.some((g) => groupMatches(g, ev))
  return rule.mode === 'show' ? any : !any
}
