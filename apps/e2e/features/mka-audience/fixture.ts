/**
 * The fixture lesson: ProseMirror JSON saved through the real activity API.
 *
 * Every audience section carries a unique heading and a unique body marker, so "visible" and "absent from the DOM,
 * the table of contents and copied text" are plain substring checks.
 */
import type { SectionKey } from './personas'

export interface SectionDef {
  key: SectionKey
  heading: string
  body: string
  rule: { v: 1; mode: 'show' | 'hide'; groups: Record<string, unknown>[] }
  /** What the author header / admin badge must read. */
  label: string
}

export const SECTIONS: Record<SectionKey, SectionDef> = {
  localTabligh: {
    key: 'localTabligh',
    heading: 'ZQ Local Tabligh Heading',
    body: 'ZQ-BODY-LOCALTABLIGH-q81',
    rule: { v: 1, mode: 'show', groups: [{ level: ['local'], department: ['tabligh'] }] },
    label: 'Local officeholders in Tabligh',
  },
  regionalQaids: {
    key: 'regionalQaids',
    heading: 'ZQ Regional Qaids Heading',
    body: 'ZQ-BODY-REGIONALQAIDS-m47',
    rule: { v: 1, mode: 'show', groups: [{ level: ['regional'], role: ['regional_qaid'] }] },
    label: 'Regional Qaids',
  },
  national: {
    key: 'national',
    heading: 'ZQ National Team Heading',
    body: 'ZQ-BODY-NATIONAL-z02',
    rule: { v: 1, mode: 'show', groups: [{ level: ['national'] }] },
    label: 'National officeholders',
  },
  hideNational: {
    key: 'hideNational',
    heading: 'ZQ Hide From National Heading',
    body: 'ZQ-BODY-HIDENATIONAL-k93',
    rule: { v: 1, mode: 'hide', groups: [{ level: ['national'] }] },
    label: 'Everyone except national officeholders',
  },
  majlisAlbany: {
    key: 'majlisAlbany',
    heading: 'ZQ Majlis Albany Heading',
    body: 'ZQ-BODY-MAJLISALBANY-d15',
    rule: { v: 1, mode: 'show', groups: [{ majlis: ['Albany'] }] },
    label: 'Officeholders in Albany',
  },
}

export const UNTARGETED = {
  heading: 'ZQ Untargeted Heading',
  body: 'ZQ-BODY-UNTARGETED-a60',
}

export const V2_TAIL = 'ZQ-BODY-VERSION2-TAIL-t55'

const text = (t: string) => ({ type: 'text', text: t })
const para = (t: string) => ({ type: 'paragraph', content: [text(t)] })
const heading = (t: string) => ({ type: 'heading', attrs: { level: 2 }, content: [text(t)] })

const FIELD_ID: Record<SectionKey, string> = {
  localTabligh: '11111111-1111-4111-8111-111111111111',
  regionalQaids: '22222222-2222-4222-8222-222222222222',
  national: '33333333-3333-4333-8333-333333333333',
  hideNational: '44444444-4444-4444-8444-444444444444',
  majlisAlbany: '55555555-5555-4555-8555-555555555555',
}

function section(s: SectionDef) {
  return {
    type: 'mkaAudience',
    attrs: { id: FIELD_ID[s.key], rule: s.rule },
    content: [heading(s.heading), para(s.body)],
  }
}

export function lessonDoc(opts: { withV2Tail?: boolean } = {}) {
  const content: unknown[] = [
    heading(UNTARGETED.heading),
    para(UNTARGETED.body),
    {
      type: 'paragraph',
      content: [
        text('FIELDS Majlis: '),
        { type: 'mkaViewerField', attrs: { field: 'majlis', fallback: 'your Majlis' } },
        text(' Region: '),
        { type: 'mkaViewerField', attrs: { field: 'region', fallback: 'your region' } },
        text(' END'),
      ],
    },
    ...Object.values(SECTIONS).map(section),
    { type: 'mkaCounterparts', attrs: { id: '66666666-6666-4666-8666-666666666666' } },
  ]
  if (opts.withV2Tail) content.push(para(V2_TAIL))
  return { type: 'doc', content }
}

export const HIDDEN_FOR = (visible: SectionKey[]): SectionKey[] =>
  (Object.keys(SECTIONS) as SectionKey[]).filter((k) => !visible.includes(k))
