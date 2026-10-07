import type { Aggregate } from "@mka/analytics/pure";
import { pct } from "@/lib/format";

function Tile({ label, value, sub, tooltip }: { label: string; value: string; sub?: string; tooltip?: string }) {
  return (
    <div className="rounded-2xl border border-border bg-surface p-4">
      <dt className="text-xs uppercase tracking-wide text-muted">
        {label}
        {tooltip ? (
          <span className="ml-1 inline-block cursor-help" title={tooltip} aria-label={`${label}: ${tooltip}`}>
            <svg className="inline h-3 w-3 text-muted" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M8 1a7 7 0 1 0 0 14A7 7 0 0 0 8 1Zm0 12.5a5.5 5.5 0 1 1 0-11 5.5 5.5 0 0 1 0 11ZM7.25 5h1.5v1.5h-1.5V5Zm0 2.5h1.5v3.5h-1.5V7.5Z"/></svg>
          </span>
        ) : null}
      </dt>
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
      <Tile label="Signed off" value={pct(agg.attestedPct)} sub={`${pct(agg.expectedAttestedPct)} expected by now`} tooltip="Expected pace assumes linear progress from cycle start to deadline." />
      <Tile label="Overdue" value={String(agg.overdue)} sub={agg.overdue ? "need a nudge" : "none"} />
      <Tile label="Contact mismatches" value={String(agg.selfCheckMismatches)} sub={`${agg.selfCheckMismatchedPeople} people`} />
    </dl>
  );
}
