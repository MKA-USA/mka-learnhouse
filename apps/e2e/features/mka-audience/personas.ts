/**
 * Synthetic personas for the audience e2e. Accounts live on e2e-tests.com (a non-MKA domain: password login works and
 * no real officeholder is ever touched). The API's email validator rejects reserved TLDs (.invalid/.test/.example),
 * so a normal throwaway domain is used, matching apps/e2e/core/instance.ts.
 *
 * Attributes come from the real admin override endpoint (PUT /mka/attributes/users/{id}/override), exactly what an
 * org admin would use for a personal-name officer, not from a mock.
 */
export const PERSONA_PASSWORD = 'E2ePersona!234'
export const EMAIL_DOMAIN = 'e2e-tests.com'

export type SectionKey = 'localTabligh' | 'regionalQaids' | 'national' | 'hideNational' | 'majlisAlbany'
export const SECTION_KEYS: SectionKey[] = ['localTabligh', 'regionalQaids', 'national', 'hideNational', 'majlisAlbany']

export type PersonaKey =
  | 'localNazim'
  | 'regionalQaid'
  | 'mohtamim'
  | 'regionalNazim'
  | 'unrecognized'
  | 'notOfficeholder'
  | 'admin'
  | 'author'

export interface CounterpartRow {
  role_title: string
  email: string
}

export interface PersonaDef {
  key: PersonaKey
  label: string
  /** Local part; the admin persona uses the stack's bootstrapped admin instead. */
  local: string
  /** Admin override (PUT /mka/attributes/users/{id}/override); null = leave the account without attributes. */
  override: Record<string, unknown> | null
  /** What the LEARNER view must show, by section. Admin/author see all five (see ALL_SECTIONS). */
  visible: SectionKey[]
  /** Value shown by {{my_majlis}} / {{my_region}} (null = the node's fallback text). */
  majlis: string | null
  region: string | null
  /** "Parts of this lesson are tailored by role" note expected. */
  unrecognizedNote: boolean
  /** Counterparts card rows (mailto addresses), in order; null = the "once your role is recognized" card instead. */
  counterparts: CounterpartRow[] | null
}

export const ALL_SECTIONS: SectionKey[] = SECTION_KEYS

const NATIONAL_TABLIGH: CounterpartRow = { role_title: 'Mohtamim Tabligh', email: 'tabligh@mkausa.org' }
const REGIONAL_NAZIM_NE: CounterpartRow = { role_title: 'Regional Nazim Tabligh', email: 'tabligh.northeast@mkausa.org' }
const REGIONAL_QAID_NE: CounterpartRow = { role_title: 'Regional Qaid', email: 'qaid.northeast@mkausa.org' }

export const PERSONAS: PersonaDef[] = [
  {
    key: 'localNazim',
    label: 'Local Nazim Tabligh · Albany',
    local: 'local-nazim-tabligh-albany',
    override: { level: 'local', department: 'tabligh', role: 'nazim_dept', majlis: 'Albany' },
    visible: ['localTabligh', 'hideNational', 'majlisAlbany'],
    majlis: 'Albany',
    region: 'Northeast',
    unrecognizedNote: false,
    counterparts: [NATIONAL_TABLIGH, REGIONAL_NAZIM_NE, REGIONAL_QAID_NE],
  },
  {
    key: 'regionalQaid',
    label: 'Regional Qaid · Northeast',
    local: 'regional-qaid-northeast',
    override: { level: 'regional', role: 'regional_qaid', region: 'Northeast' },
    visible: ['regionalQaids', 'hideNational'],
    majlis: null,
    region: 'Northeast',
    unrecognizedNote: false,
    counterparts: null, // no department and role not in {qaid, naib_qaid, motamid} => reason no_department => "recognized" card (see FINDINGS.md)
  },
  {
    key: 'mohtamim',
    label: 'Mohtamim Tabligh (National)',
    local: 'mohtamim-tabligh-national',
    override: { level: 'national', department: 'tabligh', role: 'mohtamim' },
    visible: ['national'],
    majlis: null,
    region: null,
    unrecognizedNote: false,
    counterparts: [NATIONAL_TABLIGH],
  },
  {
    key: 'regionalNazim',
    label: 'Regional Nazim Tabligh · Northeast',
    local: 'regional-nazim-tabligh-northeast',
    override: { level: 'regional', department: 'tabligh', role: 'regional_nazim_dept', region: 'Northeast' },
    visible: ['hideNational'],
    majlis: null,
    region: 'Northeast',
    unrecognizedNote: false,
    counterparts: [NATIONAL_TABLIGH, REGIONAL_QAID_NE],
  },
  {
    key: 'unrecognized',
    label: 'Unrecognized account',
    local: 'unrecognized-account',
    override: null,
    visible: ['hideNational'],
    majlis: null,
    region: null,
    unrecognizedNote: true,
    counterparts: null,
  },
  {
    key: 'notOfficeholder',
    label: 'Not an officeholder',
    local: 'not-an-officeholder',
    override: { status: 'not_applicable', is_officeholder: false },
    visible: ['hideNational'],
    majlis: null,
    region: null,
    unrecognizedNote: false,
    counterparts: null,
  },
  {
    key: 'author',
    label: 'Course author (CREATOR, not admin)',
    local: 'course-author',
    override: null,
    visible: ALL_SECTIONS,
    majlis: null,
    region: null,
    unrecognizedNote: false,
    counterparts: null,
  },
]

export const emailFor = (p: PersonaDef) => `${p.local}@${EMAIL_DOMAIN}`
