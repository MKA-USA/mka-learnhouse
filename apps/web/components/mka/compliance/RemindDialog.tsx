'use client'
import React, { useCallback, useRef, useState } from 'react'
import { BellRing, Loader2 } from 'lucide-react'
import toast from 'react-hot-toast'
import { Button } from '@components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@components/ui/dialog'
import { MKA_COMPLIANCE_REMIND, errorStatus, remindCourse, useComplianceAuth } from '@services/mka/compliance'
import type { RemindResponse } from '@services/mka/compliance.types'
import { canSendReminders, remindErrorMessage, remindHeadline, remindSkipped } from './format'

export type RemindPhase =
  | { kind: 'loading' }
  | { kind: 'preview'; data: RemindResponse }
  | { kind: 'sending'; data: RemindResponse }
  | { kind: 'error'; status: number | null }

/**
 * Presentational body of the dialog (no hooks, no Radix context) so every phase can be rendered in tests.
 * The first screen is ALWAYS a dry-run preview; nothing is sent until the person confirms it.
 */
export function RemindDialogView({
  phase,
  onConfirm,
  onRetry,
  onClose,
}: {
  phase: RemindPhase
  onConfirm: () => void
  onRetry: () => void
  onClose: () => void
}) {
  if (phase.kind === 'loading') {
    return (
      <p role="status" aria-live="polite" className="flex items-center gap-2 text-sm text-gray-600">
        <Loader2 aria-hidden="true" className="size-4 animate-spin" />
        Checking who still needs a reminder…
      </p>
    )
  }

  if (phase.kind === 'error') {
    // 429 / 403 / 404 / 409 are final answers; only an unknown failure is worth retrying.
    const retryable = ![403, 404, 409, 429].includes(phase.status ?? 0)
    return (
      <div className="space-y-4">
        <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
          {remindErrorMessage(phase.status)}
        </p>
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button type="button" variant="outline" onClick={onClose}>
            Close
          </Button>
          {retryable ? (
            <Button type="button" onClick={onRetry}>
              Try again
            </Button>
          ) : null}
        </div>
      </div>
    )
  }

  const { data } = phase
  const sending = phase.kind === 'sending'
  const skipped = remindSkipped(data)
  const can = canSendReminders(data)
  return (
    <div className="space-y-4">
      <div role="status" aria-live="polite" className="space-y-1">
        <p className="text-base font-semibold text-gray-900">{remindHeadline(data)}</p>
        {skipped ? <p className="text-sm text-gray-600">{skipped}</p> : null}
      </div>
      {data.test_mode ? (
        <p className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
          Test mode is on: these emails go to the test address only. Nobody on the list receives anything.
        </p>
      ) : null}
      {!data.enabled ? (
        <p className="rounded-lg border border-gray-200 bg-gray-50 p-3 text-sm text-gray-700">
          Reminders aren&apos;t switched on yet, so this is a preview only.
        </p>
      ) : null}
      <p className="text-xs text-gray-500">
        Each person gets at most one reminder a week, and a course can be reminded once every 24 hours.
      </p>
      <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <Button type="button" variant="outline" onClick={onClose} disabled={sending}>
          Cancel
        </Button>
        <Button type="button" onClick={onConfirm} disabled={!can || sending}>
          {sending ? <Loader2 aria-hidden="true" className="animate-spin" /> : <BellRing aria-hidden="true" />}
          {sending ? 'Sending…' : `Send ${data.would_send} ${data.would_send === 1 ? 'reminder' : 'reminders'}`}
        </Button>
      </div>
    </div>
  )
}

/**
 * "Remind" on the course Compliance tab. Hidden unless NEXT_PUBLIC_MKA_COMPLIANCE_REMIND=1. The server decides who
 * may press it (scope check, API tokens refused, 24 h limit); this only words the answers.
 */
export function RemindButton({
  courseUuid,
  courseName,
  cycleId,
  disabled,
  blockedReason,
}: {
  courseUuid: string
  courseName: string
  cycleId: number | null
  disabled?: boolean
  /** Set when the cycle on screen is not the current, started one: the button stays visible but off, with this as the tooltip. */
  blockedReason?: string | null
}) {
  const auth = useComplianceAuth()
  const [open, setOpen] = useState(false)
  const [phase, setPhase] = useState<RemindPhase>({ kind: 'loading' })
  const seq = useRef(0) // a late answer for a closed / restarted dialog is dropped

  const preview = useCallback(async () => {
    const mine = ++seq.current
    setPhase({ kind: 'loading' })
    try {
      const data = await remindCourse(auth, courseUuid, cycleId, true)
      if (seq.current === mine) setPhase({ kind: 'preview', data })
    } catch (err) {
      if (seq.current === mine) setPhase({ kind: 'error', status: errorStatus(err) })
    }
  }, [auth, courseUuid, cycleId])

  function openDialog() {
    setOpen(true)
    void preview()
  }

  function closeDialog() {
    seq.current++ // drop any answer still in flight
    setOpen(false)
  }

  async function confirm() {
    if (phase.kind !== 'preview') return
    const before = phase.data
    const mine = ++seq.current
    setPhase({ kind: 'sending', data: before })
    try {
      const result = await remindCourse(auth, courseUuid, cycleId, false)
      if (seq.current !== mine) return
      setOpen(false)
      toast.success(remindHeadline(result))
    } catch (err) {
      if (seq.current !== mine) return
      const status = errorStatus(err)
      setOpen(false)
      toast.error(remindErrorMessage(status))
    }
  }

  if (!MKA_COMPLIANCE_REMIND) return null
  return (
    <>
      {/* a disabled button swallows hover, so the explanation lives on the wrapper */}
      <span title={blockedReason ?? undefined} className="inline-flex">
        <Button
          type="button"
          variant="outline"
          onClick={openDialog}
          disabled={disabled || Boolean(blockedReason)}
          aria-describedby={blockedReason ? 'mka-remind-blocked' : undefined}
          className="bg-white"
        >
          <BellRing aria-hidden="true" />
          Remind
        </Button>
        {blockedReason ? <span id="mka-remind-blocked" className="sr-only">{blockedReason}</span> : null}
      </span>
      <Dialog open={open} onOpenChange={(next) => {
          if (phase.kind === 'sending') return
          if (next) openDialog()
          else closeDialog()
        }}>
        <DialogContent className="max-h-[90vh] overflow-y-auto bg-white sm:max-w-md">
          <DialogHeader className="p-6 pb-2">
            <DialogTitle>Remind people about this course</DialogTitle>
            <DialogDescription>{courseName}</DialogDescription>
          </DialogHeader>
          <div className="p-6 pt-2">
            <RemindDialogView phase={phase} onConfirm={() => void confirm()} onRetry={() => void preview()} onClose={closeDialog} />
          </div>
        </DialogContent>
      </Dialog>
    </>
  )
}
