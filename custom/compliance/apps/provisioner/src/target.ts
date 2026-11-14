import { assertTokenTarget, resolveTarget, writeConfirmed, type Target } from "@mka/compliance-core";
import type { Args } from "./args";

/** Commands that talk to LearnHouse, the fork API or the course_map: they need a resolved target. */
export const TARGET_COMMANDS = new Set(["plan", "apply", "reconcile", "publish", "export-courses", "push-cycle", "push-roster", "assign-authors", "sync-identity", "identity-status"]);

let current: Target | null = null;

/** `--target dev|prod` (default dev). Prod needs `--confirm-prod <exact prod hostname>`; the token must come from the same target's wrapper. */
export function initTarget(a: Args, env: Record<string, string | undefined> = process.env): Target {
  current = resolveTarget({ target: a.str("target"), confirmProd: a.str("confirm-prod"), env });
  assertTokenTarget(current, env);
  return current;
}
/** The resolved target (dev when the CLI did not resolve one). LH_API_BASE is re-validated on every call so a later env change cannot redirect a run. */
export const currentTarget = (): Target =>
  current ? resolveTarget({ target: current.name, confirmProd: current.name === "prod" ? current.host : undefined, env: process.env }) : resolveTarget({ env: process.env });
/** Write gate: dev needs `--confirm-staging`; prod needs an explicit `--write` on top of `--confirm-prod` (which only selects the target). */
export const writeOk = (a: Args): boolean => writeConfirmed(currentTarget(), a.has("confirm-staging"), a.has("write"));
export const confirmHint = (): string => (currentTarget().name === "prod" ? `--write (prod writes need it on top of --confirm-prod ${currentTarget().host})` : "--confirm-staging");
/** Prod artefacts never share a folder with dev's (out/prod/...). */
/** Org slug comes from the target config (prod never from .env); dev may still be overridden by LH_ORG_SLUG. */
export const orgSlug = (): string => (currentTarget().name === "prod" ? currentTarget().orgSlug : process.env.LH_ORG_SLUG || currentTarget().orgSlug);
export const outSubdir = (): string => (currentTarget().name === "prod" ? "prod" : "");
