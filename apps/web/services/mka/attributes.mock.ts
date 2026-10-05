/**
 * Deterministic MOCK layer for the Audience block (dev / screenshots only).
 * Enabled by NEXT_PUBLIC_MKA_AUDIENCE_MOCK=1 and never in a production build (see attributes.ts).
 * Everything here is synthetic: `example.invalid` mailboxes, invented personas (contract §2.1).
 *
 * Dev switches (query string): `?mka_viewer=<persona id>` picks the signed-in viewer,
 * `?mka_admin=1` makes the viewer an author/admin (`can_view_all`).
 */
import { evaluateRule } from '@components/mka/audience/evaluate'
import type {
  AudienceCount,
  AudienceOptions,
  Counterparts,
  MkaMeResponse,
  MkaViewerAttributes,
  Persona,
  Preset,
  Rule,
} from '@components/mka/audience/types'

const NULLS: MkaViewerAttributes = {
  status: 'unrecognized',
  is_officeholder: null,
  level: null,
  department: null,
  role: null,
  role_title: null,
  majlis: null,
  region: null,
}

export const MOCK_PERSONAS: Persona[] = [
  {
    id: 'local-nazim-tabligh-albany',
    label: 'Local Nazim Tabligh · Albany',
    attributes: { status: 'matched', is_officeholder: true, level: 'local', department: 'tabligh', role: 'nazim_dept', role_title: 'Nazim Tabligh', majlis: 'Albany', region: 'Northeast' },
  },
  {
    id: 'local-qaid-houston',
    label: 'Local Qaid · Houston',
    attributes: { status: 'matched', is_officeholder: true, level: 'local', department: null, role: 'qaid', role_title: 'Qaid', majlis: 'Houston', region: 'Gulf' },
  },
  {
    id: 'regional-qaid-northeast',
    label: 'Regional Qaid · Northeast',
    attributes: { status: 'matched', is_officeholder: true, level: 'regional', department: null, role: 'regional_qaid', role_title: 'Regional Qaid', majlis: null, region: 'Northeast' },
  },
  {
    id: 'mohtamim-tabligh-national',
    label: 'Mohtamim Tabligh (National)',
    attributes: { status: 'matched', is_officeholder: true, level: 'national', department: 'tabligh', role: 'mohtamim', role_title: 'Mohtamim Tabligh', majlis: null, region: null },
  },
  {
    id: 'regional-nazim-tabligh-northeast',
    label: 'Regional Nazim Tabligh · Northeast',
    attributes: { status: 'matched', is_officeholder: true, level: 'regional', department: 'tabligh', role: 'regional_nazim_dept', role_title: 'Regional Nazim Tabligh', majlis: null, region: 'Northeast' },
  },
  { id: 'unrecognized-account', label: 'Unrecognized account', attributes: { ...NULLS } },
  {
    id: 'not-an-officeholder',
    label: 'Not an officeholder',
    attributes: { ...NULLS, status: 'not_applicable', is_officeholder: false },
  },
]

const DEPARTMENTS: [string, string][] = [
  ['aitmad', 'Aitmad'], ['tabligh', 'Tabligh'], ['tarbiyyat', 'Tarbiyyat'], ['maal', 'Maal'],
  ['sanat_o_tijarat', 'Sanat-o-Tijarat'], ['sehat_e_jismani', 'Sehat-e-Jismani'], ['ishaat', 'Ishaat'],
  ['khidmat_e_khalq', 'Khidmat-e-Khalq'], ['tahrik_e_jadid', 'Tahrik-e-Jadid'], ['tajneed', 'Tajneed'],
  ['taleem', 'Taleem'], ['nau_mubaeen', 'Nau Mubaeen'], ['amoomi', 'Amoomi'], ['amoor_e_tuluba', 'Amoor-e-Tuluba'],
  ['waqar_e_amal', 'Waqar-e-Amal'], ['mohasib', 'Mohasib'], ['rishta_nata', 'Rishta Nata'], ['wasiyyat', 'Wasiyyat'],
  ['waqf_e_nau', 'Waqf-e-Nau'], ['new_immigrants', 'New Immigrants'], ['atfal', 'Atfal'],
]

