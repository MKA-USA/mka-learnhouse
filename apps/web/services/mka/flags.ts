// MKA fork — build-time flags for the Audience block. Functions (not module constants) so tests can flip env.
/** Gates ONLY authoring entry points (slash items, shortcut, bar). Evaluation is always on (contract §3.4). */
export const mkaAudienceEnabled = (): boolean => process.env.NEXT_PUBLIC_MKA_AUDIENCE_ENABLED === '1'

/** Dev/screenshot mock layer; hard-disabled in production builds. */
export const mkaAudienceMock = (): boolean =>
  process.env.NEXT_PUBLIC_MKA_AUDIENCE_MOCK === '1' && process.env.NODE_ENV !== 'production'
