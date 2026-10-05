// MKA fork — flags for the Audience block.

const ENABLED_VAR = 'NEXT_PUBLIC_MKA_AUDIENCE_ENABLED'

/**
 * Gates ONLY authoring entry points (slash items, shortcut, Preview button, bar outside a preview). Evaluation of
 * existing sections is never gated (contract 3.4).
 *
 * Runtime-configurable. ilm-dev sets env in Coolify at RUNTIME, not at build time, and Next inlines a literal
 * `process.env.NEXT_PUBLIC_*` at BUILD time, so:
 *  - client: `window.__RUNTIME_CONFIG__` (injected by server-wrapper.js via /runtime-config.js, which can execute AFTER
 *    hydration; see waitForMkaAudienceEnabled / useMkaAudienceEnabled) wins when it carries the variable; otherwise
 *    the build-time value is the fallback (dev, tests, builds that did set it);
 *  - server: read through a variable key so it is looked up at runtime and not inlined (same trick as
 *    lib/mka-turnstile.ts).
 */
export function mkaAudienceEnabled(): boolean {
  if (typeof window !== 'undefined') {
    const runtime = (window as unknown as { __RUNTIME_CONFIG__?: Record<string, unknown> }).__RUNTIME_CONFIG__
    if (runtime && runtime[ENABLED_VAR] !== undefined) return runtime[ENABLED_VAR] === '1'
    return process.env.NEXT_PUBLIC_MKA_AUDIENCE_ENABLED === '1' // build-time fallback
  }
  return process.env[ENABLED_VAR] === '1'
}

/**
 * Dev/screenshot mock layer. Build-time ONLY and hard-off in production: it must never become enable-able at
 * runtime (a runtime-config value for it is deliberately ignored).
 */
export const mkaAudienceMock = (): boolean =>
  process.env.NEXT_PUBLIC_MKA_AUDIENCE_MOCK === '1' && process.env.NODE_ENV !== 'production'

/**
 * Calls `cb` once, as soon as the flag is on: immediately if it already is, otherwise by polling (default every
 * 150 ms for up to 5 s) to cover `/runtime-config.js` executing after hydration. Returns a cancel function.
 */
export function waitForMkaAudienceEnabled(cb: () => void, opts: { intervalMs?: number; maxMs?: number; onGiveUp?: () => void } = {}): () => void {
  if (mkaAudienceEnabled()) {
    cb()
    return () => {}
  }
  const interval = opts.intervalMs ?? 150
  const deadline = Date.now() + (opts.maxMs ?? 5000)
  const id = setInterval(() => {
    if (mkaAudienceEnabled()) {
      clearInterval(id)
      cb()
    } else if (Date.now() >= deadline) {
      clearInterval(id)
      opts.onGiveUp?.()
    }
  }, interval)
  return () => clearInterval(id)
}
