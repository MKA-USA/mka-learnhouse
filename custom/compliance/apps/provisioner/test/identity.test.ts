import { afterEach, beforeEach, describe, expect, spyOn, test } from "bun:test";
import { existsSync, readFileSync, rmSync } from "node:fs";
import { join } from "node:path";
import { LhClient, SafetyError, identityStatus, syncIdentity } from "@mka/compliance-core";
import { parseArgs } from "../src/args";
import { cmdIdentityStatus, cmdSyncIdentity } from "../src/commands-push";
import { OUT_DIR } from "../src/commands-data";

const SYNC = { users_seen: 126, groups_created: 3, memberships_added: 400, memberships_removed: 0, roles_set: 20, roles_reverted: 0, errors: [], planned: [{ user: "x", op: "add_group" }] };
function mock(payload: unknown = SYNC, status = 200) {
  const seen: { method: string; path: string; query: string; auth: string | null; body: unknown }[] = [];
  const fetchFn = (async (url: string, init: RequestInit) => {
    const u = new URL(url);
    seen.push({ method: String(init.method), path: u.pathname, query: u.search, auth: (init.headers as Record<string, string>).Authorization ?? null, body: init.body ?? null });
    return new Response(JSON.stringify(payload), { status });
  }) as unknown as typeof fetch;
  return { seen, fetchFn, client: new LhClient({ baseUrl: "https://ilm-dev.mkausa.org/api/v1", token: "tok", orgSlug: "default", delayMs: 0, sleep: async () => {}, fetch: fetchFn }) };
}

describe("identity client calls", () => {
  test("dry run sends dry_run=true with org_slug and bearer", async () => {
    const { client, seen } = mock(); await syncIdentity(client, true);
    expect(seen[0]).toMatchObject({ method: "POST", path: "/api/v1/mka/identity/sync", auth: "Bearer tok", body: null });
    expect(seen[0]!.query).toContain("org_slug=default"); expect(seen[0]!.query).toContain("dry_run=true");
  });
  test("apply sends dry_run=false", async () => {
    const { client, seen } = mock(); await syncIdentity(client, false); expect(seen[0]!.query).toContain("dry_run=false");
  });
  test("status is a GET with org_slug", async () => {
    const { client, seen } = mock({ enabled: true, role_id: 7, group_count: 85, last_sync_at: null }); const r = await identityStatus(client);
    expect(r.group_count).toBe(85); expect(seen[0]).toMatchObject({ method: "GET", path: "/api/v1/mka/identity/status", query: "?org_slug=default" });
  });
});

describe("sync-identity / identity-status commands", () => {
  const env = { ...process.env }; const report = join(OUT_DIR, "sync-identity-report.json");
  let log: ReturnType<typeof spyOn>; let realFetch: typeof fetch;
  beforeEach(() => { realFetch = globalThis.fetch; log = spyOn(console, "log").mockImplementation(() => {}); process.exitCode = 0; if (existsSync(report)) rmSync(report); });
  afterEach(() => { globalThis.fetch = realFetch; log.mockRestore(); process.env = { ...env }; process.exitCode = 0; });
  const useMock = (payload?: unknown, status?: number) => { const m = mock(payload, status); globalThis.fetch = m.fetchFn; process.env.LH_API_TOKEN = "tok"; process.env.LH_API_BASE = "https://ilm-dev.mkausa.org/api/v1"; return m; };

  test("default is a dry run", async () => {
    const m = useMock(); await cmdSyncIdentity(parseArgs(["sync-identity"]));
    expect(m.seen).toHaveLength(1); expect(m.seen[0]!.query).toContain("dry_run=true");
    expect(String(log.mock.calls[0]![0])).toContain("dry run");
  });
  test("--dry-run is also a dry run", async () => {
    const m = useMock(); await cmdSyncIdentity(parseArgs(["sync-identity", "--dry-run"])); expect(m.seen[0]!.query).toContain("dry_run=true");
  });
  test("--apply without --confirm-staging is refused before any request", async () => {
    const m = useMock(); await expect(cmdSyncIdentity(parseArgs(["sync-identity", "--apply"]))).rejects.toBeInstanceOf(SafetyError); expect(m.seen).toHaveLength(0);
  });
  test("--apply with --dry-run is refused", async () => {
    const m = useMock(); await expect(cmdSyncIdentity(parseArgs(["sync-identity", "--apply", "--confirm-staging", "--dry-run"]))).rejects.toBeInstanceOf(SafetyError); expect(m.seen).toHaveLength(0);
  });
  test("refuses a non-staging host", async () => {
    const m = useMock(); process.env.LH_API_BASE = "https://ilm.mkausa.org/api/v1";
    await expect(cmdSyncIdentity(parseArgs(["sync-identity", "--apply", "--confirm-staging"]))).rejects.toBeInstanceOf(SafetyError); expect(m.seen).toHaveLength(0);
  });
  test("--apply --confirm-staging sends dry_run=false and writes the report; console shows counts only", async () => {
    const m = useMock(); await cmdSyncIdentity(parseArgs(["sync-identity", "--apply", "--confirm-staging"]));
    expect(m.seen[0]!.query).toContain("dry_run=false");
    const out = JSON.parse(readFileSync(report, "utf8")); expect(out.apply).toBe(true); expect(out.response.planned).toHaveLength(1);
    const printed = log.mock.calls.map((c: unknown[]) => String(c[0])).join("\n");
    expect(printed).toContain("users_seen 126"); expect(printed).not.toContain("add_group");
  });
  test("missing fields do not crash; errors set exit code", async () => {
    useMock({ users_seen: 1, errors: [{ user: "u", error: "boom" }], surprise: true }); await cmdSyncIdentity(parseArgs(["sync-identity"]));
    expect(process.exitCode).toBe(1); expect(existsSync(report)).toBe(true);
    expect(log.mock.calls.map((c: unknown[]) => String(c[0])).join("\n")).toContain("unexpected response shape");
  });
  test("HTTP 404 gives the explained message", async () => {
    useMock({ detail: "nope" }, 404); await expect(cmdSyncIdentity(parseArgs(["sync-identity"]))).rejects.toThrow("fork identity API not deployed");
  });
  test("identity-status refuses a non-staging host and sends nothing", async () => {
    const m = useMock(); process.env.LH_API_BASE = "https://ilm.mkausa.org/api/v1";
    await expect(cmdIdentityStatus(parseArgs(["identity-status"]))).rejects.toBeInstanceOf(SafetyError); expect(m.seen).toHaveLength(0);
  });
  test("object errors print as JSON, not [object Object]", async () => {
    useMock({ errors: { u1: "boom" } }); await cmdSyncIdentity(parseArgs(["sync-identity"]));
    const printed = log.mock.calls.map((c: unknown[]) => String(c[0])).join("\n"); expect(printed).toContain('{"u1":"boom"}'); expect(printed).not.toContain("[object Object]");
  });
  test("identity-status prints a one-line summary", async () => {
    useMock({ enabled: false, role_id: null, group_count: 0, last_sync_at: null }); await cmdIdentityStatus(parseArgs(["identity-status"]));
    expect(String(log.mock.calls[0]![0])).toContain("enabled false");
  });
});
