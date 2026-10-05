'use client'
// MKA fork: DEV-ONLY preview of the compliance page on the mock layer (no auth / API needed), used for screenshots.
// 404s unless NEXT_PUBLIC_MKA_COMPLIANCE_MOCK=1 (and never in a production build).
import { notFound } from 'next/navigation'
import MkaCompliancePage from '@components/mka/compliance/MkaCompliancePage'
import { MKA_COMPLIANCE_MOCK } from '@services/mka/compliance'

export default function CompliancePreview() {
  if (!MKA_COMPLIANCE_MOCK) notFound()
  return (
    <div className="h-screen">
      <MkaCompliancePage orgslug="preview" />
    </div>
  )
}
