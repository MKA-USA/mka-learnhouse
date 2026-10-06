// MKA fork — plain-TS driver for everything correctness-critical in a viewer.
//
// Learner filter (hidden content out of the editor STATE), clipboard policy, learner notes and preview editability
// used to live in the React chrome. That chrome renders through a portal that can fail to mount (see chromeMount.ts),
// and then none of it ran. This driver depends only on the per-editor store, which the section controllers (they do
// mount: they are node views) feed with the viewer state. No React here.
import type { Editor } from '@tiptap/core'
import { applyLearnerFilter } from './learnerFilter'
import { computeLearnerNotes, DEFAULT_COPY } from './logic'
import { getAudienceStore } from './store'
import type { AudienceStoreState, CopyPolicy } from './store'

const NOTE_CLASS = 'my-2 rounded-md bg-slate-50 px-3 py-2 text-sm text-slate-700 dark:bg-slate-800 dark:text-slate-200'

type DriverOptions = { editable: boolean }

export type NotesView = { unrecognized: boolean; emptyLesson: boolean }

/** What notes (if any) to show for the current store state. Pure given the doc JSON. */
export function notesFor(st: AudienceStoreState, getDoc: () => unknown): NotesView | null {
  const v = st.viewing
  if (!v || v.state !== 'ready' || st.sectionCount <= 0) return null
  const previewing = st.view.kind !== 'author'
  // Authors / can_view_all see "everything" by default: notes only describe what a previewed viewer would see.
  if ((v.providerEditable || v.canViewAll) && !previewing) return null
  const effective = st.view.kind === 'persona' ? st.view.attributes : v.viewer
  const n = computeLearnerNotes(getDoc(), effective) // lazily: only when notes can render (never for author keystrokes)
  return { unrecognized: n.unrecognized, emptyLesson: n.emptyLesson }
}

export function renderNotes(host: HTMLElement, notes: NotesView | null, copy: { unrecognized_note: string; empty_lesson: string }): void {
  const want: [string, string, string][] = []
  if (notes?.unrecognized) want.push(['mka-note-unrecognized', copy.unrecognized_note, 'status'])
  if (notes?.emptyLesson) want.push(['mka-note-empty', copy.empty_lesson, 'note'])
  const have = [...host.children].map((c) => `${c.getAttribute('data-testid')}|${c.textContent}`).join('\n')
  if (have === want.map(([id, t]) => `${id}|${t}`).join('\n')) return
  host.setAttribute('aria-live', 'polite')
  host.replaceChildren(
    ...want.map(([id, text, role]) => {
      const p = document.createElement('p')
      p.setAttribute('role', role)
      p.setAttribute('data-testid', id)
      p.className = NOTE_CLASS
      p.textContent = text
      return p
    }),
  )
}

/** Starts the driver for one editor. Returns a stop function. */
export function startAudienceDriver(editor: Editor, options: DriverOptions, notesHost: HTMLElement): () => void {
  const store = getAudienceStore(editor as any)
  let stopped = false
  let scheduled = false
  let wasPreviewing = false
  let last: { phase: 'none' | 'ready'; viewer: unknown; canViewAll: boolean; originalVersion: number } | null = null

  // Only write when it changed: every store write re-schedules this driver.
  const setPolicy = (next: CopyPolicy) => {
    const cur = store.get().copyPolicy
    if (cur.kind === next.kind && (cur.kind !== 'viewer' || (next.kind === 'viewer' && cur.viewer === next.viewer))) return
    store.set({ copyPolicy: next })
  }

  const run = () => {
    scheduled = false
    if (stopped || editor.isDestroyed) return
    const st = store.get()
    const v = st.viewing

    // Preview makes an authoring editor read-only (transitions only; no `update`, so unsaved-changes tracking is untouched).
    if (v?.providerEditable) {
      const previewing = st.view.kind !== 'author'
      if (previewing !== wasPreviewing) {
        wasPreviewing = previewing
        editor.setEditable(!previewing, false)
      }
    }

    // Learner view: keep hidden content out of the editor STATE (TOC, copy and AI read editor.state.doc), not only out of the DOM.
    // Never for authoring editors. Until a ready viewer is known (loading, /me retrying, or no section controller ever
    // published) EVERY section is emptied: fail closed, then re-filter from the original once the viewer is known.
    // Only when the inputs changed: re-running on every store write would also undo any later change to the document.
    if (!options.editable && !v?.providerEditable && st.sectionCount > 0) {
      const pending = !v || v.state === 'loading'
      const inputsChanged = pending
        ? last?.phase !== 'none' || last.originalVersion !== st.originalVersion
        : !last || last.phase !== 'ready' || last.viewer !== v.viewer || last.canViewAll !== v.canViewAll || last.originalVersion !== st.originalVersion
      if (inputsChanged) {
        if (pending) {
          last = { phase: 'none', viewer: null, canViewAll: false, originalVersion: st.originalVersion }
          applyLearnerFilter(editor as any, 'none')
        } else {
          last = { phase: 'ready', viewer: v.viewer, canViewAll: v.canViewAll, originalVersion: st.originalVersion }
          if (v.canViewAll) {
            applyLearnerFilter(editor as any, 'all')
            setPolicy({ kind: 'all' })
          } else {
            applyLearnerFilter(editor as any, v.viewer)
            setPolicy({ kind: 'viewer', viewer: v.viewer })
          }
        }
      }
    }

    renderNotes(notesHost, notesFor(store.get(), () => editor.state.doc.toJSON()), store.get().copy ?? DEFAULT_COPY)
  }

  // Coalesced and deferred: filtering swaps the editor state, and node view updates flushSync React renders, which
  // React rejects while it is mid-lifecycle (the store is also written from React effects).
  const schedule = () => {
    if (scheduled || stopped) return
    scheduled = true
    queueMicrotask(run)
  }

  const unsubscribe = store.subscribe(schedule)
  schedule()
  return () => {
    stopped = true
    unsubscribe()
    if (wasPreviewing && !editor.isDestroyed) editor.setEditable(true, false)
  }
}
