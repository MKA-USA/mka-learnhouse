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
  const headerRef = useRef<HTMLDivElement>(null)
  // One-shot allowance for the programmatic refocus of the editor that the slash command performs right after the new
  // section's picker opens. Anything later (the author really moving focus or clicking into the editor) dismisses as usual.
  const refocusGraceUntil = useRef(0)
  // Where focus goes when the picker closes (never <body>): an existing section's Edit button, else the editor.
  const returnTo = useRef<'edit' | 'editor'>('editor')
  const restoreFocus = () => {
    if (returnTo.current === 'edit') {
      const edit = [...(headerRef.current?.querySelectorAll('button') ?? [])].find((b) => b.textContent?.trim() === 'Edit')
      if (edit) {
        edit.focus()
        return
      }
    }
    editor.commands.focus()
  }

  // Phones: the sheet is a Dialog without a trigger, so hand focus back ourselves when it closes.
  const wasOpen = useRef(false)
  useEffect(() => {
    if (narrow && wasOpen.current && !open) {
      wasOpen.current = false
      const t = setTimeout(restoreFocus, 0)
      return () => clearTimeout(t)
    }
    wasOpen.current = open
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, narrow])

  // A freshly inserted section opens its picker immediately.
  useEffect(() => {
    if (id && st.openPickerFor === id) {
      startRule.current = norm ?? DEFAULT_RULE
      setIsNew(true)
      setOpen(true)
      refocusGraceUntil.current = Date.now() + 400
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
    // A NEW section needs no commit step: its insert/wrap is already one history step and the live previews were not
    // history steps, so one Ctrl+Z removes it and redo restores it with the final rule. Only an EDIT needs folding
    // into one step.
    if (id && !isNew) editor.commands.commitEditMkaAudience(id, startRule.current)
    returnTo.current = isNew ? 'editor' : 'edit' // new: keep typing inside the section
    close()
  }

  const cancel = () => {
    if (id) {
      // Only Done commits. Cancelling a NEW section removes it (an empty inserted one entirely, a wrapped one
      // by unwrapping); cancelling an edit reverts to the rule it had when the picker opened.
      if (isNew) editor.commands.cancelNewMkaAudience(id)
      else editor.commands.updateMkaAudienceRule(id, startRule.current, { addToHistory: false })
    }
    returnTo.current = isNew ? 'editor' : 'edit'
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
              returnTo.current = 'editor'
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
        <div ref={headerRef}>{header}</div>
        {open ? picker : null}
      </>
    )
  }
  return (
    <Popover open={open} onOpenChange={(o) => (o ? setOpen(true) : cancel())}>
      <PopoverAnchor asChild>
        <div ref={headerRef}>{header}</div>
      </PopoverAnchor>
      <PopoverContent
        align="start"
        collisionPadding={8}
        // The slash command re-focuses the editor right after opening a NEW section's picker (the click blurred it). That
        // single programmatic focus must not dismiss (= cancel) the picker; any later focus or click does.
        onFocusOutside={(e) => {
          const target = e.target as Node | null
          if (target && editor.view.dom.contains(target) && refocusGraceUntil.current > Date.now()) {
            refocusGraceUntil.current = 0
            e.preventDefault()
          }
        }}
        onCloseAutoFocus={(e) => {
          e.preventDefault()
          restoreFocus()
        }}
        className="max-h-(--radix-popover-content-available-height) w-[min(34rem,calc(100vw-2rem))] overflow-y-auto border-0 bg-transparent p-0 shadow-none"
      >
        {picker}
      </PopoverContent>
    </Popover>
  )
}

