import { resolveConfig, type ProvisionConfig } from "@mka/compliance-core";
import type { Args } from "./args";

/** The one place the CLI derives the cycle's department scope: Atfal is excluded by default (core/config.ts); `--include-atfal` switches it back on. */
export function configFrom(a: Args): ProvisionConfig { return resolveConfig({ includeAtfal: a.has("include-atfal") }); }

/** Fails fast when a command explicitly asks for an excluded department. */
export function assertNotExcluded(slugs: string[] | undefined, cfg: ProvisionConfig) {
  const bad = (slugs ?? []).filter((s) => cfg.excludedDepartments.includes(s));
  if (bad.length) throw new Error(`department(s) excluded by config: ${bad.join(", ")}. Pass --include-atfal to include Atfal.`);
}
