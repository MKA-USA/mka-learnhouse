// MKA fork — ProseMirror plugin view that mounts the Audience bar and learner notes above the document.
// Rendered through ReactRenderer (portal into the editor's EditorContent) so app contexts are available,
// and with no upstream layout hook (B1.4).
import { Plugin, PluginKey } from '@tiptap/pm/state'
import { ReactRenderer } from '@tiptap/react'
import type { AudienceNodeOptions } from './AudienceNodeView'
import { AudienceChrome } from './AudienceChrome'
import { getAudienceStore } from './store'
import { AUDIENCE_NODE } from './plugins'

export const chromePluginKey = new PluginKey('mkaAudienceChrome')

export function createChromePlugin(editor: any, options: AudienceNodeOptions): Plugin {
  return new Plugin({
    key: chromePluginKey,
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
          if (v.state.doc !== prev.doc) publish()
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
