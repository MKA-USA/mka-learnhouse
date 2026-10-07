import type { LhClient } from "../lh/client";

/** Contract of POST /mka/identity/sync and GET /mka/identity/status (spec 2026-10-07 section 3.A4). Every field is optional: print what came back, never crash. */
export interface IdentitySyncResponse {
  users_seen?: number; groups_created?: number; memberships_added?: number; memberships_removed?: number;
  roles_set?: number; roles_reverted?: number; errors?: unknown; planned?: unknown[];
}
export interface IdentityStatusResponse { enabled?: boolean; role_id?: number | null; group_count?: number; last_sync_at?: string | null }

/** Org API token + `org_slug` query, same style as pushCycle/pushExpected. `dry_run` is sent explicitly on every call. */
export const syncIdentity = (c: LhClient, dryRun: boolean) =>
  c.post<IdentitySyncResponse>("/mka/identity/sync", undefined, { org_slug: c.orgSlug, dry_run: dryRun ? "true" : "false" });
export const identityStatus = (c: LhClient) => c.get<IdentityStatusResponse>("/mka/identity/status", { org_slug: c.orgSlug });
