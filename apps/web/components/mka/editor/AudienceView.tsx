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
import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { Editor } from '@tiptap/react'
import type { Node as PMNode } from '@tiptap/pm/model'
import { Popover, PopoverAnchor, PopoverContent } from '@components/ui/popover'
import { useEditorProvider } from '@components/Contexts/Editor/EditorContext'
import { useAudienceCount, useAudienceOptions, useAudienceScope, useMkaViewer } from '@services/mka/attributes'
import { DEFAULT_RULE } from '../audience/types'
import type { AudienceOptions, Rule } from '../audience/types'
import type { DescribeOptions } from '../audience/describe'
import { validateRule } from '../audience/evaluate'
import { describeRule } from '../audience/describe'
import { getAudienceStore, useAudienceStore } from './store'
import { isRuleEditable, resolveSectionMode, ruleWarnings, showsPreviewLabel } from './logic'
import type { SectionMode } from './logic'
import type { AudienceNodeOptions, AudienceNodeViewApi } from './AudienceNodeView'
import { MkaErrorBoundary } from './MkaErrorBoundary'
import { AudienceHeader, HiddenPlaceholder, ReadOnlyBadge } from './AudienceHeader'
import { AudiencePicker } from './AudiencePicker'

type Props = {
  nodeView: AudienceNodeViewApi
  node: PMNode
  editor: Editor
  getPos: () => number | undefined
  options: AudienceNodeOptions
}

const FALLBACK_DESCRIBE: DescribeOptions = {
  levels: [
    { key: 'national', label: 'National' },
    { key: 'regional', label: 'Regional' },
    { key: 'local', label: 'Local' },
  ],
  departments: [],
  roles: [],
  regions: [],
  majlis: [],
}
const describeWith = (rule: Rule, o: AudienceOptions | undefined) => describeRule(rule, o ?? FALLBACK_DESCRIBE)

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
  const orgOptions = useAudienceOptions(scope.orgId).data

  const rule = node.attrs.rule
  const id = node.attrs.id as string | null
  const norm = useMemo(() => {
    const r = validateRule(rule)
    return r.ok ? r.rule : null
  }, [rule])
  const label = norm ? norm.label || describeWith(norm, orgOptions) : DAMAGED_LABEL

  const mode = resolveSectionMode({
    view: st.view,
    viewerState: me.state,
    viewer: me.viewer,
    canViewAll: me.canViewAll,
    editable,
    rule,
  })
  const collapsed = mode === 'chrome' && !!id && !!st.collapsed[id]

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
  if (mode === 'chrome' && editable) return <AuthorHeader {...p} />
  if (mode === 'chrome') return <ReadOnlyBadge rule={norm ?? DEFAULT_RULE} label={label} className="mb-1" />
  if (mode === 'placeholder') return <HiddenPlaceholder label={label} className="my-1" />
  if (showsPreviewLabel(mode, st.view, editable, canViewAll)) {
    return (
      <div className="mb-1 text-[11px] text-slate-500 dark:text-slate-400" data-testid="mka-audience-preview-label">
        Visible to: {label}
      </div>
    )
  }
  return null
}

function AuthorHeader(p: ChromeProps) {
  const { node, editor, norm, label, collapsed, scope, authorDepartment } = p
  const id = node.attrs.id as string | null
  const store = getAudienceStore(editor)
  const st = useAudienceStore(editor)
  const orgOptions = useAudienceOptions(scope.orgId).data
  const count = useAudienceCount(scope.orgId, scope.courseUuid, norm)
  const [open, setOpen] = useState(false)
  const [isNew, setIsNew] = useState(false)
  const startRule = useRef<Rule>(norm ?? DEFAULT_RULE)

  // A freshly inserted section opens its picker immediately.
  useEffect(() => {
    if (id && st.openPickerFor === id) {
      startRule.current = norm ?? DEFAULT_RULE
      setIsNew(true)
      setOpen(true)
      store.set({ openPickerFor: null })
    }
  }, [st.openPickerFor, id, norm, store])

  const editableRule = isRuleEditable(node.attrs.rule)
  const warnings = useMemo(
    () => ruleWarnings(node.attrs.rule, orgOptions, count.state === 'ready' && count.data?.count === 0),
    [node.attrs.rule, orgOptions, count],
  )

  const apply = (next: Rule) => {
    if (!id) return
    const withLabel: Rule = { ...next, label: describeWith(next, orgOptions) }
    editor.commands.updateMkaAudienceRule(id, withLabel)
  }

  const close = () => {
    setOpen(false)
    setIsNew(false)
  }

  const cancel = () => {
    if (id) {
      if (isNew) editor.commands.unsetMkaAudience(id)
      else editor.commands.updateMkaAudienceRule(id, startRule.current)
    }
    close()
  }

  const toggleCollapse = () => {
    if (!id) return
    const next = { ...st.collapsed }
    if (next[id]) delete next[id]
    else {
      next[id] = true
      // Keep the caret out of content that is about to leave the page.
      const pos = p.getPos()
      if (typeof pos === 'number') editor.commands.setTextSelection(pos + node.nodeSize)
    }
    store.set({ collapsed: next })
  }

  return (
    <Popover open={open} onOpenChange={(o) => (o ? setOpen(true) : close())}>
      <PopoverAnchor asChild>
        <div>
          <AudienceHeader
            rule={norm ?? DEFAULT_RULE}
            label={label}
            count={count}
            onEdit={
              editableRule
                ? () => {
                    startRule.current = norm ?? DEFAULT_RULE
                    setIsNew(false)
                    setOpen(true)
                  }
                : undefined
            }
            onPreview={() => store.set({ view: { kind: 'self' } })}
            onToggleCollapse={toggleCollapse}
            collapsed={collapsed}
            blockCount={node.childCount}
            warnings={warnings}
          />
        </div>
      </PopoverAnchor>
      <PopoverContent
        align="start"
        className="w-[min(34rem,calc(100vw-2rem))] max-sm:fixed max-sm:inset-x-0 max-sm:bottom-0 max-sm:top-auto max-sm:w-full"
      >
        <AudiencePicker
          value={norm ?? DEFAULT_RULE}
          onChange={apply}
          onDone={close}
          onCancel={cancel}
          onRemove={
            id
              ? () => {
                  editor.commands.unsetMkaAudience(id)
                  close()
                }
              : undefined
          }
          options={orgOptions}
          authorDepartment={authorDepartment}
          count={count}
          isNew={isNew}
        />
      </PopoverContent>
    </Popover>
  )
}

export default AudienceView
