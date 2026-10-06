'use client'
/**
 * Single import surface for the upstream course-page hook (H3):
 *   import MkaCourseComplianceTab, { useMkaCourseTabs } from '@components/mka/compliance/course-tab' // MKA fork
 * Tab visibility is cosmetic; the API enforces on every endpoint.
 */
import { ShieldCheck, type LucideIcon } from 'lucide-react'
import { useComplianceScopeQuery } from '@services/mka/compliance'
import type { ComplianceScope, ScopeCourse } from '@services/mka/compliance.types'
import { sameCourse } from './format'
import MkaCourseComplianceTab from './MkaCourseComplianceTab'

export interface MkaCourseTab {
  key: 'compliance'
  label: string
  icon: LucideIcon
  href: string
  requiredPermission: 'update'
  /** No plan gate: never shown a plan badge (typed so `tabs.push` stays compatible with the upstream tab union). */
  requiresPlan?: undefined
}

/**
 * Pure: the tab list for a course. Empty unless the viewer's scope is `all`, or
 * `own` and this course is one of theirs.
 */
export function mkaCourseTabs(
  courseuuid: string,
  scope: ComplianceScope,
  courses: Pick<ScopeCourse, 'course_uuid'>[] = [],
): MkaCourseTab[] {
  if (scope === 'none') return []
  if (scope === 'own' && !courses.some((c) => sameCourse(c.course_uuid, courseuuid))) return []
  return [
    {
      key: 'compliance',
      label: 'Compliance',
      icon: ShieldCheck,
      href: `/dash/courses/course/${courseuuid}/compliance`,
      requiredPermission: 'update',
    },
  ]
}

/** Hook wrapper used by the upstream page: `tabs.push(...useMkaCourseTabs(params.courseuuid))`. */
export function useMkaCourseTabs(courseuuid: string): MkaCourseTab[] {
  const { data, isPending } = useComplianceScopeQuery()
  // While the scope loads keep the tab (it is already gated by course `update`), so a deep link to
  // /compliance isn't bounced by the page's "unknown subpage" redirect; once loaded, `none` removes it.
  if (isPending) return mkaCourseTabs(courseuuid, 'all')
  return mkaCourseTabs(courseuuid, data?.scope ?? 'none', data?.courses)
}

export default MkaCourseComplianceTab
