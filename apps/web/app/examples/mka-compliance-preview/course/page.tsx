'use client'
// MKA fork: DEV-ONLY preview of the course "Compliance" tab body on the mock layer. See ../page.tsx. (Lives under /examples because the tenant proxy skips that prefix.)
import { notFound, useSearchParams } from 'next/navigation'
import { Suspense } from 'react'
import MkaCourseComplianceTab from '@components/mka/compliance/MkaCourseComplianceTab'
import { MKA_COMPLIANCE_MOCK } from '@services/mka/compliance'

function Inner() {
  const course = useSearchParams().get('course') ?? 'course_mock-tarbiyyat'
  return (
    <div className="min-h-screen bg-[#f8f8f8]">
      <MkaCourseComplianceTab courseUUID={course} />
    </div>
  )
}

export default function CourseCompliancePreview() {
  if (!MKA_COMPLIANCE_MOCK) notFound()
  return (
    <Suspense fallback={null}>
      <Inner />
    </Suspense>
  )
}
