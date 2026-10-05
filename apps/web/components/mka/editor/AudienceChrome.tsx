'use client'
/**
 * Document-level chrome for audience sections, mounted above the document by chromePlugin:
 *  - the Audience bar (viewing mode / preview-as) for authors and `can_view_all` viewers;
 *  - the learner notes ("tailored by role", "nothing applies to you"), once per activity.
 */
import React, { useCallback, useEffect, useMemo, useRef } from 'react'
import type { Editor } from '@tiptap/react'
import { useEditorProvider } from '@components/Contexts/Editor/EditorContext'
import { useLHSession } from '@components/Contexts/LHSessionContext'
import {
  fetchPreviewPerson,
  searchPreviewPeople,
  useAttributesAuth,
  useAudienceOptions,
  useAudienceScope,
  useMkaViewer,
} from '@services/mka/attributes'
import { mkaAudienceEnabled, mkaAudienceMock } from '@services/mka/flags'
import type { AudienceView } from '../audience/types'
import { AudienceBar } from './AudienceBar'
import type { PreviewPerson } from './PreviewMenu'
import { MkaErrorBoundary } from './MkaErrorBoundary'
import { getAudienceStore, useAudienceStore } from './store'
import { computeLearnerNotes, DEFAULT_COPY } from './logic'
import type { AudienceNodeOptions } from './AudienceNodeView'

const NOTE_CLASS = 'my-2 rounded-md bg-slate-50 px-3 py-2 text-sm text-slate-700 dark:bg-slate-800 dark:text-slate-200'

type Props = { editor: Editor; options: AudienceNodeOptions }

export function AudienceChrome(props: Props) {
  return (
    <MkaErrorBoundary fallback={null}>
      <Inner {...props} />
    </MkaErrorBoundary>
  )
}

function Inner({ editor, options }: Props) {
  const provider = useEditorProvider() as { isEditable?: boolean } | null
  const editable = provider?.isEditable === true
  const scope = useAudienceScope(options.activity, { courseUuid: options.courseUuid, orgId: options.orgId })
  const me = useMkaViewer(scope.courseUuid)
  const st = useAudienceStore(editor)
  const orgOptions = useAudienceOptions(scope.orgId).data
  const auth = useAttributesAuth()
  // UI hint only (the API enforces org admin/maintainer on the preview-people routes). Null-safe: the fork
  // must not throw where no session provider exists.
  const session = useLHSession() as any
  const canPickPerson =
    (mkaAudienceMock() && me.canViewAll) ||
    session?.data?.user?.is_superadmin === true ||
    ((session?.data?.roles ?? []) as any[]).some(
      (r) => r?.org?.id === scope.orgId && r?.role?.rights?.dashboard?.action_access === true,
    )
  const people = useRef(new Map<number, string>())

  const previewing = st.view.kind !== 'author'

  // Under a preview the document is read-only: the author is looking at what a viewer sees, with
  // hidden content detached from the page. Only transitions touch editability (never on mount), and
  // without emitting an update so the upstream unsaved-changes tracking is not triggered.
  const wasPreviewing = useRef(false)
  useEffect(() => {
    if (!editable || wasPreviewing.current === previewing) return
    wasPreviewing.current = previewing
    if (!editor.isDestroyed) editor.setEditable(!previewing, false)
  }, [editable, previewing, editor])
  useEffect(
    () => () => {
      if (wasPreviewing.current && !editor.isDestroyed) editor.setEditable(true, false)
    },
    [editor],
  )

  const showBar = mkaAudienceEnabled() && st.sectionCount > 0 && (editable || me.canViewAll)

  const onChangeView = useCallback((view: AudienceView) => getAudienceStore(editor).set({ view }), [editor])
  const searchPeople = useCallback(
    async (q: string): Promise<PreviewPerson[]> => {
      if (!scope.orgId) return []
      const res = await searchPreviewPeople(auth.token, scope.orgId, q)
      res.people.forEach((p) => people.current.set(p.user_id, p.display_name))
      return res.people
    },
    [auth.token, scope.orgId],
  )
  const pickPerson = useCallback(
    async (rawId: number | string) => {
      if (!scope.orgId) return
      const id = Number(rawId)
      try {
        const res = await fetchPreviewPerson(auth.token, scope.orgId, id)
        getAudienceStore(editor).set({
          view: { kind: 'persona', label: people.current.get(id) ?? 'Selected person', attributes: res.attributes },
        })
      } catch {
        /* the bar keeps its current view; the audit-writing call failed closed */
      }
    },
    [auth.token, scope.orgId, editor],
  )

  // Learner notes: only for what a viewer effectively sees (not the author's "everything" view).
  const effectiveViewer = st.view.kind === 'persona' ? st.view.attributes : me.viewer
  const showNotes = st.sectionCount > 0 && me.state === 'ready' && (editable || me.canViewAll ? previewing : true)
  const notes = useMemo(
    () => (showNotes ? computeLearnerNotes(editor.state.doc.toJSON(), effectiveViewer) : null),
    // docVersion: recompute when the document changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [showNotes, effectiveViewer, st.docVersion, editor],
  )
  const copy = orgOptions?.copy ?? DEFAULT_COPY

  return (
    <>
      {showBar && (
        <AudienceBar
          sectionCount={st.sectionCount}
          view={st.view}
          onChangeView={onChangeView}
          personas={orgOptions?.personas ?? []}
          canPickPerson={canPickPerson}
          searchPeople={searchPeople}
          pickPerson={pickPerson}
          options={orgOptions}
        />
      )}
      {notes?.unrecognized && (
        <p role="note" data-testid="mka-note-unrecognized" className={NOTE_CLASS}>
          {copy.unrecognized_note}
        </p>
      )}
      {notes?.emptyLesson && (
        <p role="note" data-testid="mka-note-empty" className={NOTE_CLASS}>
          {copy.empty_lesson}
        </p>
      )}
    </>
  )
}

export default AudienceChrome
