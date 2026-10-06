// MKA fork: extra headers the signup gateway (app/api/signup/route.ts) sends to
// the backend create-user endpoint OUTSIDE SaaS mode. Pure; no imports.
//
// - X-Turnstile-Token: a Turnstile token is single-use (a second siteverify
//   fails with `timeout-or-duplicate`), so outside SaaS the gateway does NOT
//   verify it; the API verifies it once (apps/api/src/services/security/
//   mka_turnstile.py). That also closes the direct-POST bypass of the API.
// - X-Forwarded-For / X-Real-IP: the gateway calls the API server-side, so
//   without these the API sees the gateway hop (not the member) as the client
//   and the per-IP signup limit becomes one shared bucket. They are copied
//   VERBATIM from the incoming request (as set by the container nginx), so the
//   API's get_client_ip sees exactly what it sees on a direct request.
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

// --- Loopback call to the API (non-SaaS) -------------------------------------
//
// getServerAPIUrl() resolves to the PUBLIC API URL on MKA (NEXT_PUBLIC_LEARNHOUSE_API_URL),
// so the gateway's server-side fetch left the container and came back through
// the edge (Traefik -> nginx -> API). The API then saw the edge hop, not the
// member, as the client: every signup shared one rate-limit bucket. Outside
// SaaS the gateway calls the API on loopback instead (the API binds
// 0.0.0.0:LEARNHOUSE_PORT in the same container) and forwards the member's
// X-Forwarded-For itself (mkaSignupForwardHeaders).

/** Loopback API base: LEARNHOUSE_INTERNAL_API_URL, else http://127.0.0.1:<LEARNHOUSE_PORT|9000>/api/v1/. */
export function mkaInternalApiUrl(env: Record<string, string | undefined> = process.env): string {
  const explicit = env.LEARNHOUSE_INTERNAL_API_URL
  const url = explicit || `http://127.0.0.1:${env.LEARNHOUSE_PORT || '9000'}/api/v1/`
  return url.endsWith('/') ? url : `${url}/`
}

/**
 * fetch() for the signup gateway. SaaS: plain fetch(url) (upstream). Non-SaaS:
 * when `url` starts with `publicBase`, call the loopback equivalent ONLY. There
 * is deliberately no fallback to the public URL: it would silently reintroduce
 * the shared edge-IP rate-limit bucket, and a refused loopback means the API is
 * down anyway. Errors propagate to the route's existing 502 handling; there is
 * never a second request.
 */
export async function mkaSignupFetch(
  saas: boolean,
  publicBase: string,
  url: string,
  init: RequestInit,
  opts: { internalBase?: string; fetchImpl?: typeof fetch } = {},
): Promise<Response> {
  const fetchImpl = opts.fetchImpl ?? fetch
  if (saas || !url.startsWith(publicBase)) return fetchImpl(url, init)
  return fetchImpl((opts.internalBase ?? mkaInternalApiUrl()) + url.slice(publicBase.length), init)
}
