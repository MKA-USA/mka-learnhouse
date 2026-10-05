'use client'
import React from 'react'
import { NodeViewWrapper } from '@tiptap/react'
import { Mail, Users } from 'lucide-react'
import { useEditorProvider } from '@components/Contexts/Editor/EditorContext'
import { useAudienceScope, useCounterparts, useMkaViewer } from '@services/mka/attributes'
import { MkaErrorBoundary } from './MkaErrorBoundary'
import { useAudienceStore } from './store'

const CARD =
  'my-3 rounded-lg border border-slate-200 bg-white p-4 text-sm shadow-xs dark:border-slate-700 dark:bg-slate-900'

export function Counterparts(props: any) {
  return (
    <NodeViewWrapper className="mka-counterparts" contentEditable={false}>
      <MkaErrorBoundary fallback={null}>
        <Inner {...props} />
      </MkaErrorBoundary>
    </NodeViewWrapper>
  )
}

function Inner({ editor, extension }: any) {
  const provider = useEditorProvider() as { isEditable?: boolean } | null
  const editable = provider?.isEditable === true
  const opts = extension?.options ?? {}
  const scope = useAudienceScope(opts.activity, { courseUuid: opts.courseUuid, orgId: opts.orgId })
  const me = useMkaViewer(scope.courseUuid)
  const st = useAudienceStore(editor)
  const authorView = (editable || me.canViewAll) && st.view.kind === 'author'
  const previewing = (editable || me.canViewAll) && st.view.kind === 'persona'
  // Only real learners (or an author's "As me" view) hit the API.
  const q = useCounterparts(!authorView && !previewing)

  if (authorView) {
    return (
      <div data-testid="mka-counterparts-sample" className={CARD}>
        <div className="flex items-center gap-2 font-medium">
          <Users className="size-4" aria-hidden /> Counterparts (filled per viewer)
        </div>
        <p className="mt-1 text-slate-500 dark:text-slate-400">Each viewer sees the national, regional and local contacts for their role.</p>
      </div>
    )
  }
  if (previewing) {
    return (
      <div data-testid="mka-counterparts-preview" className={CARD}>
        Preview shows sample counterparts
      </div>
    )
  }
  if (me.state === 'loading' || q.isLoading) return null
  const data = q.data
  if (!data) return null
  if (data.reason) {
    return <div className={CARD}>Counterparts appear once your role is recognized.</div>
  }
  if (data.counterparts.length === 0) return null
  return (
    <div data-testid="mka-counterparts-card" className={CARD}>
      <div className="mb-2 flex items-center gap-2 font-medium">
        <Users className="size-4" aria-hidden /> Your counterparts
      </div>
      <ul className="space-y-1.5">
        {data.counterparts.map((c) => (
          <li key={`${c.level}-${c.email}`} className="flex flex-wrap items-center gap-x-2">
            <span className="font-medium">{c.role_title}</span>
            {c.name && <span>{c.name}</span>}
            <a className="inline-flex items-center gap-1 text-blue-700 underline dark:text-blue-300" href={`mailto:${c.email}`}>
              <Mail className="size-3.5" aria-hidden /> {c.email}
            </a>
          </li>
        ))}
      </ul>
    </div>
  )
}

export default Counterparts
