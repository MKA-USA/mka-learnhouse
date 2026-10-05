// MKA fork — Audience block shared types.
// Frozen contract: docs/superpowers/specs/2026-10-05-mka-audience-contracts.md

export type AudienceLevel = 'national' | 'regional' | 'local'
export type RuleListKey = 'level' | 'department' | 'role' | 'region' | 'majlis'
export const RULE_LIST_KEYS: readonly RuleListKey[] = ['level', 'department', 'role', 'region', 'majlis']

export type Group = {
  officeholder?: boolean
  level?: string[]
  department?: string[]
  role?: string[]
  region?: string[]
  majlis?: string[]
  // Unknown keys may be present in stored content (forward-compat); they make the group non-matching.
  [unknown: string]: unknown
}

export type Rule = {
  v: number
  mode: 'show' | 'hide'
  groups: Group[]
  label?: string
}

export const DEFAULT_RULE: Rule = { v: 1, mode: 'show', groups: [{}] }

export type MkaStatus = 'matched' | 'partial' | 'ambiguous' | 'unrecognized' | 'not_applicable'

/** PUBLIC_FIELDS of GET /mka/attributes/me `attributes`. */
export type MkaViewerAttributes = {
  status: MkaStatus | string
  is_officeholder: boolean | null
  level: AudienceLevel | null
  department: string | null
  role: string | null
  role_title: string | null
  majlis: string | null
  region: string | null
}

export type MkaMeResponse = {
  attributes: MkaViewerAttributes
  stale: boolean
  can_view_all: boolean
  rules_version: string
}

export type Preset = { id: string; label: string; rule: Rule; needs_author_department?: boolean }
export type Persona = { id: string; label: string; attributes: MkaViewerAttributes }

export type AudienceOptions = {
  rules_version: string
  levels: { key: AudienceLevel; label: string }[]
  departments: { key: string; name: string; aka: string[] }[]
  roles: { key: string; title: string; plural: string }[]
  regions: { name: string }[]
  majlis: { name: string; region: string }[]
  presets: Preset[]
  personas: Persona[]
  copy: { not_secret: string; unrecognized_note: string; empty_lesson: string; count_tooltip: string }
}

export type AudienceCount = {
  count: number
  total_officeholders: number
  unrecognized: number
  by_level: Record<AudienceLevel, number>
  expected: { matching: number; total: number; cycle_id: number } | null
}

export type CountState = { state: 'idle' | 'loading' | 'error' | 'ready'; data?: AudienceCount }

export type Counterpart = {
  level: AudienceLevel
  role_title: string
  email: string
  name: string | null
  department: string | null
}
export type Counterparts = { counterparts: Counterpart[]; reason: null | 'unrecognized' | 'no_department' }

/** Per-editor viewing mode (contracts §3.3). */
export type AudienceView =
  | { kind: 'author' }
  | { kind: 'self' }
  | { kind: 'persona'; label: string; attributes: MkaViewerAttributes | null }

export type AudienceWarning =
  | { kind: 'zero' }
  | { kind: 'only_unclassified' }
  | { kind: 'unknown_values'; values: string[] }
  | { kind: 'invalid' }
  | { kind: 'newer_version' }
