// MKA fork — plain-English description of an audience rule (contract §1.4). Pure, no React.
import type { AudienceOptions, Group, Rule } from './types'

export type DescribeOptions = Pick<AudienceOptions, 'levels' | 'departments' | 'roles' | 'regions' | 'majlis'>
export type LevelTone = 'national' | 'regional' | 'local' | 'mixed' | 'hide'

export const INVALID_LABEL = 'Audience needs fixing'
export const NEWER_LABEL = 'Made with a newer editor'
const MAX_SHOWN = 3
const KNOWN_KEYS = ['officeholder', 'level', 'department', 'role', 'region', 'majlis']
const LIST_KEYS = ['level', 'department', 'role', 'region', 'majlis'] as const

/** The level each role key implies (parser role keys). */
export const ROLE_LEVEL: Record<string, string> = {
  sadr: 'national', naib_sadr: 'national', mohtamim: 'national', national_staff: 'national',
  regional_qaid: 'regional', regional_nazim_dept: 'regional', regional_motamid: 'regional',
  nazim_dept: 'local', qaid: 'local', naib_qaid: 'local', motamid: 'local', nazim_atfal: 'local', murabbi_atfal: 'local',
}

const isStringList = (v: unknown): v is string[] => Array.isArray(v) && v.every((x) => typeof x === 'string')

/** Structural check only; full validation lives in evaluate.ts. */
export function isDescribable(rule: unknown): rule is Rule {
  if (!rule || typeof rule !== 'object') return false
  const r = rule as Record<string, unknown>
  if (typeof r.v !== 'number' || !Number.isInteger(r.v) || r.v < 1) return false
  if (r.mode !== 'show' && r.mode !== 'hide') return false
  if (!Array.isArray(r.groups) || r.groups.length === 0) return false
  return r.groups.every((g) => {
    if (!g || typeof g !== 'object' || Array.isArray(g)) return false
    const grp = g as Record<string, unknown>
    if ('officeholder' in grp && typeof grp.officeholder !== 'boolean') return false
    return LIST_KEYS.every((k) => !(k in grp) || isStringList(grp[k]))
  })
}

/** "A", "A or B", "A, B or C", more than three: "A, B and N more". */
export function joinList(items: string[]): string {
  if (items.length === 0) return ''
  if (items.length === 1) return items[0]
  if (items.length <= MAX_SHOWN) return `${items.slice(0, -1).join(', ')} or ${items[items.length - 1]}`
  const shown = items.slice(0, 2)
  return `${shown.join(', ')} and ${items.length - shown.length} more`
}

const unknown = (v: string) => `${v} (unknown)`

function labels(values: string[], lookup: (v: string) => string | undefined): string[] {
  return values.map((v) => lookup(v) ?? unknown(v))
}

function describeGroup(g: Group, o: DescribeOptions): string {
  const levelsList = Array.isArray(g.level) ? g.level : []
  const levels = labels(levelsList, (k) => o.levels.find((l) => l.key === k)?.label)
  const roles = Array.isArray(g.role) ? g.role : []
  const departments = Array.isArray(g.department) ? g.department : []
  const regions = Array.isArray(g.region) ? g.region : []
  const majlis = Array.isArray(g.majlis) ? g.majlis : []
  const hasFilters = levels.length + roles.length + departments.length + regions.length + majlis.length > 0
  const anyone = g.officeholder === false

  const hasUnknownKey = Object.keys(g).some((k) => !KNOWN_KEYS.includes(k))
  if (!hasFilters) {
    return (anyone ? 'Everyone signed in' : 'All officeholders') + (hasUnknownKey ? ' (unknown filter)' : '')
  }

  const noun = anyone ? 'signed-in people' : 'officeholders'
  let head: string
  if (roles.length) {
    const plurals = labels(roles, (k) => o.roles.find((r) => r.key === k)?.plural)
    head = joinList(plurals)
    // A role that implies the chosen level ("Regional Qaids" + Regional) doesn't need the level repeated.
    const first = ROLE_LEVEL[roles[0]]
    const redundant = first !== undefined && roles.every((r) => ROLE_LEVEL[r] === first) && levelsList.length === 1 && levelsList[0] === first
    if (levels.length && !redundant) {
      head += ` at the ${joinList(levels)} level`
    }
  } else if (levels.length) {
    head = `${joinList(levels)} ${noun}`
  } else {
    head = noun[0].toUpperCase() + noun.slice(1)
  }

  const parts = [head]
  const tail: string[] = []
  if (departments.length) {
    tail.push(`in ${joinList(labels(departments, (k) => o.departments.find((d) => d.key === k)?.name))}`)
  }
  if (regions.length) {
    const names = labels(regions, (n) => o.regions.find((r) => r.name === n)?.name)
    tail.push(`in the ${joinList(names)} ${regions.length === 1 ? 'region' : 'regions'}`)
  }
  if (majlis.length) {
    tail.push(`in ${joinList(labels(majlis, (n) => o.majlis.find((m) => m.name === n)?.name))}`)
  }
  parts.push(...tail)
  let out = parts[0] + (tail.length ? ' ' + tail.join(', ') : '')
  if (hasUnknownKey) out += ' (unknown filter)'
  return out
}

function showPhrase(rule: Rule, o: DescribeOptions): string {
  return rule.groups.map((g) => describeGroup(g, o)).join(', plus ')
}

function lowerFirst(phrase: string, o: DescribeOptions): string {
  const first = phrase.split(' ')[0]
  const always = ['All', 'Signed-in', 'Everyone', 'Officeholders']
  const levelThenNoun =
    o.levels.some((l) => l.label === first.replace(',', '')) && /officeholders|signed-in people/.test(phrase.split(' in ')[0])
  return always.includes(first) || levelThenNoun ? first.toLowerCase() + phrase.slice(first.length) : phrase
}

export function describeRule(rule: unknown, options: DescribeOptions): string {
  if (!isDescribable(rule)) return INVALID_LABEL
  if (rule.v > 1) return NEWER_LABEL
  const phrase = showPhrase(rule, options)
  if (rule.mode === 'show') return phrase
  if (phrase === 'Everyone signed in') return 'Nobody signed in'
  return `Everyone except ${lowerFirst(phrase, options)}`
}

export function ariaLabelForRule(rule: unknown, options: DescribeOptions): string {
  if (!isDescribable(rule)) return 'Section audience needs fixing'
  if (rule.v > 1) return 'Section made with a newer editor'
  return `Section visible to ${describeRule(rule, options)}`
}

export function levelTone(rule: unknown): LevelTone {
  if (!isDescribable(rule) || rule.v > 1) return 'mixed'
  if (rule.mode === 'hide') return 'hide'
  if (rule.groups.length !== 1) return 'mixed'
  const g = rule.groups[0]
  if (g.officeholder === false) return 'mixed'
  if (Array.isArray(g.level) && g.level.length === 1) {
    const l = g.level[0]
    if (l === 'national' || l === 'regional' || l === 'local') return l
  }
  return 'mixed'
}
