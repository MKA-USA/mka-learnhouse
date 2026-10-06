import { NextRequest, NextResponse } from 'next/server'
import { getServerAPIUrl } from '@services/config/config'
import { isSaaSMode, isCustomDomainRequest } from '@lib/saas'
import { verifyTurnstile, clientIpFromHeaders } from '@lib/turnstile'
import { mkaSignupFetch, mkaSignupForwardHeaders, mkaSignupResponseHeaders } from '@lib/mka-signup-proxy' // MKA fork
import { validateSignupEmail } from '@services/emails/disposableEmail'
import { addContactWithLoops, sendLoopsEvent, LOOPS_SIGNED_USERS_GROUP } from '@services/emails/loops'

// Signup gateway. Runs the anti-abuse add-ons (Turnstile, disposable-email)
// server-side BEFORE creating the account and fires the Loops marketing sync
// after — secrets never touch the client, and every add-on degrades gracefully
// when its key is unset (and only runs in SaaS mode).
//
// Account creation targets one of three backend endpoints, mirroring how the
// platform worked:
//   - org-less apex signup → POST /users/            (a standalone account, NOT
//     attached to any organization — the user creates/joins orgs later)
//   - org-subdomain signup → POST /users/{org_id}    (create + join that org)
//   - invite signup        → POST /users/{org_id}/invite/{code}
// The apex account is NOT linked to the instance default org.

interface SignupBody {
  org_id?: string | number
  org_slug?: string
  email: string
  password: string
  username: string
  first_name?: string
  last_name?: string
  bio?: string
  /** Answers to the org's admin-defined signup fields, keyed by field key. */
  custom_fields?: Record<string, unknown>
  // MKA fork
  mka_profile?: { majlis?: string; mobile?: string | null; amc_id?: string | null; tanzeem?: string | null }
  turnstileToken?: string | null
  inviteCode?: string
}

export async function POST(request: NextRequest) {
  let body: SignupBody
  try {
    body = await request.json()
  } catch {
    return NextResponse.json({ detail: 'Invalid request body' }, { status: 400 })
  }

  const {
    email,
    org_id,
    org_slug: _org_slug,
    turnstileToken,
    inviteCode,
    password,
    username,
    first_name,
    last_name,
    bio,
    custom_fields,
    mka_profile, // MKA fork
  } = body

  if (!email || !password || !username) {
    return NextResponse.json({ detail: 'Missing required fields' }, { status: 400 })
  }

  // The anti-abuse add-ons run ONLY on the SaaS deployment. On OSS/self-hosted
  // this route is a thin proxy to the backend user-create endpoint.
  const saas = await isSaaSMode()

  // MKA fork: outside SaaS the API verifies the single-use Turnstile token (forwarded by mkaSignupForwardHeaders below).

  if (saas) {
    // 1. Turnstile — allowed through automatically when no secret is set. Skipped
    // on org custom domains: the hostname-locked widget can't render there, so the
    // client sends no token and the challenge is disabled end-to-end (matches the
    // client widget + the /api/turnstile/verify route).
    if (!(await isCustomDomainRequest())) {
      const turnstile = await verifyTurnstile(turnstileToken, clientIpFromHeaders(request.headers))
      if (!turnstile.ok) {
        const detail =
          turnstile.reason === 'missing_token'
            ? 'Please complete the verification challenge.'
            : 'Verification failed. Please try again.'
        return NextResponse.json({ detail }, { status: 403 })
      }
    }

    // 2. Disposable-email gate — offline check + optional AbstractAPI.
    const emailCheck = await validateSignupEmail(email)
    if (!emailCheck.ok) {
      return NextResponse.json(
        { detail: 'Please use a permanent email address — temporary/disposable addresses are not allowed.' },
        { status: 400 },
      )
    }
  }

  const base = getServerAPIUrl()

  // The backend UserCreate body — account fields only; the org (if any) is in
  // the URL path, never the body.
  //
  // Every field is listed explicitly rather than spread from the request. The
  // previous `...rest` spread forwarded any key the client invented, which is
  // how an arbitrary `extra_metadata` blob could reach UserCreate. Custom field
  // answers travel in their own slot and the backend validates them against the
  // org's declared fields.
  const backendBody = {
    email,
    password,
    username,
    first_name,
    last_name,
    bio,
    ...(custom_fields ? { custom_fields } : {}),
    // MKA fork: forward only the four known profile keys (never spread client input)
    ...(mka_profile && typeof mka_profile === 'object'
      ? {
          mka_profile: {
            majlis: typeof mka_profile.majlis === 'string' ? mka_profile.majlis : undefined,
            mobile: mka_profile.mobile === null ? null : typeof mka_profile.mobile === 'string' ? mka_profile.mobile : undefined,
            amc_id: mka_profile.amc_id === null ? null : typeof mka_profile.amc_id === 'string' ? mka_profile.amc_id : undefined,
            tanzeem: mka_profile.tanzeem === null ? null : typeof mka_profile.tanzeem === 'string' ? mka_profile.tanzeem : undefined,
          },
        }
      : {}),
  }

  let url: string
  if (inviteCode) {
    if (!org_id) {
      return NextResponse.json({ detail: 'Invite signups require an organization.' }, { status: 400 })
    }
    url = `${base}users/${org_id}/invite/${encodeURIComponent(inviteCode)}`
  } else if (org_id) {
    // Org subdomain: create the account and join that org.
    url = `${base}users/${org_id}`
  } else {
    // Org-less apex: create a standalone account (POST /users/), unattached to
    // any org — exactly like the platform. The user creates their org next.
    url = `${base}users/`
  }

  let backendRes: Response
  try {
    backendRes = await mkaSignupFetch(saas, base, url, { // MKA fork: non-SaaS calls the API on loopback
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...mkaSignupForwardHeaders(saas, request.headers, turnstileToken) }, // MKA fork
      body: JSON.stringify(backendBody),
      signal: AbortSignal.timeout(8000),
    })
  } catch (err) {
    console.error('[signup] backend request failed:', err)
    return NextResponse.json({ detail: 'Could not reach the signup service. Please try again.' }, { status: 502 })
  }

  const data = await backendRes.json().catch(() => ({}))

  // On success, sync the marketing contact (SaaS-only, fire-and-forget) — but
  // ONLY for ORG-LESS signups (learnhouse.io self-serve prospects). Members
  // signing up INTO an existing org (org_id present) are that org's learners,
  // not people we market to, so they are not added. Org admins are recorded
  // separately when they create/administer an org (see /api/loops/admin).
  if (backendRes.ok && saas && !org_id) {
    void addContactWithLoops(email, LOOPS_SIGNED_USERS_GROUP, {
      firstName: first_name || '',
      lastName: last_name || '',
    }).catch(() => {})
    void sendLoopsEvent(email, 'user_signed_up', {
      username,
      has_org: false,
    }).catch(() => {})
  }

  return NextResponse.json(data, { status: backendRes.status, headers: mkaSignupResponseHeaders(backendRes.headers) }) // MKA fork: pass Retry-After through
}
