'use client'
import React, { useState } from 'react'
import { BellRing, Download, Loader2 } from 'lucide-react'
import { Button } from '@components/ui/button'
import {
  MKA_COMPLIANCE_REMIND,
  complianceToday,
  downloadChaseListCsv,
  useComplianceAuth,
} from '@services/mka/compliance'
import type { LearnerFilters } from '@services/mka/compliance.types'
import { chaseListFilename } from './format'

/**
 * "Download chase list (CSV)". Fetched with the bearer token (the API
 * scope-checks it); saved under a locally sanitised filename. Respects the
 * table's current filters so a head can export "Overdue in Gulf" directly.
 */
export function DownloadChaseList({
  courseUuid,
  courseName,
  filters,
  cycleId,
  disabled,
}: {
  courseUuid: string
  courseName: string
  filters: LearnerFilters
  cycleId: number | null
  disabled?: boolean
}) {
  const auth = useComplianceAuth()
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState(false)

  async function run() {
    setBusy(true)
    setFailed(false)
    try {
      await downloadChaseListCsv(auth, courseUuid, filters, cycleId, chaseListFilename(courseName, complianceToday()))
    } catch {
      setFailed(true)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-col items-start gap-1">
      <Button type="button" variant="outline" onClick={run} disabled={disabled || busy} className="bg-white">
        {busy ? <Loader2 aria-hidden="true" className="animate-spin" /> : <Download aria-hidden="true" />}
        Download chase list (CSV)
      </Button>
      <span role="status" aria-live="polite" className={failed ? 'text-xs text-red-700' : 'sr-only'}>
        {failed ? "Couldn't download the list. Try again." : busy ? 'Preparing download' : ''}
      </span>
    </div>
  )
}

/**
 * Reminders are pending a product decision. Renders nothing unless
 * NEXT_PUBLIC_MKA_COMPLIANCE_REMIND=1, and even then is an inert placeholder.
 */
export function RemindPlaceholder() {
  if (!MKA_COMPLIANCE_REMIND) return null
  return (
    <Button type="button" variant="outline" disabled title="Reminders are coming soon" className="bg-white">
      <BellRing aria-hidden="true" />
      Remind (coming soon)
    </Button>
  )
}
