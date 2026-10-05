'use client'
import React, { useState } from 'react'
import { Download, Loader2 } from 'lucide-react'
import { Button } from '@components/ui/button'
import {
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
  const [notice, setNotice] = useState<string | null>(null)

  async function run() {
    setBusy(true)
    setFailed(false)
    setNotice(null)
    try {
      const r = await downloadChaseListCsv(auth, courseUuid, filters, cycleId, chaseListFilename(courseName, complianceToday()))
      setNotice(r.notice)
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
      <span
        role="status"
        aria-live="polite"
        className={failed ? 'text-xs text-red-700' : notice ? 'max-w-64 text-xs text-amber-800' : 'sr-only'}
      >
        {failed ? "Couldn't download the list. Try again." : busy ? 'Preparing download' : (notice ?? '')}
      </span>
    </div>
  )
}
