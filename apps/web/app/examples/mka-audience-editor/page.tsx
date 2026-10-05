'use client'
// MKA fork — DEV-ONLY harness: the real viewer (DynamicCanva) and a TipTap authoring editor with the MKA extensions
// inside the real EditorOptionsProvider, against the mock attributes layer. 404s unless NEXT_PUBLIC_MKA_AUDIENCE_MOCK=1
// (never in a production build). Query: ?mode=view|edit, ?mka_viewer=<persona id>, ?mka_admin=1.
import React, { Suspense } from 'react'
import { notFound, useSearchParams } from 'next/navigation'
import { useEditor, EditorContent } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import EditorOptionsProvider from '@components/Contexts/Editor/EditorContext'
import Canva from '@components/Objects/Activities/DynamicCanva/DynamicCanva'
import { SlashCommands } from '@components/Objects/Editor/Extensions/SlashCommands'
import { mkaEditorExtensions } from '@components/mka/editor'
import { mkaAudienceMock } from '@services/mka/flags'

const rule = (level: string, mode = 'show') => ({ v: 1, mode, groups: [{ level: [level] }] })
const p = (t: string) => ({ type: 'paragraph', content: [{ type: 'text', text: t }] })
const sec = (id: string, t: string, r: unknown) => ({ type: 'mkaAudience', attrs: { id, rule: r }, content: [p(t)] })
const content = {
  type: 'doc',
  content: [
    p('PUBLIC intro paragraph'),
    { type: 'paragraph', content: [{ type: 'text', text: 'You are in ' }, { type: 'mkaViewerField', attrs: { field: 'majlis', fallback: 'your Majlis' } }] },
    sec('a', 'LOCAL-ONLY: submit your monthly report', rule('local')),
    sec('b', 'REGIONAL-ONLY: review local reports', rule('regional')),
    sec('c', 'NOT-LOCAL: everyone except local', rule('local', 'hide')),
    { type: 'mkaCounterparts', attrs: { id: null } },
    p('Select me and press the shortcut.'),
    p('Second line for wrapping.'),
  ],
}

function Authoring() {
  const editor = useEditor({
    immediatelyRender: false,
    extensions: [StarterKit, SlashCommands.configure({}), ...mkaEditorExtensions({ editable: true, activity: { org_id: 1 }, courseUuid: 'course_x' })],
    content,
  })
  React.useEffect(() => {
    ;(window as unknown as { __editor?: unknown }).__editor = editor
  }, [editor])
  return (
    <EditorOptionsProvider options={{ isEditable: true }}>
      <div className="rounded border p-4"><EditorContent editor={editor} /></div>
    </EditorOptionsProvider>
  )
}

function Inner() {
  const mode = useSearchParams().get('mode') ?? 'view'
  return (
    <div className="mx-auto max-w-3xl space-y-4 p-6">
      {mode === 'edit' ? (
        <Authoring />
      ) : (
        <Canva content={content as never} activity={{ org_id: 1, activity_uuid: 'activity_x' }} courseUuid="course_x" hideTableOfContents />
      )}
    </div>
  )
}

export default function Page() {
  if (!mkaAudienceMock()) notFound()
  return (
    <Suspense>
      <Inner />
    </Suspense>
  )
}
