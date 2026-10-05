/** Safety guards shared by the CLI and probes. Staging only; never publish. */
export const STAGING_HOST = "ilm-dev.mkausa.org";
export const STAGING_API_BASE = `https://${STAGING_HOST}/api/v1`;

export class SafetyError extends Error {
  constructor(message: string) { super(message); this.name = "SafetyError"; }
}

/** Throws unless the base URL is exactly the staging host over https. */
export function assertStaging(base: string | undefined): URL {
  let u: URL;
  try { u = new URL(base ?? ""); } catch { throw new SafetyError("LH_API_BASE is not a valid URL"); }
  if (u.protocol !== "https:" || u.hostname !== STAGING_HOST) {
    throw new SafetyError(`refusing: LH_API_BASE host must be ${STAGING_HOST} (staging only)`);
  }
  return u;
}

/** Throws if a payload tries to publish anything. */
export function assertDraftOnly(body: unknown): void {
  const b = body as { published?: unknown } | null;
  if (b && typeof b === "object" && b.published === true) throw new SafetyError("refusing: payload sets published=true (drafts only)");
}
