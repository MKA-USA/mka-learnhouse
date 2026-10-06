// MKA fork — keep hidden audience content out of the viewer's editor STATE (not only out of the DOM).
//
// Upstream code reads `editor.state.doc` directly (TableOfContents lists headings, AICanvaToolkit sends
// `doc.textBetween` to AI, copy serializes the selection), so DOM-detaching hidden sections is not enough for a
// learner. For a learner view, once /me has resolved, the document is replaced by a filtered copy of the ORIGINAL
// document in which every non-matching section keeps its node and attrs (so learner notes still compute) but holds a
// single empty paragraph. The original is kept in extension storage and the filter always re-runs from it.
import { Fragment, Slice } from '@tiptap/pm/model'
import { EditorState } from '@tiptap/pm/state'
import type { Node as PMNode } from '@tiptap/pm/model'
import { evaluateRule } from '../audience/evaluate'
import type { MkaViewerAttributes } from '../audience/types'
import { AUDIENCE_NODE } from './plugins'
import type { CopyPolicy } from './store'

type JSONNode = { type?: string; attrs?: { rule?: unknown } | null; content?: JSONNode[] }

/** Pure: replaces the content of each non-matching section with one empty paragraph. */
export function filterDocJSON<T extends JSONNode>(node: T, viewer: MkaViewerAttributes | null): T {
  if (node.type === AUDIENCE_NODE && !evaluateRule(node.attrs?.rule, viewer)) {
    return { ...node, content: [{ type: 'paragraph' }] }
  }
  if (!node.content) return node
  return { ...node, content: node.content.map((c) => filterDocJSON(c, viewer)) }
}

/** Pure: replaces the content of EVERY section with one empty paragraph (nodes and attrs are kept). */
export function emptyAllSectionsJSON<T extends JSONNode>(node: T): T {
  if (node.type === AUDIENCE_NODE) return { ...node, content: [{ type: 'paragraph' }] }
  if (!node.content) return node
  return { ...node, content: node.content.map((c) => emptyAllSectionsJSON(c)) }
}

/** Fragment-level filter used for copy/cut. `viewer === undefined` drops every section; a viewer keeps matches only. */
export function filterFragment(fragment: Fragment, keep: (node: PMNode) => boolean): Fragment {
  const out: PMNode[] = []
  fragment.forEach((child) => {
    if (child.type.name === AUDIENCE_NODE && !keep(child)) return
    out.push(child.content.size ? child.copy(filterFragment(child.content, keep)) : child)
  })
  return Fragment.fromArray(out)
}

export function keepFor(policy: CopyPolicy): (node: PMNode) => boolean {
  if (policy.kind === 'all') return () => true
  if (policy.kind === 'none') return () => false
  return (node) => evaluateRule(node.attrs.rule, policy.viewer)
}

export function transformCopiedSlice(slice: Slice, policy: CopyPolicy): Slice {
  if (policy.kind === 'all') return slice
  return new Slice(filterFragment(slice.content, keepFor(policy)), slice.openStart, slice.openEnd)
}

type EditorLike = { state: any; view: any; storage: Record<string, any>; emit: (event: any, ...args: any[]) => unknown }

/** Re-applies the filter from the original document. `viewer: 'all'` restores the full document. */
export function applyLearnerFilter(editor: EditorLike, viewer: MkaViewerAttributes | null | 'all' | 'none'): boolean {
  const storage = editor.storage.mkaAudience
  const original = storage?.original
  if (!original) return false
  const target = viewer === 'all' ? original : viewer === 'none' ? emptyAllSectionsJSON(original) : filterDocJSON(original, viewer)
  const doc: PMNode = editor.state.schema.nodeFromJSON(target)
  if (doc.eq(editor.state.doc)) return false
  // Not a transaction on purpose. DynamicCanva (the learner viewer) installs upstream's NoTextInput plugin, whose
  // filterTransaction rejects EVERY doc-changing transaction, ours included. The viewer is read-only and keeps no
  // history, so we swap in a fresh state over the same plugins and doc instead (selection resets to the start,
  // plugin state is re-initialised; both are irrelevant for a read-only viewer).
  storage.stripping = true
  try {
    const next = EditorState.create({ schema: editor.state.schema, doc, plugins: editor.state.plugins })
    editor.view.updateState(next)
    // Upstream's TableOfContents refreshes only on `update`. Viewer editors have no persistence listeners
    // (DynamicCanva / EditorPreview never save content), so this is safe.
    editor.emit('update', { editor, transaction: next.tr, appendedTransactions: [] })
  } finally {
    storage.stripping = false
  }
  return true
}
