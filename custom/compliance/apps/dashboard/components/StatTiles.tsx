import type { Aggregate } from "@mka/analytics/pure";
import { pct } from "@/lib/format";

function Tile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-2xl border border-border bg-surface p-4">
      <dt className="text-xs uppercase tracking-wide text-muted">{label}</dt>
      <dd className="mt-1 text-2xl font-semibold tabular-nums">{value}</dd>
      {sub ? <p className="mt-0.5 text-xs text-muted">{sub}</p> : null}
    </div>
  );
}

export function StatTiles({ agg }: { agg: Aggregate }) {
  return (
    <dl className="grid grid-cols-2 gap-3 lg:grid-cols-5">
      <Tile label="Officeholders" value={String(agg.expected)} sub="on the roster" />
      <Tile label="Started" value={pct(agg.startedPct)} sub={`${agg.notStarted} not started`} />
      <Tile label="Signed off" value={pct(agg.attestedPct)} sub={`${pct(agg.expectedAttestedPct)} expected by now`} />
      <Tile label="Overdue" value={String(agg.overdue)} sub={agg.overdue ? "need a nudge" : "none"} />
      <Tile label="Contact mismatches" value={String(agg.selfCheckMismatches)} sub={`${agg.selfCheckMismatchedPeople} people`} />
    </dl>
  );
}
