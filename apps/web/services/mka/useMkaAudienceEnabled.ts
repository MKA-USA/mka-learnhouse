'use client'
import { useEffect, useState } from 'react'
import { mkaAudienceEnabled, waitForMkaAudienceEnabled } from './flags'

/**
 * Reactive version of mkaAudienceEnabled(): turns true when `/runtime-config.js` arrives after hydration (polls
 * for a few seconds), so authoring entry points appear without re-creating the editor.
 */
export function useMkaAudienceEnabled(): boolean {
  const [on, setOn] = useState(() => mkaAudienceEnabled())
  useEffect(() => {
    if (on) return
    return waitForMkaAudienceEnabled(() => setOn(true))
  }, [on])
  return on
}
