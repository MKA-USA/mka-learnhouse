import { Link as HLink } from "@heroui/react";
import type { Filters } from "@/lib/queries";

/** Plain link to the scoped CSV route (server enforces scope again; filters here only narrow). */
export function ChaseButton({ filters, label = "Download chase list (CSV)" }: { filters: Filters; label?: string }) {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(filters)) if (v !== undefined) p.set(k, k === "region" && v === "" ? "_national" : k === "dept" && v === "" ? "executive" : v);
  return <HLink href={`/api/chase${p.size ? `?${p}` : ""}`} download className="rounded-lg border border-border px-3 py-1.5 text-sm font-medium">{label}</HLink>;
}
