// MKA fork — pure helpers the audience picker uses to edit a rule. No React.
import { describeRule, type DescribeOptions } from './describe'
import { DEFAULT_RULE, RULE_LIST_KEYS, type Group, type Preset, type Rule, type RuleListKey } from './types'

/** Drop empty lists, de-duplicate, and refresh the cached label (or drop it when we cannot describe). */
export function normalizeRule(rule: Rule, options?: DescribeOptions): Rule {
  const groups = rule.groups.map((g): Group => {
    const next: Group = { ...g }
    for (const k of RULE_LIST_KEYS) {
      const list = next[k]
      if (!Array.isArray(list)) continue
      const unique = Array.from(new Set(list))
      if (unique.length === 0) delete next[k]
      else next[k] = unique
    }
    return next
  })
  const out: Rule = { ...rule, groups: groups.length ? groups : [{}] }
  if (options) out.label = describeRule(out, options)
  else delete out.label
  return out
}

export const firstGroup = (rule: Rule): Group => rule.groups[0] ?? {}

export function listOf(rule: Rule, key: RuleListKey): string[] {
  const v = firstGroup(rule)[key]
  return Array.isArray(v) ? v : []
}

export function setList(rule: Rule, key: RuleListKey, values: string[], options?: DescribeOptions): Rule {
  const [first, ...rest] = rule.groups.length ? rule.groups : [{}]
  return normalizeRule({ ...rule, groups: [{ ...first, [key]: values }, ...rest] }, options)
}

export function toggleValue(rule: Rule, key: RuleListKey, value: string, options?: DescribeOptions): Rule {
  const cur = listOf(rule, key)
  return setList(rule, key, cur.includes(value) ? cur.filter((v) => v !== value) : [...cur, value], options)
}

export function replaceValue(rule: Rule, key: RuleListKey, from: string, to: string, options?: DescribeOptions): Rule {
  const cur = listOf(rule, key)
  return setList(rule, key, cur.map((v) => (v === from ? to : v)), options)
}

export function setMode(rule: Rule, mode: Rule['mode'], options?: DescribeOptions): Rule {
  return normalizeRule({ ...rule, mode }, options)
}

/** Whole region picked: swap that region's Majlis for the region row. */
export function selectWholeRegion(rule: Rule, region: string, majlisInRegion: string[], options?: DescribeOptions): Rule {
  const inRegion = new Set(majlisInRegion)
  const majlis = listOf(rule, 'majlis').filter((m) => !inRegion.has(m))
  const regions = listOf(rule, 'region')
  const withMajlis = setList(rule, 'majlis', majlis)
  return setList(withMajlis, 'region', regions.includes(region) ? regions : [...regions, region], options)
}

type Known = Pick<DescribeOptions, 'levels' | 'departments' | 'roles' | 'regions' | 'majlis'>

/** Values in the rule that the current rules file does not know. */
export function unknownValues(rule: Rule, o: Known): { key: RuleListKey; value: string }[] {
  const known: Record<RuleListKey, Set<string>> = {
    level: new Set(o.levels.map((l) => l.key)),
    department: new Set(o.departments.map((d) => d.key)),
    role: new Set(o.roles.map((r) => r.key)),
    region: new Set(o.regions.map((r) => r.name)),
    majlis: new Set(o.majlis.map((m) => m.name)),
  }
  return RULE_LIST_KEYS.flatMap((key) => listOf(rule, key).filter((v) => !known[key].has(v)).map((value) => ({ key, value })))
}

/** Presets that can be offered: "My department" needs an author department we recognise. */
export function resolvePresets(presets: Preset[], authorDepartment: string | null, knownDepartments: string[]): Preset[] {
  return presets.flatMap((p) => {
    if (!p.needs_author_department) return [p]
    if (!authorDepartment || !knownDepartments.includes(authorDepartment)) return []
    return [{ ...p, rule: { ...p.rule, groups: [{ department: [authorDepartment] }] } }]
  })
}

export function applyPreset(preset: Preset, options?: DescribeOptions): Rule {
  return normalizeRule({ v: 1, mode: 'show', groups: preset.rule.groups.map((g) => ({ ...g })) }, options)
}

export const sameGroups = (a: Rule, b: Rule) => JSON.stringify(normalizeRule(a).groups) === JSON.stringify(normalizeRule(b).groups)

export const hasRoleKey = (rule: Rule) => rule.groups.some((g) => Array.isArray(g.role) && g.role.length > 0)

export const emptyRule = (): Rule => ({ ...DEFAULT_RULE, groups: [{}] })

/** A "Hide from" rule with a group that matches every officeholder: only people who are not officeholders keep the section. */
export function hidesAllOfficeholders(rule: Rule): boolean {
  if (rule.mode !== 'hide' || rule.v > 1) return false
  return rule.groups.some((g) => g.officeholder !== false && Object.keys(g).every((k) => k === 'officeholder' || (Array.isArray(g[k]) && (g[k] as unknown[]).length === 0)))
}

export const ONLY_NON_OFFICEHOLDERS_NOTE = "Only people who aren't officeholders will see this."
