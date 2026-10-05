import type { SeriesPoint } from "@mka/analytics/pure";

/** Attested % over time (solid) against the expected curve (dashed). Pure SVG, server rendered. */
export function Sparkline({ series, width = 120, height = 32, label }: { series: SeriesPoint[]; width?: number; height?: number; label?: string }) {
  if (series.length < 2) return <span className="text-xs text-muted" aria-label="Not enough history yet">no trend yet</span>;
  const max = Math.max(0.05, ...series.map((p) => Math.max(p.attestedPct, p.expectedAttestedPct)));
  const x = (i: number) => (i / (series.length - 1)) * (width - 4) + 2;
  const y = (v: number) => height - 3 - (v / max) * (height - 6);
  const line = (f: (p: SeriesPoint) => number) => series.map((p, i) => `${x(i).toFixed(1)},${y(f(p)).toFixed(1)}`).join(" ");
  const first = series[0]!, last = series.at(-1)!;
  const text = label ?? `Signed off ${Math.round(first.attestedPct * 100)}% on ${first.date}, ${Math.round(last.attestedPct * 100)}% on ${last.date}; expected ${Math.round(last.expectedAttestedPct * 100)}%`;
  return (
    <svg role="img" aria-label={text} width={width} height={height} viewBox={`0 0 ${width} ${height}`} className="shrink-0 overflow-visible">
      <title>{text}</title>
      <polyline points={line((p) => p.expectedAttestedPct)} fill="none" stroke="currentColor" strokeOpacity="0.4" strokeDasharray="3 3" strokeWidth="1.5" className="text-muted" />
      <polyline points={line((p) => p.attestedPct)} fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" className="text-accent" />
    </svg>
  );
}
