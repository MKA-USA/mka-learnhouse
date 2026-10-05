import type { Trend } from "@mka/analytics/pure";

export function TrendText({ trend, span }: { trend: Trend; span: string }) {
  if (trend.direction === "unknown") return <span className="text-xs text-muted">no {span} comparison yet</span>;
  const pts = Math.round(trend.attestedDelta * 100);
  const glyph = trend.direction === "improving" ? "↑" : trend.direction === "worsening" ? "↓" : "→";
  const word = trend.direction === "improving" ? "improving" : trend.direction === "worsening" ? "slipping" : "flat";
  return <span className="text-xs text-muted"><span aria-hidden="true">{glyph} </span>{word} ({pts >= 0 ? "+" : ""}{pts} pts signed off vs {span})</span>;
}
