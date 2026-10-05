// MKA fork — DEV-ONLY synthetic AudienceOptions for the playground. Everything here is invented (emails use example.invalid).
import type { AudienceOptions, MkaViewerAttributes, Persona } from '@components/mka/audience/types'

const MAJLIS: Record<string, string[]> = {
  East: ['Baltimore', 'Central Jersey', 'Harrisburg', 'North Jersey', 'Philadelphia', 'Willingboro'],
  'Great Lakes': ['Cleveland', 'Columbus', 'Dayton', 'Detroit', 'Indiana', 'Kentucky'],
  Gulf: ['Austin', 'Dallas', 'Fort Worth', 'Houston', 'Tulsa'],
  Midwest: ['Chicago', 'Kansas City', 'Milwaukee', 'Minnesota', 'Oshkosh', 'Saint Louis', 'Zion'],
  Muqami: ['Muqami'],
  'New York Metro': ['Bronx', 'Brooklyn', 'Long Island', 'Queens'],
  Northeast: ['Albany', 'Boston', 'Connecticut', 'Rochester', 'Syracuse-Binghamton'],
  Northwest: ['Bay Point', 'Portland', 'Sacramento', 'Seattle', 'Silicon Valley'],
  Southeast: ['Atlanta', 'Charlotte', 'Miami', 'Orlando', 'Tennessee'],
  Southwest: ['Las Vegas', 'Los Angeles', 'Phoenix', 'Tucson'],
  Virginia: ['North Virginia', 'South Virginia', 'Richmond', 'RTP'],
}

const DEPARTMENTS: [string, string][] = [
  ['aitmad', 'Aitmad'], ['tabligh', 'Tabligh'], ['tarbiyyat', 'Tarbiyyat'], ['maal', 'Maal'],
  ['sanat_o_tijarat', 'Sanat-o-Tijarat'], ['sehat_e_jismani', 'Sehat-e-Jismani'], ['ishaat', 'Ishaat'],
  ['khidmat_e_khalq', 'Khidmat-e-Khalq'], ['tahrik_e_jadid', 'Tahrik-e-Jadid'], ['tajneed', 'Tajneed'],
  ['taleem', 'Taleem'], ['nau_mubaeen', 'Nau Mubaeen'], ['amoomi', 'Amoomi'], ['amoor_e_tuluba', 'Amoor-e-Tuluba'],
  ['waqar_e_amal', 'Waqar-e-Amal'], ['mohasib', 'Mohasib'], ['rishta_nata', 'Rishta Nata'], ['wasiyyat', 'Wasiyyat'],
  ['waqf_e_nau', 'Waqf-e-Nau'], ['new_immigrants', 'New Immigrants'], ['atfal', 'Atfal'],
]

const ROLES: [string, string, string][] = [
  ['sadr', 'Sadr', 'Sadrs'], ['naib_sadr', 'Naib Sadr', 'Naib Sadrs'], ['mohtamim', 'Mohtamim', 'Mohtamims'],
  ['nazim_dept', 'Nazim (department)', 'Nazims (department)'], ['qaid', 'Qaid', 'Qaids'],
  ['naib_qaid', 'Naib Qaid', 'Naib Qaids'], ['regional_qaid', 'Regional Qaid', 'Regional Qaids'],
  ['motamid', 'Motamid', 'Motamids'], ['regional_nazim_dept', 'Regional Nazim (department)', 'Regional Nazims (department)'],
  ['regional_motamid', 'Regional Motamid', 'Regional Motamids'], ['nazim_atfal', 'Nazim Atfal', 'Nazims Atfal'],
  ['murabbi_atfal', 'Murabbi Atfal', 'Murabbis Atfal'], ['national_staff', 'National staff', 'National staff'],
]

const attrs = (a: Partial<MkaViewerAttributes>): MkaViewerAttributes => ({
  status: 'matched', is_officeholder: true, level: null, department: null, role: null, role_title: null, majlis: null, region: null, ...a,
})

export const MOCK_PERSONAS: Persona[] = [
  { id: 'local-nazim-tabligh-albany', label: 'Local Nazim Tabligh · Albany', attributes: attrs({ level: 'local', department: 'tabligh', role: 'nazim_dept', role_title: 'Nazim Tabligh', majlis: 'Albany', region: 'Northeast' }) },
  { id: 'local-qaid-houston', label: 'Local Qaid · Houston', attributes: attrs({ level: 'local', role: 'qaid', role_title: 'Qaid', majlis: 'Houston', region: 'Gulf' }) },
  { id: 'regional-qaid-northeast', label: 'Regional Qaid · Northeast', attributes: attrs({ level: 'regional', role: 'regional_qaid', role_title: 'Regional Qaid', region: 'Northeast' }) },
  { id: 'mohtamim-tabligh', label: 'Mohtamim Tabligh (National)', attributes: attrs({ level: 'national', department: 'tabligh', role: 'mohtamim', role_title: 'Mohtamim Tabligh' }) },
  { id: 'atfal-nazim-syracuse', label: 'Atfal Nazim · Syracuse-Binghamton', attributes: attrs({ level: 'local', department: 'atfal', role: 'nazim_atfal', role_title: 'Nazim Atfal', majlis: 'Syracuse-Binghamton', region: 'Northeast' }) },
  { id: 'unrecognized', label: 'Unrecognized account', attributes: attrs({ status: 'unrecognized', is_officeholder: null }) },
  { id: 'not-officeholder', label: 'Not an officeholder', attributes: attrs({ status: 'not_applicable', is_officeholder: false }) },
]

export const MOCK_OPTIONS: AudienceOptions = {
  rules_version: '2026.1',
  levels: [{ key: 'national', label: 'National' }, { key: 'regional', label: 'Regional' }, { key: 'local', label: 'Local' }],
  departments: DEPARTMENTS.map(([key, name]) => ({ key, name, aka: [] })),
  roles: ROLES.map(([key, title, plural]) => ({ key, title, plural })),
  regions: Object.keys(MAJLIS).map((name) => ({ name })),
  majlis: Object.entries(MAJLIS).flatMap(([region, names]) => names.map((name) => ({ name, region }))),
  presets: [
    { id: 'local', label: 'Local officeholders', rule: { v: 1, mode: 'show', groups: [{ level: ['local'] }] } },
    { id: 'regional-qaids', label: 'Regional Qaids', rule: { v: 1, mode: 'show', groups: [{ level: ['regional'], role: ['regional_qaid'] }] } },
    { id: 'national', label: 'National team', rule: { v: 1, mode: 'show', groups: [{ level: ['national'] }] } },
    { id: 'qaids', label: 'Qaids & Naib Qaids', rule: { v: 1, mode: 'show', groups: [{ role: ['qaid', 'naib_qaid'] }] } },
    { id: 'motamids', label: 'Motamids', rule: { v: 1, mode: 'show', groups: [{ role: ['motamid', 'regional_motamid'] }] } },
    { id: 'my-dept', label: 'My department', rule: { v: 1, mode: 'show', groups: [{}] }, needs_author_department: true },
  ],
  personas: MOCK_PERSONAS,
  copy: {
    not_secret: "This only hides sections from the lesson page. It isn't a security feature, so don't put anything confidential in a section.",
    unrecognized_note: "Some content is hidden because we couldn't match your account to an officeholder role.",
    empty_lesson: 'Nothing in this lesson is meant for your role.',
    count_tooltip: "Counts people in this organization whose MKA profile matches. Accounts we couldn't recognize aren't counted.",
  },
}
