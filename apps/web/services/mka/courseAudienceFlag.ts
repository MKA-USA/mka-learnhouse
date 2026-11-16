// MKA fork — flag for the per-course Audience panel (NEXT_PUBLIC_MKA_COURSE_AUDIENCE_ENABLED=1).
// Same runtime-config mechanics as flags.ts: window.__RUNTIME_CONFIG__ wins on the client, build-time value is the
// fallback, server reads through a variable key so it is looked up at runtime.
import { useEffect, useState } from 'react'

const VAR = 'NEXT_PUBLIC_MKA_COURSE_AUDIENCE_ENABLED'

export function mkaCourseAudienceEnabled(): boolean {
  if (typeof window !== 'undefined') {
    const runtime = (window as unknown as { __RUNTIME_CONFIG__?: Record<string, unknown> }).__RUNTIME_CONFIG__
    if (runtime && runtime[VAR] !== undefined) return runtime[VAR] === '1'
    return process.env.NEXT_PUBLIC_MKA_COURSE_AUDIENCE_ENABLED === '1'
  }
  return process.env[VAR] === '1'
}

/** Reactive: polls briefly because /runtime-config.js can execute after hydration. */
export function useMkaCourseAudienceEnabled(): boolean {
  const [on, setOn] = useState(() => mkaCourseAudienceEnabled())
  useEffect(() => {
    if (on) return
    const deadline = Date.now() + 5000
    const id = setInterval(() => {
      if (mkaCourseAudienceEnabled()) {
        clearInterval(id)
        setOn(true)
      } else if (Date.now() >= deadline) clearInterval(id)
    }, 150)
    return () => clearInterval(id)
  }, [on])
  return on
}
