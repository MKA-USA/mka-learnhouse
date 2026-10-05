import { loadScoped } from "@/lib/access";
import { applyFilters, parseFilters } from "@/lib/queries";
import { getViewer } from "@/lib/viewer";

export const dynamic = "force-dynamic";

/** Scoped JSON rows (same choke point as pages and CSV). */
export async function GET(req: Request): Promise<Response> {
  const viewer = await getViewer();
  if (!viewer) return Response.json({ error: "unauthorized" }, { status: 401 });
  const data = await loadScoped(viewer);
  if (!data.scopes.length) return Response.json({ error: "forbidden" }, { status: 403 });
  const sp: Record<string, string> = {};
  new URL(req.url).searchParams.forEach((v, k) => { sp[k] = v; });
  const rows = applyFilters(data.rows, parseFilters(sp)).slice(0, 500);
  return Response.json({ asOf: data.asOf, scope: data.scopeText, count: rows.length, rows }, { headers: { "Cache-Control": "private, no-store" } });
}
