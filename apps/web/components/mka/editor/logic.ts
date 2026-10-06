// MKA fork — pure decision logic for Audience sections (contract §3.3). No React, no DOM.
import { evaluateRule, validateRule } from '../audience/evaluate'
import { hidesAllOfficeholders } from '../audience/rule-edit'
import type { AudienceOptions, AudienceView, AudienceWarning, MkaViewerAttributes, Rule } from '../audience/types'

/**
 * What a section does for one viewer:
 *  - content:     render the content, no chrome (learner match, or an author's preview match)
 *  - hidden:      render nothing; the content must NOT be in the document DOM
 *  - placeholder: author preview of a non-match: dashed "Hidden for this viewer" stand-in
 *  - chrome:      render everything with the author header / read-only "Visible to" badge
 *  - loading:     viewer unknown yet; render nothing (no flash)
 */
export type SectionMode = 'content' | 'hidden' | 'placeholder' | 'chrome' | 'loading'

export type ViewerLoad = 'loading' | 'ready' | 'error'

export type ResolveInput = {
  view: AudienceView
  viewerState: ViewerLoad
  viewer: MkaViewerAttributes | null
  canViewAll: boolean
  /** True only for the authoring editor (EditorContext `isEditable`). */
  editable: boolean
  rule: unknown
}

export function resolveSectionMode(i: ResolveInput): SectionMode {
  const { view, viewerState, viewer, canViewAll, editable, rule } = i
  if (editable) {
    // Authoring never depends on /me for the default view: authors must never lose sight of their content.
    if (view.kind === 'author') return 'chrome'
    if (view.kind === 'persona') return evaluateRule(rule, view.attributes) ? 'content' : 'placeholder'
    if (viewerState === 'loading') return 'loading'
    return evaluateRule(rule, viewer) ? 'content' : 'placeholder'
  }

  // Viewing: /me decides everything, nothing renders until it is known.
  if (viewerState === 'loading') return 'loading'
  if (canViewAll) {
    if (view.kind === 'author') return 'chrome'
    const effective = view.kind === 'persona' ? view.attributes : viewer
    return evaluateRule(rule, effective) ? 'content' : 'placeholder'
  }
  // Learners can never pick a view: it is ignored. Error/anonymous => null viewer (fail closed).
  return evaluateRule(rule, viewer) ? 'content' : 'hidden'
}

/** Thin "Visible to" label shown over matching content only while someone with authoring rights previews. */
export function showsPreviewLabel(mode: SectionMode, view: AudienceView, editable: boolean, canViewAll: boolean): boolean {
  return mode === 'content' && view.kind !== 'author' && (editable || canViewAll)
}

// ---- learner notes -----------------------------------------------------------------------------

export const DEFAULT_COPY = {
  unrecognized_note:
    "Parts of this lesson are tailored by role. We couldn't recognise your role from your sign-in. Contact your administrator.",
  empty_lesson: 'Nothing in this lesson applies to your role. You can mark it complete and continue.',
}

type JSONNode = { type?: string; attrs?: { rule?: unknown } | null; content?: JSONNode[]; text?: string }

const RECOGNISED = new Set(['matched', 'partial', 'not_applicable'])

export type LearnerNotes = { unrecognized: boolean; emptyLesson: boolean; hiddenCount: number }

const isBlankTop = (n: JSONNode) =>
  n.type === 'paragraph' && !(n.content ?? []).some((c) => c.type !== 'text' || (c.text ?? '').trim() !== '')

/**
 * Notes shown once per activity to learners (top of the document).
 *  - unrecognized: the viewer's status is not recognised AND >=1 section is hidden.
 *  - emptyLesson: >=1 section is hidden AND every top-level node is a hidden section or an empty paragraph.
 * Anonymous viewers (`viewer === null`) get no unrecognized note: there is no sign-in to recognise.
 */
export function computeLearnerNotes(doc: unknown, viewer: MkaViewerAttributes | null): LearnerNotes {
  const top = ((doc as JSONNode | null)?.content ?? []) as JSONNode[]
  let hiddenCount = 0
  const walk = (n: JSONNode) => {
    if (n.type === 'mkaAudience') {
      if (!evaluateRule(n.attrs?.rule, viewer)) {
        hiddenCount += 1
        return // content of a hidden section is never evaluated
      }
    }
    for (const c of n.content ?? []) walk(c)
  }
  for (const n of top) walk(n)
  const everyTopHidden =
    top.length > 0 &&
    top.every((n) => (n.type === 'mkaAudience' && !evaluateRule(n.attrs?.rule, viewer)) || isBlankTop(n))
  return {
    hiddenCount,
    unrecognized: hiddenCount > 0 && viewer !== null && !RECOGNISED.has(String(viewer.status)),
    emptyLesson: hiddenCount > 0 && everyTopHidden,
  }
}

export function countSections(doc: unknown): number {
  let n = 0
  const walk = (x: JSONNode) => {
    if (x.type === 'mkaAudience') n += 1
    for (const c of x.content ?? []) walk(c)
  }
  walk(doc as JSONNode)
  return n
}

// ---- author warnings ---------------------------------------------------------------------------

/** Values in the rule that the current rules data no longer knows (renamed department, ...). */
export function unknownValues(rule: Rule, options: AudienceOptions | undefined): string[] {
  if (!options) return []
  const known: Record<string, Set<string>> = {
    level: new Set(options.levels.map((l) => l.key)),
    department: new Set(options.departments.map((d) => d.key)),
    role: new Set(options.roles.map((r) => r.key)),
    region: new Set(options.regions.map((r) => r.name)),
    majlis: new Set(options.majlis.map((m) => m.name)),
  }
  const out: string[] = []
  for (const g of rule.groups) {
    for (const [key, set] of Object.entries(known)) {
      for (const v of (g[key] as string[] | undefined) ?? []) if (!set.has(v) && !out.includes(v)) out.push(v)
    }
  }
  return out
}

export function ruleWarnings(raw: unknown, options: AudienceOptions | undefined, zero: boolean): AudienceWarning[] {
  const res = validateRule(raw)
  if (!res.ok) return [{ kind: 'invalid' }]
  const warnings: AudienceWarning[] = []
  if (res.rule.v > 1) warnings.push({ kind: 'newer_version' })
  if (hidesAllOfficeholders(res.rule)) warnings.push({ kind: 'only_non_officeholders' })
  const unknown = unknownValues(res.rule, options)
  if (unknown.length) warnings.push({ kind: 'unknown_values', values: unknown })
  if (zero) warnings.push({ kind: 'zero' })
  return warnings
}

/** Authors may not edit a rule written by a newer editor. A damaged rule stays editable: the picker replaces it. */
export function isRuleEditable(raw: unknown): boolean {
  const res = validateRule(raw)
  return !(res.ok && res.rule.v > 1)
}
