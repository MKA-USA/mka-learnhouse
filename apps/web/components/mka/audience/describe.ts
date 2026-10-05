// PLACEHOLDER — replaced by seam c
// Minimal stand-in for describeRule (contract §1.4). Seam b only needs *a* label string; no logic here is depended on.
import type { AudienceOptions, Rule } from './types'

export function describeRule(rule: Rule, _options?: Pick<AudienceOptions, 'departments' | 'roles' | 'levels'>): string {
  const first = rule.groups[0] ?? {}
  const parts = ['level', 'department', 'role', 'region', 'majlis']
    .flatMap((k) => (Array.isArray(first[k]) ? (first[k] as string[]) : []))
    .join(', ')
  const who = parts ? `Officeholders: ${parts}` : first.officeholder === false ? 'Everyone signed in' : 'All officeholders'
  return rule.mode === 'hide' ? `Everyone except ${who}` : who
}
