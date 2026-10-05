// MKA fork — `mkaAudience` block node (contract §3.2).
import { Node } from '@tiptap/core'
import { TextSelection } from '@tiptap/pm/state'
import type { Transaction } from '@tiptap/pm/state'
import { Slice } from '@tiptap/pm/model'
import type { Node as PMNode } from '@tiptap/pm/model'
import { ReplaceAroundStep } from '@tiptap/pm/transform'
import toast from 'react-hot-toast'
import { DEFAULT_RULE } from '../audience/types'
import type { Rule } from '../audience/types'
import { AudienceNodeView } from './AudienceNodeView'
import type { AudienceNodeOptions } from './AudienceNodeView'
import { AudienceView } from './AudienceView'
import { AUDIENCE_NODE, buildFixTransaction, createIdsPlugin, findAudienceById, newAudienceId } from './plugins'
import { createAudienceStore, getAudienceStore } from './store'
import { createChromePlugin } from './chromePlugin'
import { mkaAudienceEnabled } from '@services/mka/flags'

declare module '@tiptap/core' {
  interface Commands<ReturnType> {
    mkaAudience: {
      /** Wrap the selected blocks (or insert an empty section with the cursor inside) and open its picker. */
      setMkaAudience: () => ReturnType
      /** `addToHistory: false` for live picker previews and reverts (only Done records a history step). */
      updateMkaAudienceRule: (id: string, rule: Rule, opts?: { addToHistory?: boolean }) => ReturnType
      /** Done on an EXISTING section: restore `opening` silently, then record the final rule as ONE step. */
      commitEditMkaAudience: (id: string, opening: Rule) => ReturnType
      /** Unwrap a section, keeping its content. */
      unsetMkaAudience: (id: string) => ReturnType
      /** Cancel of a NEW section: an empty inserted one is removed entirely, a wrapped one is unwrapped. */
      cancelNewMkaAudience: (id: string) => ReturnType
    }
  }
}

/** An unparsable `data-rule` is kept as an invalid object so it fails safe (hidden for learners, flagged for authors). */
function parseRuleAttr(el: HTMLElement): unknown {
  const raw = el.getAttribute('data-rule')
  if (raw == null) return DEFAULT_RULE
  try {
    return JSON.parse(raw)
  } catch {
    return { invalid: true }
  }
}

