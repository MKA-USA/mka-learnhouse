import { getCycleRow, type Db } from "@mka/compliance-core";
import type { Args } from "./args";

/** Defaults for known labels only (MKA year starts Nov 1; 2026-27 deadline Dec 1). Real values live in the cycle table; flags override. */
export const CYCLES: Record<string, { startsOn: string; deadlineOn: string }> = {
  "2025-26": { startsOn: "2025-11-01", deadlineOn: "2025-12-01" },
  "2026-27": { startsOn: "2026-11-01", deadlineOn: "2026-12-01" },
};
export const DEFAULT_CYCLE = "2026-27";
export interface CycleDef { label: string; startsOn: string; deadlineOn: string; fromFlags: boolean }
const ISO = /^\d{4}-\d{2}-\d{2}$/;

/** Precedence: --starts-on/--deadline-on flags > cycle table row > built-in default for known labels > error. */
export function resolveDates(label: string, flags: { startsOn?: string; deadlineOn?: string }, row: { startsOn: string; deadlineOn: string } | null) {
  const d = CYCLES[label];
  return { startsOn: flags.startsOn ?? row?.startsOn ?? d?.startsOn, deadlineOn: flags.deadlineOn ?? row?.deadlineOn ?? d?.deadlineOn };
}
export async function loadCycleDef(db: Db, label: string, a?: Args): Promise<CycleDef> {
  const row = await getCycleRow(db, label);
  const { startsOn, deadlineOn } = resolveDates(label, { startsOn: a?.str("starts-on"), deadlineOn: a?.str("deadline-on") }, row);
  if (!startsOn || !deadlineOn) throw new Error(`cycle ${label} has no dates: pass --starts-on YYYY-MM-DD --deadline-on YYYY-MM-DD`);
  if (!ISO.test(startsOn) || !ISO.test(deadlineOn)) throw new Error("dates must be YYYY-MM-DD");
  if (startsOn > deadlineOn) throw new Error("starts-on must not be after deadline-on");
  return { label, startsOn, deadlineOn, fromFlags: !!(a?.has("starts-on") || a?.has("deadline-on")) };
}
