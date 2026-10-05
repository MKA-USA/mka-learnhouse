'use client'
import React from 'react'

type Props = {
  /** Called once when a child throws. Used to put the node view into its fail-safe mode. */
  onError?: (error: unknown) => void
  fallback?: React.ReactNode
  children: React.ReactNode
}

/**
 * Wraps every fork render path. A throw must never blank the lesson:
 *  - the section's mode controller reports to its node view, which then shows the content plainly
 *    for authoring editors and NOTHING for learners (fail-safe hide; see AudienceView.tsx);
 *  - purely visual chrome falls back to `null`.
 */
export class MkaErrorBoundary extends React.Component<Props, { failed: boolean }> {
  state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  componentDidCatch(error: unknown) {
    try {
      this.props.onError?.(error)
    } catch {
      /* ignore */
    }
    if (process.env.NODE_ENV !== 'production') console.error('[mka-audience] render failed', error)
  }

  render() {
    return this.state.failed ? (this.props.fallback ?? null) : this.props.children
  }
}
