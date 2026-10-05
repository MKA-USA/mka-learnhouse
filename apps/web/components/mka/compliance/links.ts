import { getUriWithOrg } from '@services/config/config'
import { bareCourseUuid, buildQuery } from './format'

/** Link to a course's Compliance tab, optionally pre-filtered (read once by the tab on mount). */
export function courseTabHref(
  orgslug: string,
  courseUuid: string,
  filters: { region?: string | null; status?: string | null } = {},
): string {
  const qs = buildQuery({ region: filters.region ?? undefined, status: filters.status ?? undefined })
  const path = `/dash/courses/course/${encodeURIComponent(bareCourseUuid(courseUuid))}/compliance${qs ? `?${qs}` : ''}`
  return getUriWithOrg(orgslug, path)
}