const MAJLIS_REGION: [string, string][] = [
  ['Baltimore', 'East'], ['Central Jersey', 'East'], ['Harrisburg', 'East'], ['North Jersey', 'East'], ['Philadelphia', 'East'], ['Willingboro', 'East'],
  ['Cleveland', 'Great Lakes'], ['Columbus', 'Great Lakes'], ['Dayton', 'Great Lakes'], ['Detroit', 'Great Lakes'], ['Indiana', 'Great Lakes'], ['Kentucky', 'Great Lakes'],
  ['Austin', 'Gulf'], ['Dallas', 'Gulf'], ['Fort Worth', 'Gulf'], ['Houston', 'Gulf'], ['Tulsa', 'Gulf'],
  ['Chicago', 'Midwest'], ['Kansas City', 'Midwest'], ['Milwaukee', 'Midwest'], ['Minnesota', 'Midwest'], ['Oshkosh', 'Midwest'], ['Saint Louis', 'Midwest'], ['Zion', 'Midwest'],
  ['Muqami', 'Muqami'],
  ['Bronx', 'New York Metro'], ['Brooklyn', 'New York Metro'], ['Long Island', 'New York Metro'], ['Queens', 'New York Metro'],
  ['Albany', 'Northeast'], ['Boston', 'Northeast'], ['Connecticut', 'Northeast'], ['Rochester', 'Northeast'], ['Syracuse-Binghamton', 'Northeast'],
  ['Bay Point', 'Northwest'], ['Portland', 'Northwest'], ['Sacramento', 'Northwest'], ['Seattle', 'Northwest'], ['Silicon Valley', 'Northwest'],
  ['Atlanta', 'Southeast'], ['Charlotte', 'Southeast'], ['Miami', 'Southeast'], ['Orlando', 'Southeast'], ['Tennessee', 'Southeast'],
  ['Las Vegas', 'Southwest'], ['Los Angeles', 'Southwest'], ['Phoenix', 'Southwest'], ['Tucson', 'Southwest'],
  ['North Virginia', 'Virginia'], ['South Virginia', 'Virginia'], ['Richmond', 'Virginia'], ['RTP', 'Virginia'],
]

const rule = (g: Rule['groups'][number]): Rule => ({ v: 1, mode: 'show', groups: [g] })

const PRESETS: Preset[] = [
  { id: 'local', label: 'Local officeholders', rule: rule({ level: ['local'] }) },
  { id: 'regional-qaids', label: 'Regional Qaids', rule: rule({ level: ['regional'], role: ['regional_qaid'] }) },
  { id: 'national', label: 'National team', rule: rule({ level: ['national'] }) },
  { id: 'qaids', label: 'Qaids & Naib Qaids', rule: rule({ role: ['qaid', 'naib_qaid'] }) },
  { id: 'motamids', label: 'Motamids', rule: rule({ role: ['motamid', 'regional_motamid'] }) },
  { id: 'my-department', label: 'My department', rule: rule({}), needs_author_department: true },
]

export function mockOptions(): AudienceOptions {
  return {
    rules_version: '2026.1',
    levels: [
      { key: 'national', label: 'National' },
      { key: 'regional', label: 'Regional' },
      { key: 'local', label: 'Local' },
    ],
    departments: DEPARTMENTS.map(([key, name]) => ({ key, name, aka: [] })),
    roles: [
      { key: 'sadr', title: 'Sadr', plural: 'Sadrs' },
      { key: 'naib_sadr', title: 'Naib Sadr', plural: 'Naib Sadrs' },
      { key: 'mohtamim', title: 'Mohtamim (department)', plural: 'Mohtamims' },
      { key: 'nazim_dept', title: 'Nazim (department)', plural: 'Nazims' },
      { key: 'qaid', title: 'Qaid', plural: 'Qaids' },
      { key: 'naib_qaid', title: 'Naib Qaid', plural: 'Naib Qaids' },
      { key: 'regional_qaid', title: 'Regional Qaid', plural: 'Regional Qaids' },
      { key: 'motamid', title: 'Motamid', plural: 'Motamids' },
      { key: 'regional_nazim_dept', title: 'Regional Nazim (department)', plural: 'Regional Nazims' },
      { key: 'regional_motamid', title: 'Regional Motamid', plural: 'Regional Motamids' },
      { key: 'nazim_atfal', title: 'Nazim Atfal', plural: 'Nazim Atfal' },
      { key: 'murabbi_atfal', title: 'Murabbi Atfal', plural: 'Murabbi Atfal' },
      { key: 'national_staff', title: 'National staff', plural: 'National staff' },
    ],
    regions: Array.from(new Set(MAJLIS_REGION.map(([, r]) => r))).map((name) => ({ name })),
    majlis: MAJLIS_REGION.map(([name, region]) => ({ name, region })),
    presets: PRESETS,
    personas: MOCK_PERSONAS,
    copy: {
      not_secret: 'This controls what people see. It is not a security boundary: do not put secrets in a section.',
      unrecognized_note:
        "Parts of this lesson are tailored by role. We couldn't recognise your role from your sign-in. Contact your administrator.",
      empty_lesson: 'Nothing in this lesson applies to your role. You can mark it complete and continue.',
      count_tooltip: 'Counts organisation members whose current attributes match. Aggregates only.',
    },
  }
}

