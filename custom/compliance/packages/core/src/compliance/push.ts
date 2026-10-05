import type { LhClient } from "../lh/client";
import type { CyclePayload, ExpectedRowPayload } from "./payload";

export interface CycleResponse { cycle: { id: number; label: string; starts_on: string; deadline_on: string; action: string }; courses: { row: number; course_uuid: string | null; ok: boolean; action?: string; error?: string }[]; ok: number; failed: number }
export interface ExpectedResponse { cycle_id: number; received: number; created: number; updated: number; unchanged: number; failed: number; errors: { row: number; error: string }[]; dry_run: boolean; departments_without_course: string[] }

/** Org API token + `org_slug` query (routers/mka_compliance.py::_resolve_admin). Base is the same /api/v1. */
export const pushCycle = (c: LhClient, p: CyclePayload) => c.post<CycleResponse>("/mka/compliance/cycles", p, { org_slug: c.orgSlug });
export const pushExpected = (c: LhClient, cycleLabel: string, rows: ExpectedRowPayload[], dryRun: boolean) =>
  c.post<ExpectedResponse>("/mka/compliance/expected/import", { cycle: cycleLabel, rows, dry_run: dryRun }, { org_slug: c.orgSlug });
