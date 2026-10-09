'use client'
// MKA fork — per-course Audience panel for the course Access tab. Renders nothing unless
// NEXT_PUBLIC_MKA_COURSE_AUDIENCE_ENABLED=1. API contract: services/mka/courseAudience.ts.
import React, { useEffect, useMemo, useState } from 'react'
import toast from 'react-hot-toast'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCourse } from '@components/Contexts/CourseContext'
import { useLHSession } from '@components/Contexts/LHSessionContext'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { useMkaCourseAudienceEnabled } from '@services/mka/courseAudienceFlag'
import {
  fetchCourseAudience,
  fetchCourseAudienceOptions,
  previewCourseAudience,
  removeCourseAudience,
  saveCourseAudience,
  type CourseAudienceKind,
  type CourseAudienceMode,
  type CustomRule,
} from '@services/mka/courseAudience'
import {
  DEFAULT_DRAFT,
  buildPayload,
  confirmText,
  draftFromState,
  draftsEqual,
  needsEnrollConfirm,
  normalizeOptions,
  previewText,
  resultText,
  sampleText,
  toggleValue,
  validateDraft,
  type Draft,
  type Option,
} from './logic'

const errMsg = (e: unknown) => (e instanceof Error ? e.message : 'Something went wrong')

export default function CourseAudiencePanel() {
  const enabled = useMkaCourseAudienceEnabled()
  if (!enabled) return null
  return <Panel />
}

