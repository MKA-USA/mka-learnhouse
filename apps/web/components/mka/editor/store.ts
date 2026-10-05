// MKA fork — tiny per-editor external store for Audience viewing mode (contract §3.3).
// Held in `editor.storage.mkaAudience.store`; React reads it via useSyncExternalStore.
import { useSyncExternalStore } from 'react'
import type { AudienceView, MkaViewerAttributes } from '../audience/types'

/**
 * What copy/cut may serialize out of the document (belt and braces behind the learner filter):
 *  - all:    everything (authoring, and viewers with can_view_all)
 *  - none:   no audience section at all (viewer not resolved yet)
 *  - viewer: only sections this viewer matches
 */
export type CopyPolicy = { kind: 'all' } | { kind: 'none' } | { kind: 'viewer'; viewer: MkaViewerAttributes | null }

/** Viewer state published by the section controllers (React, but mounted reliably) for the plain-TS driver. */
export type ViewingState = {
  state: 'loading' | 'ready' | 'error'
  viewer: MkaViewerAttributes | null
  canViewAll: boolean
  /** EditorContext `isEditable`: true only for the authoring editor. */
  providerEditable: boolean
}

export type AudienceStoreState = {
  /** Null until a section controller has mounted. */
  viewing: ViewingState | null
  /** Copy for learner notes, published by the chrome when /options has loaded (constants are used until then). */
  copy: { unrecognized_note: string; empty_lesson: string } | null
  view: AudienceView
  /** Editor-local view setting, never saved to content. */
  collapsed: Record<string, true>
  /** Id of a freshly inserted section whose picker should open immediately. */
  openPickerFor: string | null
  /** Number of audience sections in the document (maintained by the chrome plugin). */
  sectionCount: number
  /** Bumped on every document change so subscribers can recompute doc-derived data. */
  docVersion: number
  /** Bumped whenever the original (unfiltered) document is (re)captured, so the learner filter re-runs. */
  originalVersion: number
  /** Sections inserted empty by the slash menu / shortcut and not wrapped around existing content. */
  inserted: Record<string, true>
  copyPolicy: CopyPolicy
}

export type AudienceStore = {
  get(): AudienceStoreState
  set(partial: Partial<AudienceStoreState>): void
  subscribe(fn: () => void): () => void
}

export function createAudienceStore(opts: { editableDoc?: boolean } = {}): AudienceStore {
  let state: AudienceStoreState = {
    viewing: null,
    copy: null,
    view: { kind: 'author' },
    collapsed: {},
    openPickerFor: null,
    sectionCount: 0,
    docVersion: 0,
    originalVersion: 0,
    inserted: {},
    // Viewer editors serialize no section until the viewer is known (fail closed).
    copyPolicy: opts.editableDoc ? { kind: 'all' } : { kind: 'none' },
  }
  const listeners = new Set<() => void>()
  return {
    get: () => state,
    set(partial) {
      const next = { ...state, ...partial }
      const changed = (Object.keys(partial) as (keyof AudienceStoreState)[]).some((k) => next[k] !== state[k])
      if (!changed) return
      state = next
      listeners.forEach((fn) => fn())
    },
    subscribe(fn) {
      listeners.add(fn)
      return () => listeners.delete(fn)
    },
  }
}

// Fallback for editors that lack the extension storage (never expected, but never throw).
const orphans = new WeakMap<object, AudienceStore>()

export function getAudienceStore(editor: { storage?: Record<string, any> } | null | undefined): AudienceStore {
  const existing = editor?.storage?.mkaAudience?.store as AudienceStore | undefined
  if (existing) return existing
  const key = (editor ?? orphans) as object
  let s = orphans.get(key)
  if (!s) {
    s = createAudienceStore()
    orphans.set(key, s)
  }
  return s
}

export function useAudienceStore(editor: { storage?: Record<string, any> } | null | undefined): AudienceStoreState {
  const store = getAudienceStore(editor)
  return useSyncExternalStore(store.subscribe, store.get, store.get)
}

/** Publishes viewer state; a no-op when nothing changed (every section controller publishes the same value). */
export function publishViewing(store: AudienceStore, next: ViewingState): void {
  const cur = store.get().viewing
  if (cur && cur.state === next.state && cur.viewer === next.viewer && cur.canViewAll === next.canViewAll && cur.providerEditable === next.providerEditable) return
  store.set({ viewing: next })
}
