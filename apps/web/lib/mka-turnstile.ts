// MKA fork: run Cloudflare Turnstile when its keys are configured, WITHOUT
// LearnHouse's SaaS deployment mode (SaaS mode would impose free-plan limits,
// email verification and hide Google SSO on the MKA org). Pure functions take
// explicit inputs so they are unit-testable; no imports so it is client-safe.
//
// SaaS mode behaves EXACTLY like upstream: every fork rule is inactive when
// mode === 'saas' and the upstream code paths handle it unchanged (including
// the custom-domain exclusion).
//
// Non-SaaS rules:
//  - client (widget): active when the public site key is non-empty.
//  - server: enforced only when BOTH TURNSTILE_SECRET_KEY and the site key are
//    set. Requiring both prevents the lockout where only the secret is set, the
//    widget never renders, and every signup 403s "missing_token".
//  - the custom-domain exclusion is deliberately NOT applied outside SaaS: it
//    can be true for a single-org deployment's own host and would silently
//    disable protection. The Cloudflare widget is hostname-bound, so the
//    operator must list the site hostname(s) there.
//
// Upstream's verifyTurnstile() still FAILS OPEN on Cloudflare/network errors
// (lib/turnstile.ts, unchanged).

/** The fork rules apply only outside SaaS mode (SaaS is handled by upstream). */
export function isMkaTurnstileApplicable(mode: string): boolean {
  return mode !== 'saas'
}

/** Client rule: widget active iff not SaaS and a site key is configured. */
export function mkaTurnstileActiveFor(opts: { mode: string; siteKey?: string | null }): boolean {
  return isMkaTurnstileApplicable(opts.mode) && Boolean(opts.siteKey && opts.siteKey.length > 0)
}

/** Server rule: enforce iff not SaaS and BOTH the secret and the site key are set. */
export function mkaTurnstileEnforcedFor(opts: {
  mode: string
  siteKey?: string | null
  secretKey?: string | null
}): boolean {
  return mkaTurnstileActiveFor(opts) && Boolean(opts.secretKey && opts.secretKey.length > 0)
}

// Read through a variable key so Next/webpack cannot inline the value at build
// time (it inlines literal `process.env.NEXT_PUBLIC_*`). server-wrapper.js copies
// NEXT_PUBLIC_* container env into process.env at start, so a key change needs
// only a restart.
const SITE_KEY_VAR = 'NEXT_PUBLIC_TURNSTILE_SITE_KEY'

/** Thin server wrapper over process.env. `mode` is 'saas' or anything else. */
export function isMkaTurnstileEnforced(mode: string): boolean {
  return mkaTurnstileEnforcedFor({
    mode,
    siteKey: process.env[SITE_KEY_VAR],
    secretKey: process.env.TURNSTILE_SECRET_KEY,
  })
}
