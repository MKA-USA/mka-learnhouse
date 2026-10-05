import Link from "next/link";
import { RagBadge } from "@/components/RagBadge";
import { Sparkline } from "@/components/Sparkline";
import { TrendText } from "@/components/TrendText";
import { pct } from "@/lib/format";
import type { GroupRow } from "@/lib/queries";

/** Ranked "who needs attention" list. Reasons are plain sentences, never a bare score. */
export function AttentionList({ items, hrefFor, limit, empty = "Nothing to chase." }: { items: GroupRow[]; hrefFor: (key: string) => string; limit?: number; empty?: string }) {
  const shown = (limit ? items.slice(0, limit) : items).filter((i) => i.att.rag !== "none");
  if (!shown.length) return <p className="text-sm text-muted">{empty}</p>;
  return (
    <ol className="divide-y divide-border rounded-2xl border border-border bg-surface">
      {shown.map((i, n) => (
        <li key={i.key} className="grid gap-2 p-4 sm:grid-cols-[2rem_1fr_auto] sm:items-center">
          <span className="hidden text-sm tabular-nums text-muted sm:block" aria-hidden="true">{n + 1}</span>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <Link href={hrefFor(i.key)} className="font-medium underline-offset-2 hover:underline">{i.label}</Link>
              <RagBadge rag={i.att.rag} />
            </div>
            <p className="mt-1 text-sm">{i.att.summary}</p>
            <p className="mt-0.5 text-xs text-muted">{i.agg.expected} officeholders · signed off {pct(i.agg.attestedPct)} · <TrendText trend={i.trend} span="last week" /></p>
          </div>
          <Sparkline series={i.series} />
        </li>
      ))}
    </ol>
  );
}
