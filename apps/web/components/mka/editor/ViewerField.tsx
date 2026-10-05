'use client'
import React from 'react'
import { NodeViewWrapper } from '@tiptap/react'
import { useEditorProvider } from '@components/Contexts/Editor/EditorContext'
import { useAudienceOptions, useAudienceScope, useMkaViewer } from '@services/mka/attributes'
import type { AudienceOptions, MkaViewerAttributes } from '../audience/types'
import { MkaErrorBoundary } from './MkaErrorBoundary'
import { useAudienceStore } from './store'
import { FIELD_LABELS } from './fields'
import type { ViewerFieldKey } from './fields'

/** Display value of one attribute; department keys render by name via the org options. */
export function fieldValue(field: ViewerFieldKey, attrs: MkaViewerAttributes | null, options?: AudienceOptions): string | null {
  const raw = attrs ? attrs[field] : null
  if (raw == null || raw === '') return null
  if (field === 'department') return options?.departments.find((d) => d.key === raw)?.name ?? String(raw)
  if (field === 'level') return options?.levels.find((l) => l.key === raw)?.label ?? String(raw)
  return String(raw)
}

export function ViewerField(props: any) {
  return (
    <NodeViewWrapper as="span" className="mka-viewer-field">
      <MkaErrorBoundary fallback={<span>{String(props.node?.attrs?.fallback ?? '')}</span>}>
        <Inner {...props} />
      </MkaErrorBoundary>
    </NodeViewWrapper>
  )
}

function Inner({ node, editor, extension }: any) {
  const provider = useEditorProvider() as { isEditable?: boolean } | null
  const editable = provider?.isEditable === true
  const opts = extension?.options ?? {}
  const scope = useAudienceScope(opts.activity, { courseUuid: opts.courseUuid, orgId: opts.orgId })
  const me = useMkaViewer(scope.courseUuid)
  const st = useAudienceStore(editor)
  const orgOptions = useAudienceOptions(scope.orgId).data
  const field = node.attrs.field as ViewerFieldKey
  const fallback = String(node.attrs.fallback ?? '')

  const authorView = (editable || me.canViewAll) && st.view.kind === 'author'
  if (authorView) {
    return (
      <span
        data-testid="mka-field-chip"
        className="rounded bg-slate-100 px-1.5 py-0.5 text-[0.9em] text-slate-700 dark:bg-slate-800 dark:text-slate-200"
        title={`Filled per viewer. Shows "${fallback}" when unknown.`}
      >
        {`‹${FIELD_LABELS[field]}›`}
      </span>
    )
  }
  if (me.state === 'loading') return <span aria-hidden className="inline-block min-w-0" />
  const attrs = st.view.kind === 'persona' && (editable || me.canViewAll) ? st.view.attributes : me.viewer
  return <span>{fieldValue(field, attrs, orgOptions) ?? fallback}</span>
}

export default ViewerField
