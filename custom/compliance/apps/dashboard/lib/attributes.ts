import type { ViewerAttributes } from "@mka/analytics/scope";
import { env } from "@/lib/env";
import { personaByKey } from "@/lib/personas";

/**
 * Viewer attributes from the fork (companion spec A3/A7). Fail-closed: any error or unknown shape -> null (no scope).
 * Contract UNVERIFIED until W1a ships: the path is configurable (ATTRIBUTES_LIST_PATH) and the parser tolerates
 * `[row]`, `{items:[row]}` and rows with fields either at top level or under `attributes`/`effective`.
 */
export function parseAttributesResponse(body: unknown, email: string): ViewerAttributes | null {
  const list = Array.isArray(body) ? body : Array.isArray((body as { items?: unknown })?.items) ? (body as { items: unknown[] }).items : [];
  const want = email.trim().toLowerCase();
  for (const raw of list) {
    const row = raw as Record<string, unknown>;
    if (String(row?.email ?? "").trim().toLowerCase() !== want) continue;
    const src = (row.effective ?? row.attributes ?? row) as Record<string, unknown>;
    const s = (k: string) => (typeof src[k] === "string" && src[k] ? (src[k] as string) : null);
    const status = s("status");
    if (!status || !["matched", "partial", "ambiguous", "unrecognized", "not_applicable"].includes(status)) return null;
    return {
      status: status as ViewerAttributes["status"], is_officeholder: typeof src.is_officeholder === "boolean" ? src.is_officeholder : null,
      level: (s("level") as ViewerAttributes["level"]) ?? null, department: s("department"), role: s("role"), majlis: s("majlis"), region: s("region"),
    };
  }
  return null;
}

export async function getViewerAttributes(email: string, devPersona?: string): Promise<ViewerAttributes | null> {
  if (env.fixtureMode()) return personaByKey(devPersona)?.attributes ?? null;
  const base = process.env.LH_API_BASE, token = process.env.LH_API_TOKEN;
  if (!base || !token) return null;
  try {
    const path = process.env.ATTRIBUTES_LIST_PATH || "/mka/attributes/admin/list";
    const res = await fetch(`${base.replace(/\/+$/, "")}${path}?q=${encodeURIComponent(email)}`, { headers: { Authorization: `Bearer ${token}` }, cache: "no-store", signal: AbortSignal.timeout(8000) });
    if (!res.ok) return null;
    return parseAttributesResponse(await res.json(), email);
  } catch { return null; }
}
