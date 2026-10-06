// MKA fork — ProseMirror plugin view that mounts the Audience bar and learner notes above the document.
// Rendered through ReactRenderer (portal into the editor's EditorContent) so app contexts are available,
// and with no upstream layout hook (B1.4).
import { Plugin, PluginKey } from '@tiptap/pm/state'
import type { AudienceNodeOptions } from './AudienceNodeView'
import { ensureChrome } from './chromeMount'
import { startAudienceDriver } from './driver'
import { getAudienceStore } from './store'
import { AUDIENCE_NODE } from './plugins'
import { transformCopiedSlice } from './learnerFilter'

export const chromePluginKey = new PluginKey('mkaAudienceChrome')

export function createChromePlugin(editor: any, options: AudienceNodeOptions): Plugin {
  return new Plugin({
    key: chromePluginKey,
    // The ORIGINAL document may only be (re)captured from an explicit content load: the initial document, or
    // `setContent` (it always sets the `preventUpdate` meta). Any other doc change made after the learner filter ran
    // must not become the "original", or a later can_view_all viewer would see emptied sections.
    state: {
      init: () => null,
      apply(tr) {
        if (tr.docChanged && tr.getMeta('preventUpdate') !== undefined) {
          const storage = editor.storage?.mkaAudience
          if (storage) storage.explicitLoad = true
        }
        return null
      },
    },
    props: {
      // Belt and braces behind the learner filter: copy/cut never serializes a section this viewer may not see.
      transformCopied: (slice) => transformCopiedSlice(slice, getAudienceStore(editor).get().copyPolicy),
    },
    view(view) {
      const store = getAudienceStore(editor)
      const st = () =>
        editor.storage?.mkaAudience as
          | { stripping?: boolean; explicitLoad?: boolean; original?: unknown; chromeRenderer?: any; notesHost?: HTMLElement | null; driverStop?: (() => void) | null }
          | undefined
      // The learner filter swaps in a fresh EditorState (see learnerFilter.ts), which makes ProseMirror destroy and
      // re-create plugin views. That swap must neither re-capture the filtered doc as the original nor re-mount the chrome.
      const swapping = !!st()?.stripping

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
        const storage = st()
        if (!storage || options.editable) return
        storage.original = view.state.doc.toJSON()
        store.set({ originalVersion: store.get().originalVersion + 1 })
      }
      // Only the very first plugin view captures. Later re-creations (state swap, registerPlugin/unregisterPlugin) would see
      // the FILTERED document; explicit loads (setContent) recapture via `explicitLoad` below.
      if (!swapping && !st()?.original) captureOriginal()

      // Plain-DOM notes host (no React) + the driver. Created once per editor; the state swap re-creates plugin views and
      // they inherit both.
      const storage0 = st()
      if (storage0 && !storage0.notesHost) {
        const host = document.createElement('div')
        host.className = 'mka-audience-notes'
        host.setAttribute('data-mka-notes', '')
        host.contentEditable = 'false'
        view.dom.parentElement?.insertBefore(host, view.dom)
        storage0.notesHost = host
      }
      if (storage0 && storage0.notesHost && !storage0.driverStop) {
        storage0.driverStop = startAudienceDriver(editor, options, storage0.notesHost)
      }
      // React chrome (the bar): best effort here; section node views call ensureChrome again at the right time.
      ensureChrome(editor, options)

      return {
        update(v, prev) {
          if (v.state.doc !== prev.doc) {
            const storage = st()
            if (storage && !storage.stripping && storage.explicitLoad) captureOriginal()
            if (storage) storage.explicitLoad = false
            publish()
          }
        },
        destroy() {
          if (st()?.stripping) return // state swap: the next plugin view inherits the chrome, notes host and driver
          const storage = st()
          try {
            storage?.driverStop?.()
            storage?.chromeRenderer?.destroy()
            storage?.chromeRenderer?.element.remove()
            storage?.notesHost?.remove()
          } catch {
            /* ignore */
          }
          if (storage) {
            storage.chromeRenderer = null
            storage.driverStop = null
            storage.notesHost = null
          }
        },
      }
    },
  })
}