function Panel() {
  const course = useCourse() as any
  const session = useLHSession() as any
  const token: string | undefined = session?.data?.tokens?.access_token
  const courseUuid: string | undefined = course?.courseStructure?.course_uuid
  const qc = useQueryClient()
  const stateKey = ['mka-course-audience', courseUuid] as const
  const ready = !!(courseUuid && token)

  const stateQ = useQuery({ queryKey: stateKey, queryFn: () => fetchCourseAudience(courseUuid!, token), enabled: ready, staleTime: 30_000 })
  const optionsQ = useQuery({ queryKey: ['mka-course-audience-options'], queryFn: () => fetchCourseAudienceOptions(token), enabled: !!token, staleTime: 5 * 60_000 })
  const options = useMemo(() => normalizeOptions(optionsQ.data), [optionsQ.data])

  const saved = useMemo(() => draftFromState(stateQ.data), [stateQ.data])
  // Local edits layer over the saved state; null = no unsaved edits.
  const [edited, setEdited] = useState<Draft | null>(null)
  const draft = edited ?? saved ?? DEFAULT_DRAFT
  const setDraft: React.Dispatch<React.SetStateAction<Draft>> = (u) =>
    setEdited((cur) => (typeof u === 'function' ? u(cur ?? saved ?? DEFAULT_DRAFT) : u))
  const [confirmOpen, setConfirmOpen] = useState(false)

  const error = validateDraft(draft)
  const payload = useMemo(() => buildPayload(draft), [draft])
  const payloadKey = JSON.stringify(payload)

  // Live preview: debounced, no writes.
  const [debounced, setDebounced] = useState(payloadKey)
  useEffect(() => {
    const id = setTimeout(() => setDebounced(payloadKey), 300)
    return () => clearTimeout(id)
  }, [payloadKey])
  const previewQ = useQuery({
    queryKey: ['mka-course-audience-preview', courseUuid, debounced],
    queryFn: () => previewCourseAudience(courseUuid!, JSON.parse(debounced), token),
    enabled: ready && stateQ.isSuccess && !error,
    staleTime: 10_000,
  })
  const preview = !error && debounced === payloadKey ? previewQ.data ?? null : null

  const saveM = useMutation({
    mutationFn: () => saveCourseAudience(courseUuid!, payload, token),
    onSuccess: (r) => {
      toast.success(resultText(r))
      setConfirmOpen(false)
      setEdited(null)
      qc.invalidateQueries({ queryKey: stateKey })
      qc.invalidateQueries({ queryKey: ['course', courseUuid] })
      qc.invalidateQueries({ queryKey: ['mka-course-audience-preview', courseUuid] })
    },
    onError: (e) => {
      setConfirmOpen(false)
      toast.error(errMsg(e))
    },
  })
  const removeM = useMutation({
    mutationFn: () => removeCourseAudience(courseUuid!, token),
    onSuccess: () => {
      toast.success('Audience removed. Existing enrollments were kept.')
      setEdited(null)
      qc.invalidateQueries({ queryKey: stateKey })
      qc.invalidateQueries({ queryKey: ['course', courseUuid] })
    },
    onError: (e) => toast.error(errMsg(e)),
  })

  if (!courseUuid) return null
  const busy = saveM.isPending || removeM.isPending
  const dirty = !draftsEqual(draft, saved)
  const onSave = () => {
    if (error) return
    if (needsEnrollConfirm(draft, preview)) setConfirmOpen(true)
    else saveM.mutate()
  }

  return (
    <section className="px-6 py-5 border-b border-gray-100" aria-labelledby="mka-aud-title">
      <h2 id="mka-aud-title" className="font-bold text-base text-gray-800">Audience</h2>
      <p className="text-sm text-gray-500 mt-0.5">Say once who this course is for. Matching people are enrolled or given access automatically.</p>

      {stateQ.isError && <p role="alert" className="text-sm text-destructive mt-3">Could not load the audience: {errMsg(stateQ.error)}</p>}
      {stateQ.isLoading && <p className="text-sm text-gray-400 mt-3">Loading...</p>}

      {stateQ.isSuccess && (
        <div className="mt-4 space-y-5">
          <RadioGroup
            value={draft.audience}
            onValueChange={(v: string) => setDraft((d) => ({ ...d, audience: v as CourseAudienceKind }))}
            disabled={busy}
            aria-label="Audience"
          >
            {AUDIENCE_CHOICES.map((c) => (
              <div key={c.value} className="flex items-start gap-2">
                <RadioGroupItem id={`mka-aud-${c.value}`} value={c.value} className="mt-0.5" />
                <Label htmlFor={`mka-aud-${c.value}`} className="font-normal flex flex-col items-start gap-0.5">
                  <span className="text-gray-800">{c.label}</span>
                  <span className="text-xs text-gray-500">{c.hint}</span>
                </Label>
              </div>
            ))}
          </RadioGroup>

          {draft.audience === 'custom' && (
            <div className="grid gap-4 sm:grid-cols-3 rounded-lg border border-gray-100 p-4">
              <Multi legend="Departments" options={options.departments} value={draft.rule.departments} disabled={busy} loading={optionsQ.isLoading}
                onToggle={(k) => setRule(setDraft, 'departments', k)} />
              <Multi legend="Levels" options={options.levels} value={draft.rule.levels} disabled={busy} loading={optionsQ.isLoading}
                onToggle={(k) => setRule(setDraft, 'levels', k)} />
              <Multi legend="Roles" options={options.roles} value={draft.rule.roles} disabled={busy} loading={optionsQ.isLoading}
                onToggle={(k) => setRule(setDraft, 'roles', k)} />
              <p className="sm:col-span-3 text-xs text-gray-500">Office holders only. Within a group any value matches; across groups all must match.</p>
            </div>
          )}
          {error && <p role="alert" className="text-sm text-destructive">{error}</p>}

          <fieldset className="space-y-2" disabled={busy}>
            <legend className="text-sm font-medium text-gray-800">How should matching people get it?</legend>
            <RadioGroup value={draft.mode} onValueChange={(v: string) => setDraft((d) => ({ ...d, mode: v as CourseAudienceMode }))} aria-label="Mode">
              {MODE_CHOICES.map((c) => (
                <div key={c.value} className="flex items-start gap-2">
                  <RadioGroupItem id={`mka-mode-${c.value}`} value={c.value} className="mt-0.5" />
                  <Label htmlFor={`mka-mode-${c.value}`} className="font-normal flex flex-col items-start gap-0.5">
                    <span className="text-gray-800">{c.label}</span>
                    <span className="text-xs text-gray-500">{c.hint}</span>
                  </Label>
                </div>
              ))}
            </RadioGroup>
          </fieldset>

          <div aria-live="polite" className="rounded-lg bg-gray-50 px-4 py-3 text-sm text-gray-700">
            {error ? 'Choose a filter to see who matches.' : preview ? (
              <>
                <div className="font-medium">{previewText(preview, draft.mode)}</div>
                {sampleText(preview) && <div className="mt-1 text-xs text-gray-500">{sampleText(preview)}</div>}
              </>
            ) : previewQ.isError ? 'Preview unavailable.' : 'Counting...'}
          </div>

          {saved && (
            <p className="text-xs text-gray-500">
              This audience manages the course access settings below (public / user groups). Anyone who stops matching keeps their progress but loses access, unless the audience is Everyone.
            </p>
          )}

          <div className="flex flex-wrap gap-2">
            <Button onClick={onSave} disabled={busy || !!error || (!dirty && !!saved)}>
              {saveM.isPending ? 'Saving...' : saved ? 'Save audience' : 'Set audience'}
            </Button>
            {saved && (
              <Button variant="outline" onClick={() => removeM.mutate()} disabled={busy}>
                {removeM.isPending ? 'Removing...' : 'Remove audience'}
              </Button>
            )}
          </div>
        </div>
      )}

      <Dialog open={confirmOpen} onOpenChange={(o) => !saveM.isPending && setConfirmOpen(o)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{preview ? confirmText(preview) : 'Enroll people now?'}</DialogTitle>
            <DialogDescription>
              Required courses enroll everyone who matches right away. People who stop matching later are never un-enrolled.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmOpen(false)} disabled={saveM.isPending}>Cancel</Button>
            <Button onClick={() => saveM.mutate()} disabled={saveM.isPending}>{saveM.isPending ? 'Enrolling...' : 'Enroll and save'}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  )
}

