// MKA fork — mounts the React chrome (Audience bar) above the document.
//
// ReactRenderer only renders through `editor.contentComponent`, which EditorContent creates in componentDidMount,
// AFTER the editor (and its plugin views) exist. A renderer created earlier (from a plugin view) can therefore be
// lost, silently: that is why the bar never appeared on the learner/admin page. So this is called from every place
// that runs at or after the right moment, and is idempotent per content component:
//  - the plugin view (works when the content component already exists, e.g. the editor route),
//  - every section node view construction (EditorContent.init() calls editor.createNodeViews() once the content
//    component exists, so node views are rebuilt at exactly the right time).
// Nothing correctness-critical depends on this: the learner filter, copy policy and notes are plain TS (driver.ts).
import { ReactRenderer } from '@tiptap/react'
import type { AudienceNodeOptions } from './AudienceNodeView'
import { AudienceChrome } from './AudienceChrome'

type ChromeStorage = { chromeRenderer?: ReactRenderer | null; chromeFor?: unknown; notesHost?: HTMLElement | null }

export function ensureChrome(editor: any, options: AudienceNodeOptions): void {
  try {
    const st = editor?.storage?.mkaAudience as ChromeStorage | undefined
    const contentComponent = editor?.contentComponent
    if (!st || !contentComponent || editor.isDestroyed || !editor.view?.dom?.parentElement) return
    if (st.chromeRenderer && st.chromeFor === contentComponent && st.chromeRenderer.element.parentElement === editor.view.dom.parentElement) return
    // Stale renderer from a previous content component (remount): replace it.
    try {
      st.chromeRenderer?.destroy()
      st.chromeRenderer?.element.remove()
    } catch {
      /* ignore */
    }
    const parent = editor.view.dom.parentElement as HTMLElement
    const renderer = new ReactRenderer(AudienceChrome as any, {
      editor,
      props: { editor, options },
      className: 'mka-audience-chrome',
    })
    const anchor = st.notesHost && st.notesHost.parentElement === parent ? st.notesHost : editor.view.dom
    parent.insertBefore(renderer.element, anchor)
    st.chromeRenderer = renderer
    st.chromeFor = contentComponent
  } catch (err) {
    if (process.env.NODE_ENV !== 'production') console.error('[mka-audience] chrome mount failed', err)
  }
}