function search(): URLSearchParams {
  return new URLSearchParams(typeof window !== 'undefined' ? window.location.search : '')
}

export function mockMe(): MkaMeResponse {
  const q = search()
  const id = q.get('mka_viewer') || MOCK_PERSONAS[0].id
  const persona = MOCK_PERSONAS.find((p) => p.id === id) ?? MOCK_PERSONAS[0]
  return {
    attributes: persona.attributes,
    stale: false,
    can_view_all: q.get('mka_admin') === '1',
    rules_version: '2026.1',
  }
}

// Synthetic population: persona attributes repeated with fixed multiplicities.
const POPULATION: [string, number][] = [
  ['local-nazim-tabligh-albany', 24],
  ['local-qaid-houston', 20],
  ['regional-qaid-northeast', 6],
  ['mohtamim-tabligh-national', 8],
  ['regional-nazim-tabligh-northeast', 12],
  ['unrecognized-account', 3],
  ['not-an-officeholder', 40],
]

export function mockCount(raw: unknown): AudienceCount {
  let count = 0
  let totalOfficeholders = 0
  let unrecognized = 0
  const byLevel = { national: 0, regional: 0, local: 0 }
  for (const [id, n] of POPULATION) {
    const p = MOCK_PERSONAS.find((x) => x.id === id)!
    const a = p.attributes
    if (a.is_officeholder === true) totalOfficeholders += n
    if (a.status !== 'matched' && a.status !== 'partial' && a.status !== 'not_applicable') unrecognized += n
    if (evaluateRule(raw, a)) {
      count += n
      if (a.level) byLevel[a.level] += n
    }
  }
  return { count, total_officeholders: totalOfficeholders, unrecognized, by_level: byLevel, expected: { matching: count, total: totalOfficeholders + 2, cycle_id: 1 } }
}

export function mockCounterparts(): Counterparts {
  return {
    reason: null,
    counterparts: [
      { level: 'national', role_title: 'Mohtamim Tabligh', email: 'tabligh@example.invalid', name: null, department: 'tabligh' },
      { level: 'regional', role_title: 'Regional Nazim Tabligh', email: 'tabligh.northeast@example.invalid', name: null, department: 'tabligh' },
      { level: 'regional', role_title: 'Regional Qaid', email: 'qaid.northeast@example.invalid', name: null, department: null },
    ],
  }
}

const PEOPLE = [
  { user_id: 9001, display_name: 'Sample Person One', email: 'sample.one@example.invalid' },
  { user_id: 9002, display_name: 'Sample Person Two', email: 'sample.two@example.invalid' },
  { user_id: 9003, display_name: 'Sample Person Three', email: 'sample.three@example.invalid' },
]

export function mockPeople(q: string) {
  const needle = q.trim().toLowerCase()
  return { people: needle.length < 2 ? [] : PEOPLE.filter((p) => `${p.display_name} ${p.email}`.toLowerCase().includes(needle)) }
}

export function mockPerson(userId: number): { attributes: MkaViewerAttributes } {
  const idx = Math.max(0, PEOPLE.findIndex((p) => p.user_id === userId))
  return { attributes: MOCK_PERSONAS[idx % MOCK_PERSONAS.length].attributes }
}
