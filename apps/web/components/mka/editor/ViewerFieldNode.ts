// MKA fork — `mkaViewerField` inline atom (contract §3.2): the viewer's Majlis / region / department / role / level.
import { Node, nodeInputRule } from '@tiptap/core'
import { ReactNodeViewRenderer } from '@tiptap/react'
import { ViewerField } from './ViewerField'
import { FIELD_FALLBACKS, isField } from './fields'
import type { ViewerFieldKey } from './fields'

export const MkaViewerField = Node.create<{ activity?: any; courseUuid?: string | null; orgId?: number | null }>({
  name: 'mkaViewerField',
  group: 'inline',
  inline: true,
  atom: true,
  selectable: true,

  addOptions() {
    return { activity: undefined, courseUuid: null, orgId: null }
  },

  addAttributes() {
    return {
      field: {
        default: 'majlis',
        parseHTML: (el) => {
          const f = el.getAttribute('data-mka-field')
          return isField(f) ? f : 'majlis'
        },
      },
      fallback: {
        default: FIELD_FALLBACKS.majlis,
        parseHTML: (el) => el.getAttribute('data-fallback') ?? FIELD_FALLBACKS.majlis,
      },
    }
  },

  parseHTML() {
    return [{ tag: 'span[data-mka-field]' }]
  },

  renderHTML({ node }) {
    // Plain-text copy yields the fallback.
    return ['span', { 'data-mka-field': node.attrs.field, 'data-fallback': node.attrs.fallback }, String(node.attrs.fallback ?? '')]
  },

  renderText({ node }) {
    return String(node.attrs.fallback ?? '')
  },

  addNodeView() {
    return ReactNodeViewRenderer(ViewerField as any, { as: 'span', className: 'mka-viewer-field' })
  },

  addInputRules() {
    return [
      nodeInputRule({
        // No capture group: nodeInputRule would otherwise replace only the group, leaving the braces behind.
        find: /\{\{my_(?:majlis|region|department|role_title|role|level)\}\}$/,
        type: this.type,
        getAttributes: (match) => {
          const name = match[0].slice('{{my_'.length, -2)
          const field = (name === 'role' ? 'role_title' : name) as ViewerFieldKey
          return { field, fallback: FIELD_FALLBACKS[field] }
        },
      }),
    ]
  },
})
