// MKA fork — ProseMirror transaction logic for audience sections (contract §3.2 invariants).
//  - unique ids (regenerated after paste/duplicate, B1.6)
//  - no nesting (an inner section is unwrapped, keeping its content)
import { Plugin, PluginKey } from '@tiptap/pm/state'
import type { EditorState, Transaction } from '@tiptap/pm/state'
import type { Node as PMNode } from '@tiptap/pm/model'

export const AUDIENCE_NODE = 'mkaAudience'
export const idsPluginKey = new PluginKey('mkaAudienceIds')

export function newAudienceId(): string {
  const c = (globalThis as { crypto?: { randomUUID?: () => string } }).crypto
  if (c?.randomUUID) return c.randomUUID()
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (ch) => {
    const r = (Math.random() * 16) | 0
    return (ch === 'x' ? r : (r & 0x3) | 0x8).toString(16)
  })
}

function findNested(doc: PMNode): { pos: number; node: PMNode } | null {
  let found: { pos: number; node: PMNode } | null = null
  doc.descendants((node, pos) => {
    if (found) return false
    if (node.type.name !== AUDIENCE_NODE) return true
    const $pos = doc.resolve(pos)
    for (let d = 0; d <= $pos.depth; d++) {
      if ($pos.node(d).type.name === AUDIENCE_NODE) {
        found = { pos, node }
        return false
      }
    }
    return true
  })
  return found
}

export type FixResult = { tr: Transaction; unwrapped: number; renamed: number } | null

/** Returns a transaction that restores the invariants, or null when the document already satisfies them. */
export function buildFixTransaction(state: EditorState): FixResult {
  const tr = state.tr
  let unwrapped = 0
  let renamed = 0
  for (let guard = 0; guard < 200; guard++) {
    const nested = findNested(tr.doc)
    if (!nested) break
    tr.replaceWith(nested.pos, nested.pos + nested.node.nodeSize, nested.node.content)
    unwrapped += 1
  }
  const seen = new Set<string>()
  tr.doc.descendants((node, pos) => {
    if (node.type.name !== AUDIENCE_NODE) return true
    const id = node.attrs.id as string | null
    if (!id || seen.has(id)) {
      const fresh = newAudienceId()
      tr.setNodeMarkup(pos, undefined, { ...node.attrs, id: fresh })
      seen.add(fresh)
      renamed += 1
    } else {
      seen.add(id)
    }
    return true
  })
  return unwrapped || renamed ? { tr, unwrapped, renamed } : null
}

export function createIdsPlugin(onUnwrap?: (count: number) => void): Plugin {
  return new Plugin({
    key: idsPluginKey,
    appendTransaction(transactions, _old, newState) {
      if (!transactions.some((t) => t.docChanged)) return null
      const res = buildFixTransaction(newState)
      if (!res) return null
      if (res.unwrapped && onUnwrap) {
        try {
          onUnwrap(res.unwrapped)
        } catch {
          /* a toast failing must never block an edit */
        }
      }
      return res.tr
    },
  })
}

export function findAudienceById(doc: PMNode, id: string): { pos: number; node: PMNode } | null {
  let found: { pos: number; node: PMNode } | null = null
  doc.descendants((node, pos) => {
    if (found) return false
    if (node.type.name === AUDIENCE_NODE && node.attrs.id === id) {
      found = { pos, node }
      return false
    }
    return true
  })
  return found
}
