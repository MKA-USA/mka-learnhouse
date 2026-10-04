import { getAPIUrl } from '@services/config/config'
import { RequestBodyWithAuthHeader } from '@services/utils/ts/requests'

export type MkaProfileValues = {
  majlis: string
  mobile: string
  amc_id: string
  tanzeem: string
}

export type MkaProfileFieldErrors = Partial<Record<keyof MkaProfileValues, string>>

export type MkaOptions = {
  majlis: { name: string; region: string }[]
  tanzeem: { value: string; label: string }[]
}

export type MkaProfileStatus =
  | { complete: false }
  | {
      complete: true
      majlis: string
      region: string
      mobile: string | null
      amc_id: string | null
      tanzeem: string | null
    }

export const emptyMkaProfile: MkaProfileValues = {
  majlis: '',
  mobile: '',
  amc_id: '',
  tanzeem: '',
}

export class MkaProfileError extends Error {
  status: number
  fields: MkaProfileFieldErrors
  constructor(status: number, message: string, fields: MkaProfileFieldErrors = {}) {
    super(message)
    this.status = status
    this.fields = fields
  }
}

const US_MOBILE = /^(?:\+?1)?([2-9]\d{2})([2-9]\d{2})(\d{4})$/

export function validateMkaProfile(v: MkaProfileValues): MkaProfileFieldErrors {
  const errors: MkaProfileFieldErrors = {}
  if (!v.majlis.trim()) errors.majlis = 'Majlis is required'
  const mobile = v.mobile.trim()
  if (mobile) {
    if (/[A-Za-z]/.test(mobile) || !US_MOBILE.test(mobile.replace(/[\s().-]/g, ''))) {
      errors.mobile = 'Enter a valid US mobile number'
    }
  }
  const amc = v.amc_id.trim()
  if (amc && !/^[0-9]{1,15}$/.test(amc)) errors.amc_id = 'AMC ID must contain digits only'
  return errors
}

/** Body for the API: empty optional strings become null. Never includes region. */
export function mkaValuesToBody(v: MkaProfileValues) {
  return {
    majlis: v.majlis.trim(),
    mobile: v.mobile.trim() || null,
    amc_id: v.amc_id.trim() || null,
    tanzeem: v.tanzeem.trim() || null,
  }
}

type ErrorDetailItem = {
  field?: string
  message?: unknown
  loc?: unknown[]
  msg?: unknown
}

async function parseError(res: Response): Promise<MkaProfileError> {
  let detail: unknown = null
  try {
    const body: unknown = await res.json()
    detail = (body as { detail?: unknown } | null)?.detail
  } catch {
    /* non-JSON body */
  }
  const fields: MkaProfileFieldErrors = {}
  let message = 'Something went wrong. Please try again.'
  if (typeof detail === 'string') {
    message = detail
    if (res.status === 409) fields.amc_id = detail
  } else if (Array.isArray(detail)) {
    for (const d of detail as ErrorDetailItem[]) {
      // our own {field, message} items, or FastAPI's {loc, msg}
      const field = (d.field ??
        (Array.isArray(d.loc) ? String(d.loc[d.loc.length - 1]) : '')) as
        | keyof MkaProfileValues
        | ''
      const msg = String(d.message ?? d.msg ?? '').replace(/^Value error, /, '')
      if (field && msg) fields[field] = msg
    }
    message = Object.values(fields)[0] ?? message
  }
  return new MkaProfileError(res.status, message, fields)
}

export async function getMkaOptions(): Promise<MkaOptions> {
  const res = await fetch(`${getAPIUrl()}mka/profile/options`)
  if (!res.ok) throw await parseError(res)
  return res.json()
}

export async function getMyMkaProfile(token: string): Promise<MkaProfileStatus> {
  const res = await fetch(
    `${getAPIUrl()}mka/profile/me`,
    RequestBodyWithAuthHeader('GET', null, null, token)
  )
  if (!res.ok) throw await parseError(res)
  return res.json()
}

export async function putMyMkaProfile(
  values: MkaProfileValues,
  token: string
): Promise<MkaProfileStatus> {
  const res = await fetch(
    `${getAPIUrl()}mka/profile/me`,
    RequestBodyWithAuthHeader('PUT', mkaValuesToBody(values), null, token)
  )
  if (!res.ok) throw await parseError(res)
  return res.json()
}
