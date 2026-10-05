import { writeFileSync, mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname } from "node:path";
import { LhApi, LhClient } from "@mka/compliance-core/lh";
import { renderMatrix, runProbe } from "./probe-lib";

const STAGING = "https://ilm-dev.mkausa.org/api/v1";
const base = process.env.LH_API_BASE ?? STAGING;
if (!base.includes("ilm-dev.mkausa.org")) {
  console.error("probe is staging-only (ilm-dev.mkausa.org); refusing LH_API_BASE.");
  process.exit(2);
}
if (!process.env.LH_API_TOKEN) { console.error("LH_API_TOKEN missing; run via `bun run probe` (keychain wrapper)."); process.exit(2); }

const candidates = process.env.LH_ORG_SLUG ? [process.env.LH_ORG_SLUG] : ["default", "mka", "mkausa", "ilm", "learnhouse"];
const client = LhClient.fromEnv({ ...process.env, LH_API_BASE: base, LH_ORG_SLUG: candidates[0] }, { delayMs: 1000, maxRetries: 1 });
const { rows, orgSlug, orgId, stoppedReason } = await runProbe(new LhApi(client), candidates);

const table = renderMatrix(rows);
const md = [
  "# LearnHouse staging probe report", "",
  `Target: ${base} (read-only GET requests only). Generated: ${new Date().toISOString()}`,
  `Org slug accepted: ${orgSlug ?? "none"} | org_id: ${orgId ?? "unknown"}`,
  stoppedReason ? `\n**Stopped:** ${stoppedReason}` : "", "",
  "No token values, user identities or response bodies are recorded; counts only.", "", table, "",
].join("\n");
const out = fileURLToPath(new URL("../../../docs/probe-report.md", import.meta.url));
mkdirSync(dirname(out), { recursive: true });
writeFileSync(out, md);
console.log(md);
if (stoppedReason) process.exit(1);
