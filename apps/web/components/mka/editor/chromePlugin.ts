// MKA fork — ProseMirror plugin view that mounts the Audience bar and learner notes above the document.
// Rendered through ReactRenderer (portal into the editor's EditorContent) so app contexts are available,
// and with no upstream layout hook (B1.4).
import { Plugin, PluginKey } from '@tiptap/pm/state'
import { ReactRenderer } from '@tiptap/react'
import type { AudienceNodeOptions } from './AudienceNodeView'
import { AudienceChrome } from './AudienceChrome'
import { getAudienceStore } from './store'
import { AUDIENCE_NODE } from './plugins'
import { transformCopiedSlice } from './learnerFilter'

export const chromePluginKey = new PluginKey('mkaAudienceChrome')

export function createChromePlugin(editor: any, options: AudienceNodeOptions): Plugin {
  return new Plugin({
    key: chromePluginKey,
    props: {
      // Belt and braces behind the learner filter: copy/cut never serializes a section this viewer may not see.
      transformCopied: (slice) => transformCopiedSlice(slice, getAudienceStore(editor).get().copyPolicy),
    },
    view(view) {
      const store = getAudienceStore(editor)
      let renderer: ReactRenderer | null = null

      const countSections = () => {
        let n = 0
        view.state.doc.descendants((node) => {
          if (node.type.name === AUDIENCE_NODE) n += 1
          return true
        })
        return n
      }
      const publish = () => store.set({ sectionCount: countSections(), docVersion: store.get().docVersion + 1 })
      publish()

      // Viewer editors keep the ORIGINAL document so the learner filter can always re-run from it; any document
      // change that is not our own filtering (e.g. upstream setContent) becomes the new original.
      const captureOriginal = () => {
        const st = editor.storage?.mkaAudience
        if (!st || options.editable) return
        st.original = view.state.doc.toJSON()
        store.set({ originalVersion: store.get().originalVersion + 1 })
      }
      captureOriginal()

      try {
        const parent = view.dom.parentElement
        if (parent) {
          renderer = new ReactRenderer(AudienceChrome as any, {
            editor,
            props: { editor, options },
            className: 'mka-audience-chrome',
          })
          parent.insertBefore(renderer.element, view.dom)
        }
      } catch (err) {
        renderer = null
        if (process.env.NODE_ENV !== 'production') console.error('[mka-audience] chrome mount failed', err)
      }

      return {
        update(v, prev) {
          if (v.state.doc !== prev.doc) {
            if (!editor.storage?.mkaAudience?.stripping) captureOriginal()
            publish()
          }
        },
        destroy() {
          try {
            renderer?.destroy()
            renderer?.element.remove()
          } catch {
            /* ignore */
          }
          renderer = null
        },
      }
    },
  })
}
