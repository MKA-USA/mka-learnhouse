/** Safety guards shared by the CLI and probes. Staging only; never publish. */
export const STAGING_HOST = "ilm-dev.mkausa.org";
export const STAGING_API_BASE = `https://${STAGING_HOST}/api/v1`;

export class SafetyError extends Error {
  constructor(message: string) { super(message); this.name = "SafetyError"; }
}

export type TargetName = "dev" | "prod";
/** LearnHouse targets. Hostnames come from config (here), never from a flag. Each target has its own keychain token item. */
export const TARGETS = {
  dev: { host: STAGING_HOST, tokenItem: "MKA_LH_DEV_API_TOKEN", orgSlug: "default" },
  prod: { host: "ilm.mkausa.org", tokenItem: "MKA_LH_PROD_API_TOKEN", orgSlug: "default" },
} as const satisfies Record<TargetName, { host: string; tokenItem: string; orgSlug: string }>;

export interface Target { name: TargetName; host: string; apiBase: string; orgSlug: string }

/**
 * Resolve `--target` (default dev). Prod needs `--confirm-prod <exact prod hostname from config>` for ANY use (reads included),
 * so a prod run can never start by accident. The API base is always derived from config; for dev a set `LH_API_BASE` must point at the staging host
 * (for prod it is ignored: the dev value in `.env` must never redirect or block a prod run).
 * `--confirm-staging` never authorises prod.
 */
export function resolveTarget(o: { target?: string; confirmProd?: string; env?: Record<string, string | undefined> } = {}): Target {
  const name = (o.target ?? "dev") as string;
  if (name !== "dev" && name !== "prod") throw new SafetyError(`--target must be dev or prod (got "${name}")`);
  const host = TARGETS[name].host;
  if (name === "prod" && o.confirmProd !== host) throw new SafetyError(`refusing prod: pass --confirm-prod ${host} (the exact prod hostname) to use --target prod`);
  const base = `https://${host}/api/v1`;
  const fromEnv = name === "dev" ? o.env?.LH_API_BASE : undefined;
  if (fromEnv) {
    let u: URL;
    try { u = new URL(fromEnv); } catch { throw new SafetyError("LH_API_BASE is not a valid URL"); }
    if (u.protocol !== "https:" || u.hostname !== host) throw new SafetyError(`refusing: LH_API_BASE host must be ${host} for --target ${name}`);
  }
  return { name, host, apiBase: base, orgSlug: TARGETS[name].orgSlug };
}

/**
 * The token must come from the wrapper of the SAME target (it sets LH_TOKEN_TARGET): a dev token is never sent to prod and vice versa.
 * A token without that tag (supplied directly in the environment) is refused for every target.
 */
export function assertTokenTarget(t: Target, env: Record<string, string | undefined>): void {
  if (!env.LH_API_TOKEN) return;
  const from = env.LH_TOKEN_TARGET;
  if (from !== t.name) throw new SafetyError(`refusing: the API token was loaded for ${from ?? "an unknown target (no LH_TOKEN_TARGET: use bun run lh / lh:prod)"}, but --target is ${t.name}`);
}

/**
 * Write gate. Dev: `--confirm-staging`. Prod: `--confirm-prod` only SELECTS the target (resolveTarget); a write also needs an explicit `--write`,
 * otherwise a prod run is a dry run / plan only.
 */
export const writeConfirmed = (t: Target, hasConfirmStaging: boolean, hasWrite = false): boolean => (t.name === "prod" ? hasWrite : hasConfirmStaging);

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