const AUDIENCE_CHOICES: { value: CourseAudienceKind; label: string; hint: string }[] = [
  { value: 'everyone', label: 'Everyone', hint: 'All signed-in members of the organization (not anonymous visitors).' },
  { value: 'officeholders', label: 'Office holders', hint: 'Every verified office holder.' },
  { value: 'custom', label: 'Specific departments, levels or roles', hint: 'Verified office holders matching the filter below.' },
]
const MODE_CHOICES: { value: CourseAudienceMode; label: string; hint: string }[] = [
  { value: 'required', label: 'Required', hint: 'Matching people are enrolled automatically.' },
  { value: 'optin', label: 'Opt-in', hint: 'Matching people can find and start it; nobody is enrolled for them.' },
]

function setRule(setDraft: React.Dispatch<React.SetStateAction<Draft>>, key: keyof CustomRule, value: string) {
  setDraft((d) => ({ ...d, rule: { ...d.rule, [key]: toggleValue(d.rule[key], value) } }))
}

function Multi(props: { legend: string; options: Option[]; value: string[]; disabled: boolean; loading: boolean; onToggle: (_key: string) => void }) {
  return (
    <fieldset className="min-w-0">
      <legend className="text-sm font-medium text-gray-800 mb-2">{props.legend}</legend>
      <div className="max-h-48 overflow-y-auto space-y-1.5 pe-1">
        {props.loading && <p className="text-xs text-gray-400">Loading...</p>}
        {props.options.map((o) => {
          const id = `mka-aud-${props.legend}-${o.key}`
          return (
            <div key={o.key} className="flex items-center gap-2">
              <Checkbox id={id} checked={props.value.includes(o.key)} onCheckedChange={() => props.onToggle(o.key)} disabled={props.disabled} />
              <Label htmlFor={id} className="font-normal text-sm">{o.label}</Label>
            </div>
          )
        })}
      </div>
    </fieldset>
  )
}
