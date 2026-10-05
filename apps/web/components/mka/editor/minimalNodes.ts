// MKA fork — schema-only fallback nodes. Same names, content and attrs as the real ones, but no node views and no
// plugins, so a failure in the fork's UI code can never make TipTap drop the document ("unknown node => blank").
// Hidden content is NOT enforced here: schema-only nodes render content as plain blocks. This is a last resort
// that trades visibility enforcement for not losing the lesson, and is only reachable if node construction throws.
import { Node } from '@tiptap/core'
import type { AnyExtension } from '@tiptap/core'
import { DEFAULT_RULE } from '../audience/types'

export function minimalMkaNodes(): AnyExtension[] {
  return [
    Node.create({
      name: 'mkaAudience',
      group: 'block',
      content: 'block+',
      defining: true,
      isolating: true,
      addAttributes: () => ({ id: { default: null }, rule: { default: DEFAULT_RULE as unknown } }),
      parseHTML: () => [{ tag: 'div[data-mka-audience]' }],
      renderHTML: ({ node }) => ['div', { 'data-mka-audience': '', 'data-id': node.attrs.id ?? '', 'data-rule': JSON.stringify(node.attrs.rule) }, 0],
    }),
    Node.create({
      name: 'mkaViewerField',
      group: 'inline',
      inline: true,
      atom: true,
      addAttributes: () => ({ field: { default: 'majlis' }, fallback: { default: 'your Majlis' } }),
      parseHTML: () => [{ tag: 'span[data-mka-field]' }],
      renderHTML: ({ node }) => ['span', { 'data-mka-field': node.attrs.field }, String(node.attrs.fallback ?? '')],
    }),
    Node.create({
      name: 'mkaCounterparts',
      group: 'block',
      atom: true,
      addAttributes: () => ({ id: { default: null } }),
      parseHTML: () => [{ tag: 'div[data-mka-counterparts]' }],
      renderHTML: ({ node }) => ['div', { 'data-mka-counterparts': '', 'data-id': node.attrs.id ?? '' }],
    }),
  ]
}
