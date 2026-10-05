'use client'
// MKA fork: native Compliance page (fork-only file; no upstream hooks needed for the route itself).
import React, { use } from 'react'
import MkaCompliancePage from '@components/mka/compliance/MkaCompliancePage'

export default function CompliancePage(props: { params: Promise<{ orgslug: string }> }) {
  const { orgslug } = use(props.params)
  return <MkaCompliancePage orgslug={orgslug} />
}
