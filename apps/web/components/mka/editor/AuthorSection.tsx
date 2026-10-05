'use client'
// MKA fork — author header + picker for one audience section. Lazy-loaded (see AudienceView) so learner bundles
// never include the picker, preview menu or header chrome.
import React, { useEffect, useMemo, useRef, useState } from 'react'
import type { Editor } from '@tiptap/react'
import type { Node as PMNode } from '@tiptap/pm/model'
import { Popover, PopoverAnchor, PopoverContent } from '@components/ui/popover'
import { useAudienceCount, useAudienceOptions } from '@services/mka/attributes'
import { useMkaAudienceEnabled } from '@services/mka/useMkaAudienceEnabled'
import { DEFAULT_RULE } from '../audience/types'
import type { Rule } from '../audience/types'
import { describeWith } from './describeWith'
import { getAudienceStore, useAudienceStore } from './store'
import { isRuleEditable, ruleWarnings } from './logic'
import { AudienceHeader } from './AudienceHeader'
import { AudiencePicker } from './AudiencePicker'
import { useIsNarrow } from './audience-ui'

export type AuthorSectionProps = {
  node: PMNode
  editor: Editor
  getPos: () => number | undefined
  norm: Rule | null
  label: string
  collapsed: boolean
  scope: { orgId: number | null; courseUuid: string | null }
  authorDepartment: string | null
}

export default function AuthorSection(p: AuthorSectionProps) {
  const { node, editor, norm, label, collapsed, scope, authorDepartment } = p
  const id = node.attrs.id as string | null
  const store = getAudienceStore(editor)
  const st = useAudienceStore(editor)
  const orgOptions = useAudienceOptions(scope.orgId).data
  const previewEnabled = useMkaAudienceEnabled()
  const count = useAudienceCount(scope.orgId, scope.courseUuid, norm)
  const narrow = useIsNarrow()
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
    // Live preview: not an undo step. Only Done records history (see commit*MkaAudience).
    editor.commands.updateMkaAudienceRule(id, withLabel, { addToHistory: false })
  }

  const close = () => {
    setOpen(false)
    setIsNew(false)
  }

  const done = () => {
    if (id) {
      if (isNew) editor.commands.commitNewMkaAudience(id)
      else editor.commands.commitEditMkaAudience(id, startRule.current)
    }
    close()
  }

  const cancel = () => {
    if (id) {
      // Only Done commits. Cancelling a NEW section removes it (an empty inserted one entirely, a wrapped one
      // by unwrapping); cancelling an edit reverts to the rule it had when the picker opened.
      if (isNew) editor.commands.cancelNewMkaAudience(id)
      else editor.commands.updateMkaAudienceRule(id, startRule.current, { addToHistory: false })
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

  const picker = (
    <AudiencePicker
      value={norm ?? DEFAULT_RULE}
      onChange={apply}
      onDone={done}
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
  )

  const header = (
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
      // Preview is an authoring entry point; its exit chip lives in the bar, which also shows whenever a preview is active.
      onPreview={previewEnabled ? () => store.set({ view: { kind: 'self' } }) : undefined}
      onToggleCollapse={toggleCollapse}
      collapsed={collapsed}
      blockCount={node.childCount}
      warnings={warnings}
    />
  )

  // Phones: the picker is its own bottom sheet (seam C), so there is no popover to anchor.
  if (narrow) {
    return (
      <>
        {header}
        {open ? picker : null}
      </>
    )
  }
  return (
    <Popover open={open} onOpenChange={(o) => (o ? setOpen(true) : cancel())}>
      <PopoverAnchor asChild>
        <div>{header}</div>
      </PopoverAnchor>
      <PopoverContent
        align="start"
        collisionPadding={8}
        className="max-h-(--radix-popover-content-available-height) w-[min(34rem,calc(100vw-2rem))] overflow-y-auto border-0 bg-transparent p-0 shadow-none"
      >
        {picker}
      </PopoverContent>
    </Popover>
  )
}