export const MkaAudience = Node.create<AudienceNodeOptions>({
  name: AUDIENCE_NODE,
  group: 'block',
  content: 'block+',
  defining: true,
  isolating: true,

  addOptions() {
    return { editable: false, activity: undefined, courseUuid: null, orgId: null }
  },

  addStorage() {
    return { store: createAudienceStore({ editableDoc: this.options.editable }), original: null as unknown, stripping: false, explicitLoad: false, chromeRenderer: null as unknown, chromeFor: null as unknown, notesHost: null as unknown, driverStop: null as unknown }
  },

  addAttributes() {
    return {
      id: {
        default: null,
        parseHTML: (el) => el.getAttribute('data-id'),
        renderHTML: () => ({}),
      },
      rule: {
        default: DEFAULT_RULE as unknown,
        parseHTML: (el) => parseRuleAttr(el),
        renderHTML: () => ({}),
      },
    }
  },

  parseHTML() {
    return [{ tag: 'div[data-mka-audience]' }]
  },

  renderHTML({ node }) {
    return [
      'div',
      {
        'data-mka-audience': '',
        'data-id': node.attrs.id ?? '',
        'data-rule': JSON.stringify(node.attrs.rule),
      },
      0,
    ]
  },

  addNodeView() {
    const options = this.options
    return ({ node, editor, getPos }) =>
      new AudienceNodeView({ node, editor, getPos: getPos as () => number | undefined, options, component: AudienceView })
  },

  addCommands() {
    return {
      setMkaAudience:
        () =>
        ({ state, tr, dispatch, editor }) => {
          const type = state.schema.nodes[AUDIENCE_NODE]
          const { $from, $to, empty } = state.selection
          // No nesting: refuse inside a section or when the selection already contains one.
          for (let d = 0; d <= $from.depth; d++) if ($from.node(d).type === type) return false
          let hasInner = false
          state.doc.nodesBetween($from.pos, $to.pos, (n) => {
            if (n.type === type) hasInner = true
            return !hasInner
          })
          if (hasInner) return false

          const id = newAudienceId()
          const attrs = { id, rule: DEFAULT_RULE }
          const blankParagraph = $from.parent.type.name === 'paragraph' && $from.parent.content.size === 0
          // Work at the top level so a section never lands inside a list item or table cell by accident.
          let from: number
          let to: number
          if ($from.depth >= 1) {
            from = $from.before(1)
            to = $to.after(1)
          } else {
            from = state.selection.from
            to = state.selection.to
          }
          if (!dispatch) return true

          if (empty && !blankParagraph) {
            const para = state.schema.nodes.paragraph.create()
            const node = type.create(attrs, para)
            const at = $from.depth >= 1 ? $from.after(1) : $from.pos
            tr.insert(at, node)
            tr.setSelection(selectionInside(tr, at))
          } else {
            const $f = tr.doc.resolve(from)
            const $t = tr.doc.resolve(to)
            const range = $f.blockRange($t)
            if (!range) return false
            tr.wrap(range, [{ type, attrs }])
            tr.setSelection(selectionInside(tr, range.start))
          }
          dispatch(tr.scrollIntoView())
          const store = getAudienceStore(editor)
          store.set({ openPickerFor: id, inserted: empty && !blankParagraph ? { ...store.get().inserted, [id]: true } : store.get().inserted })
          return true
        },

      updateMkaAudienceRule:
        (id, rule, opts) =>
        ({ tr, state, dispatch }) => {
          const hit = findAudienceById(state.doc, id)
          if (!hit) return false
          if (opts?.addToHistory === false) tr.setMeta('addToHistory', false)
          if (dispatch) dispatch(tr.setNodeMarkup(hit.pos, undefined, { ...hit.node.attrs, rule }))
          return true
        },

      commitEditMkaAudience:
        (id, opening) =>
        ({ state, tr: shared, editor }) => {
          const hit = findAudienceById(state.doc, id)
          if (!hit) return false
          shared.setMeta('preventDispatch', true) // we dispatch our own transactions below
          const current = hit.node.attrs.rule
          if (JSON.stringify(current) === JSON.stringify(opening)) return true
          editor.view.dispatch(state.tr.setNodeMarkup(hit.pos, undefined, { ...hit.node.attrs, rule: opening }).setMeta('addToHistory', false))
          editor.view.dispatch(editor.state.tr.setNodeMarkup(hit.pos, undefined, { ...hit.node.attrs, rule: current }))
          return true
        },

      cancelNewMkaAudience:
        (id) =>
        ({ tr, state, dispatch, editor }) => {
          const hit = findAudienceById(state.doc, id)
          const store = getAudienceStore(editor)
          const { [id]: wasInserted, ...rest } = store.get().inserted
          store.set({ inserted: rest })
          if (!hit) return false
          const only = hit.node.childCount === 1 ? hit.node.child(0) : null
          const emptyInserted = !!wasInserted && !!only && only.type.name === 'paragraph' && only.content.size === 0
          if (dispatch) {
            // Not an undo step: the cancel must not leave a Ctrl+Z that resurrects the cancelled section.
            tr.setMeta('addToHistory', false)
            if (emptyInserted) tr.delete(hit.pos, hit.pos + hit.node.nodeSize)
            else unwrapSection(tr, hit.pos, hit.node)
            dispatch(tr)
          }
          return true
        },

      unsetMkaAudience:
        (id) =>
        ({ tr, state, dispatch }) => {
          const hit = findAudienceById(state.doc, id)
          if (!hit) return false
          if (dispatch) {
            unwrapSection(tr, hit.pos, hit.node)
            dispatch(tr)
          }
          return true
        },
    }
  },

  addKeyboardShortcuts() {
    return {
      'Mod-Alt-a': () => {
        if (!this.options.editable || !mkaAudienceEnabled()) return false
        return this.editor.commands.setMkaAudience()
      },
    }
  },

  addProseMirrorPlugins() {
    const plugins = []
    try {
      plugins.push(
        createIdsPlugin(() => toast("Audience sections can't be nested. The inner section was unwrapped.")),
      )
    } catch (err) {
      if (process.env.NODE_ENV !== 'production') console.error('[mka-audience] ids plugin failed', err)
    }
    try {
      plugins.push(createChromePlugin(this.editor, this.options))
    } catch (err) {
      if (process.env.NODE_ENV !== 'production') console.error('[mka-audience] chrome plugin failed', err)
    }
    return plugins
  },

  onCreate() {
    // Repair ids on content written before this feature existed or pasted from elsewhere (authoring only).
    if (!this.options.editable) return
    try {
      const res = buildFixTransaction(this.editor.state)
      if (res) this.editor.view.dispatch(res.tr.setMeta('addToHistory', false))
    } catch {
      /* never block editor creation */
    }
  },
})

/**
 * Unwrap a section with a ReplaceAroundStep that keeps the inner content in place (the same step `tr.lift` makes).
 * Replacing the node with its content would map as a deletion and destroy the undo history of earlier edits inside the
 * wrapped blocks. `liftTarget` is not used: it refuses to lift out of an `isolating` node such as this one.
 */
function unwrapSection(tr: Transaction, pos: number, node: PMNode) {
  const end = pos + node.nodeSize
  try {
    tr.step(new ReplaceAroundStep(pos, end, pos + 1, end - 1, Slice.empty, 0, true))
  } catch {
    tr.replaceWith(pos, end, node.content)
  }
}

/** Cursor at the start of the first textblock inside the section starting at `pos`. */
function selectionInside(tr: Transaction, pos: number) {
  return TextSelection.near(tr.doc.resolve(pos + 1))
}
