// Deterministic ground truth for the audience harness page, from the product's own pure evaluator + synthetic personas.
import { evaluateRule } from '../../../apps/web/components/mka/audience/evaluate'
import { MOCK_PERSONAS } from '../../../apps/web/services/mka/attributes.mock'

export const PERSONAS = MOCK_PERSONAS
const rule = (level: string, mode = 'show') => ({ v: 1, mode, groups: [{ level: [level] }] })
export const SECTIONS = [
  { marker: 'LOCAL-ONLY', audience: 'Local officeholders', rule: rule('local') },
  { marker: 'REGIONAL-ONLY', audience: 'Regional officeholders', rule: rule('regional') },
  { marker: 'NOT-LOCAL', audience: 'everyone except Local officeholders', rule: rule('local', 'hide') },
]
export type Persona = (typeof PERSONAS)[number]
export function expected(p: Persona) {
  return SECTIONS.map((s) => ({ ...s, visible: evaluateRule(s.rule, p.attributes) }))
}
/** Compare page text to the oracle. Returns human-readable mismatches. */
export function checkText(text: string, p: Persona): string[] {
  const bad: string[] = []
  for (const s of expected(p)) {
    const shown = text.includes(`${s.marker}: `) || text.includes(`${s.marker} heading`)
    if (shown && !s.visible) bad.push(`${s.marker} section (for ${s.audience}) is visible to ${p.label} but should be hidden`)
    if (!shown && s.visible) bad.push(`${s.marker} section is missing for ${p.label} but should be visible`)
  }
  return bad
}
