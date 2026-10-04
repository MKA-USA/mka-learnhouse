// MKA fork: Turnstile activation rules that do NOT depend on LearnHouse's SaaS
// deployment mode (SaaS mode would impose free-plan limits, email verification
// and hide Google SSO on the MKA org). Pure functions take explicit inputs so
// they are unit-testable; no imports so it is safe on both client and server.
//
// Rules:
//  - client (widget): active when the public site key is non-empty.
//  - server (verification): enforced only when BOTH TURNSTILE_SECRET_KEY and the
//    site key are set. Requiring both prevents the lockout where only the secret
//    is set, the widget never renders, and every signup 403s "missing_token".
//
// Custom-domain exclusion is intentionally NOT applied: upstream's
// isCustomDomainRequest()/LH_custom_domain can be true for a single-org
// deployment's own host, which would silently disable protection. The Cloudflare
// widget is hostname-bound, so the operator must list the site hostname(s) there.
//
// Upstream's verifyTurnstile() still FAILS OPEN on Cloudflare/network errors
// (lib/turnstile.ts, unchanged).

/** Client rule: widget is active iff a site key is configured. */
export function isTurnstileActive(siteKey: string | undefined | null): boolean {
  return Boolean(siteKey && siteKey.length > 0)
}

/** Server rule: enforce only when both the secret and the site key are set. */
export function isTurnstileEnforced(
  secretKey: string | undefined | null,
  siteKey: string | undefined | null,
): boolean {
  return Boolean(secretKey && secretKey.length > 0) && isTurnstileActive(siteKey)
}

/**
 * Thin server wrapper over process.env. server-wrapper.js copies every
 * NEXT_PUBLIC_* container env var into process.env at start, so the site key is
 * readable server-side at runtime.
 */
export function isMkaTurnstileEnforced(): boolean {
  return isTurnstileEnforced(
    process.env.TURNSTILE_SECRET_KEY,
    process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY,
  )
}
