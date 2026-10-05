import { loadScoped } from "@/lib/access";
import { chaseCsvFor, parseFilters } from "@/lib/queries";
import { getViewer } from "@/lib/viewer";

export const dynamic = "force-dynamic";

/** Chase-list CSV. Scope is applied by loadScoped() exactly like the pages; query filters can only narrow it. */
export async function GET(req: Request): Promise<Response> {
  const viewer = await getViewer();
  if (!viewer) return new Response("Unauthorized", { status: 401 });
  const data = await loadScoped(viewer);
  if (!data.scopes.length) return new Response("Forbidden", { status: 403 });
  const url = new URL(req.url);
  const sp: Record<string, string> = {};
  url.searchParams.forEach((v, k) => { sp[k] = v; });
  const csv = chaseCsvFor(data, parseFilters(sp));
  return new Response(csv, { headers: { "Content-Type": "text/csv; charset=utf-8", "Content-Disposition": `attachment; filename="chase-list-${data.asOf}.csv"`, "Cache-Control": "private, no-store" } });
}
