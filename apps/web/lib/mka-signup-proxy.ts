// MKA fork: extra headers the signup gateway (app/api/signup/route.ts) sends to
// the backend create-user endpoint OUTSIDE SaaS mode. Pure; no imports.
//
// - X-Turnstile-Token: a Turnstile token is single-use (a second siteverify
//   fails with `timeout-or-duplicate`), so outside SaaS the gateway does NOT
//   verify it; the API verifies it once (apps/api/src/services/security/
//   mka_turnstile.py). That also closes the direct-POST bypass of the API.
// - X-Forwarded-For / X-Real-IP: the gateway calls the API server-side from
//   inside the container, so without these the API sees 127.0.0.1 for every
//   signup and the per-IP signup limit becomes one shared bucket. They are
//   copied VERBATIM from the incoming request (as set by the container nginx),
//   so the API's get_client_ip sees exactly what it sees on a direct request.
//
// SaaS mode returns {} so the request is byte-identical to upstream.

const MAX_TOKEN_LENGTH = 2048
const SAFE_TOKEN = /^[\x21-\x7e]+$/

export function mkaSignupForwardHeaders(
  saas: boolean,
  incoming: Headers,
  turnstileToken: unknown,
): Record<string, string> {
  if (saas) return {}
  const out: Record<string, string> = {}
  if (turnstileToken !== null && turnstileToken !== undefined && turnstileToken !== '') {
    const valid =
      typeof turnstileToken === 'string' &&
      turnstileToken.length <= MAX_TOKEN_LENGTH &&
      SAFE_TOKEN.test(turnstileToken)
    // An unusable token still reaches the API as a (failing) token, so the
    // user sees "Verification failed" rather than a proxy error.
    out['X-Turnstile-Token'] = valid ? (turnstileToken as string) : 'invalid'
  }
  const xff = incoming.get('x-forwarded-for')
  if (xff) out['X-Forwarded-For'] = xff
  const realIp = incoming.get('x-real-ip')
  if (realIp) out['X-Real-IP'] = realIp
  return out
}
