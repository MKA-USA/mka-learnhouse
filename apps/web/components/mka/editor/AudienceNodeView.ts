// MKA fork — DOM node view for audience sections.
//
// Why a hand-written node view instead of ReactNodeViewRenderer: TipTap's React node view appends the
// content element into its wrapper at construction, and merely *not rendering* <NodeViewContent/> leaves
// it there. Hidden audience content must not be in the document DOM at all (not display:none), so this view
// owns the content element and attaches it to / detaches it from the page according to the section mode.
// React (hooks, context, chrome) is rendered through TipTap's ReactRenderer portal, which keeps the app's
// providers (React Query, session, org, editor options) available.
import { ReactRenderer } from '@tiptap/react'
import type { Node as PMNode } from '@tiptap/pm/model'
import type { NodeView, ViewMutationRecord } from '@tiptap/pm/view'
import type { SectionMode } from './logic'

export type AudienceNodeOptions = {
  editable: boolean
  activity?: any
  courseUuid?: string | null
  orgId?: number | null
}

export interface AudienceNodeViewApi {
  setMode(mode: SectionMode, extra?: { collapsed?: boolean; label?: string }): void
}

type Args = {
  node: PMNode
  editor: any
  getPos: () => number | undefined
  options: AudienceNodeOptions
  /** React component rendering the controller + chrome. Injected to keep this file free of React imports/cycles. */
  component: any
}

const registry = new WeakMap<HTMLElement, AudienceNodeView>()

/** Node view instance behind a section's DOM element (used by tests to drive modes without React). */
export const audienceNodeViewFor = (dom: Element | null): AudienceNodeView | undefined =>
  dom ? registry.get(dom as HTMLElement) : undefined

/** Modes that put the section's content on the page. */
const SHOWS_CONTENT: ReadonlySet<SectionMode> = new Set(['content', 'chrome'])

export class AudienceNodeView implements NodeView, AudienceNodeViewApi {
  dom: HTMLElement
  contentDOM: HTMLElement
  private chromeHost: HTMLElement
  private slot: HTMLElement
  private renderer: ReactRenderer | null = null
  private node: PMNode
  mode: SectionMode | null = null

  constructor({ node, editor, getPos, options, component }: Args) {
    this.node = node
    this.dom = document.createElement('div')
    this.dom.setAttribute('data-mka-audience-section', '')
    this.chromeHost = document.createElement('div')
    this.chromeHost.setAttribute('data-mka-chrome', '')
    this.chromeHost.contentEditable = 'false'
    this.slot = document.createElement('div')
    this.slot.setAttribute('data-mka-slot', '')
    this.contentDOM = document.createElement('div')
    this.contentDOM.setAttribute('data-mka-content', '')
    this.dom.append(this.chromeHost, this.slot)
    registry.set(this.dom, this)

    // Authoring editors start with the content visible so a failure to mount React can never hide an
    // author's own work; every other editor starts hidden until the controller has evaluated the rule.
    this.setMode(options.editable ? 'chrome' : 'hidden')

    try {
      this.renderer = new ReactRenderer(component, {
        editor,
        props: { nodeView: this, node, editor, getPos, options },
      })
      this.chromeHost.appendChild(this.renderer.element)
    } catch (err) {
      this.renderer = null
      if (process.env.NODE_ENV !== 'production') console.error('[mka-audience] node view failed', err)
    }
  }

  setMode(mode: SectionMode, extra?: { collapsed?: boolean; label?: string }) {
    const collapsed = !!extra?.collapsed
    const show = SHOWS_CONTENT.has(mode) && !collapsed
    if (show) {
      if (this.contentDOM.parentNode !== this.slot) this.slot.appendChild(this.contentDOM)
    } else if (this.contentDOM.parentNode) {
      this.contentDOM.remove()
    }
    this.mode = mode
    const invisible = mode === 'hidden' || mode === 'loading'
    this.dom.style.display = invisible ? 'none' : ''
    this.dom.setAttribute('data-mode', mode)
    this.slot.className = mode === 'chrome' ? 'border-s-4 border-slate-300 ps-3 dark:border-slate-600' : ''
    if (mode === 'chrome' || mode === 'placeholder') {
      this.dom.setAttribute('role', 'region')
      if (extra?.label) this.dom.setAttribute('aria-label', `Section visible to ${extra.label}`)
    } else {
      this.dom.removeAttribute('role')
      this.dom.removeAttribute('aria-label')
    }
  }

  update(node: PMNode) {
    if (node.type !== this.node.type) return false
    this.node = node
    this.renderer?.updateProps({ node })
    return true
  }

  stopEvent(event: Event) {
    // Header buttons / pickers are not editor input.
    return !!event.target && this.chromeHost.contains(event.target as Node)
  }

  ignoreMutation(mutation: ViewMutationRecord) {
    if (mutation.type === 'selection') return false
    // Only changes inside the content element are document edits; React chrome and our own
    // attach/detach/class changes are not.
    return !this.contentDOM.contains(mutation.target)
  }

  destroy() {
    try {
      this.renderer?.destroy()
      this.chromeHost.remove()
    } catch {
      /* ignore */
    }
    this.renderer = null
  }
}
