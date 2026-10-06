'use client'
/**
 * React side of an audience section: a mode controller (decides what the section does for this viewer and
 * tells the node view) plus the visual chrome (author header, picker, read-only badge, placeholders).
 *
 * Failure policy (documented choice): the controller is the only part that decides visibility.
 *  - If the controller throws, authoring editors show the content plainly (never lose an author's work);
 *    every other editor shows NOTHING (fail-safe hide: we cannot evaluate the rule, so we do not risk
 *    showing another audience's content).
 *  - If only the chrome throws, the mode already set by the controller stands and the chrome renders nothing.
 */
import React, { lazy, Suspense, useEffect, useLayoutEffect, useMemo } from 'react'
import type { Editor } from '@tiptap/react'
import type { Node as PMNode } from '@tiptap/pm/model'
import { useEditorProvider } from '@components/Contexts/Editor/EditorContext'
import { useAudienceCount, useAudienceOptions, useAudienceScope, useMkaViewer } from '@services/mka/attributes'
import type { Rule } from '../audience/types'
import { validateRule } from '../audience/evaluate'
import { sectionLabel } from './describeWith'
import { getAudienceStore, publishViewing, useAudienceStore } from './store'
import { resolveSectionMode, showsPreviewLabel } from './logic'
import type { SectionMode } from './logic'
import type { AudienceNodeOptions, AudienceNodeViewApi } from './AudienceNodeView'
import { MkaErrorBoundary } from './MkaErrorBoundary'

// Author chrome is code-split: learner viewers (DynamicCanva, EditorPreview) never download the picker, header or
// preview menu. Learners cannot reach these branches, and a section still hides before any chunk loads.
const AuthorSection = lazy(() => import('./AuthorSection'))
const SectionNotice = lazy(() => import('./SectionNotices'))

type Props = {
  nodeView: AudienceNodeViewApi
  node: PMNode
  editor: Editor
  getPos: () => number | undefined
  options: AudienceNodeOptions
}

const DAMAGED_LABEL = 'Damaged audience: choose who should see this'

export function AudienceView(props: Props) {
  const { nodeView, options } = props
  return (
    <MkaErrorBoundary
      onError={() => nodeView.setMode(options.editable ? 'content' : 'hidden')}
      fallback={null}
    >
      <ModeController {...props} />
    </MkaErrorBoundary>
  )
}

function ModeController(props: Props) {
  const { nodeView, node, editor, options } = props
  const provider = useEditorProvider() as { isEditable?: boolean } | null
  const editable = provider?.isEditable === true
  const scope = useAudienceScope(options.activity, { courseUuid: options.courseUuid, orgId: options.orgId })
  const me = useMkaViewer(scope.courseUuid)
  const st = useAudienceStore(editor)
  const showsChrome = editable || me.canViewAll
  const orgOptions = useAudienceOptions(scope.orgId, showsChrome).data

  const rule = node.attrs.rule
  const id = node.attrs.id as string | null
  const norm = useMemo(() => {
    const r = validateRule(rule)
    return r.ok ? r.rule : null
  }, [rule])
  const label = norm ? sectionLabel(norm, orgOptions) : DAMAGED_LABEL

  const mode = resolveSectionMode({
    view: st.view,
    viewerState: me.state,
    viewer: me.viewer,
    canViewAll: me.canViewAll,
    editable,
    rule,
  })
  const collapsed = mode === 'chrome' && !!id && !!st.collapsed[id]

  // Feed the plain-TS driver (learner filter, copy policy, notes). Section controllers are node views and mount reliably.
  useEffect(() => {
    publishViewing(getAudienceStore(editor), {
      state: me.state,
      viewer: me.viewer,
      canViewAll: me.canViewAll,
      providerEditable: editable,
    })
  }, [editor, me.state, me.viewer, me.canViewAll, editable])

  // Layout effect: the content is attached/detached before the browser paints (no flash).
  useLayoutEffect(() => {
    nodeView.setMode(mode, { collapsed, label })
  }, [nodeView, mode, collapsed, label])

  return (
    <MkaErrorBoundary fallback={null}>
      <SectionChrome
        {...props}
        mode={mode}
        editable={editable}
        canViewAll={me.canViewAll}
        norm={norm}
        label={label}
        collapsed={collapsed}
        scope={scope}
        authorDepartment={me.viewer?.department ?? null}
      />
    </MkaErrorBoundary>
  )
}

type ChromeProps = Props & {
  mode: SectionMode
  editable: boolean
  canViewAll: boolean
  norm: Rule | null
  label: string
  collapsed: boolean
  scope: { orgId: number | null; courseUuid: string | null }
  authorDepartment: string | null
}

function SectionChrome(p: ChromeProps) {
  const { mode, editable, canViewAll, label, editor, norm } = p
  const st = useAudienceStore(editor)
  if (mode === 'chrome' && editable) {
    return (
      <Suspense fallback={null}>
        <AuthorSection
          node={p.node}
          editor={editor}
          getPos={p.getPos}
          norm={norm}
          label={label}
          collapsed={p.collapsed}
          scope={p.scope}
          authorDepartment={p.authorDepartment}
        />
      </Suspense>
    )
  }
  if (mode === 'chrome' || mode === 'placeholder') {
    return (
      <Suspense fallback={null}>
        <SectionNotice kind={mode === 'chrome' ? 'badge' : 'placeholder'} label={label} rule={norm} />
      </Suspense>
    )
  }
  if (showsPreviewLabel(mode, st.view, editable, canViewAll)) {
    return (
      <div className="mb-1 text-[11px] text-slate-500 dark:text-slate-400" data-testid="mka-audience-preview-label">
        Visible to: {label}
      </div>
    )
  }
  return null
}

export default AudienceView
