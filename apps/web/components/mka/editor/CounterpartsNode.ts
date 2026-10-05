// MKA fork — `mkaCounterparts` block atom (contract §3.2): "your counterparts" card, filled per viewer.
import { Node } from '@tiptap/core'
import { ReactNodeViewRenderer } from '@tiptap/react'
import { Counterparts } from './Counterparts'

export const MkaCounterparts = Node.create<{ activity?: any; courseUuid?: string | null; orgId?: number | null }>({
  name: 'mkaCounterparts',
  group: 'block',
  atom: true,
  selectable: true,
  draggable: true,

  addOptions() {
    return { activity: undefined, courseUuid: null, orgId: null }
  },

  addAttributes() {
    return {
      id: {
        default: null,
        parseHTML: (el) => el.getAttribute('data-id'),
      },
    }
  },

  parseHTML() {
    return [{ tag: 'div[data-mka-counterparts]' }]
  },

  renderHTML({ node }) {
    return ['div', { 'data-mka-counterparts': '', 'data-id': node.attrs.id ?? '' }]
  },

  addNodeView() {
    return ReactNodeViewRenderer(Counterparts as any)
  },
})
