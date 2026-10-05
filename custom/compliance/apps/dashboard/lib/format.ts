import type { Rag, ScoredLearner, Status } from "@mka/analytics/pure";
import { diffDays } from "@mka/analytics/pure";

export const pct = (x: number) => `${Math.round(x * 100)}%`;
export const regionLabel = (r: string) => r || "National";
export const levelLabel = (l: ScoredLearner["level"]) => (l === "national" ? "National" : l === "region" ? "Regional" : "Local");

/** RAG is never colour alone: every state has a word and a distinct glyph. */
export const RAG_META: Record<Rag, { word: string; glyph: string; cell: string; text: string }> = {
  red: { word: "Act now", glyph: "▲", cell: "bg-danger-soft border-danger/40", text: "text-danger" },
  amber: { word: "Watch", glyph: "◆", cell: "bg-warning-soft border-warning/40", text: "text-warning" },
  green: { word: "On track", glyph: "●", cell: "bg-success-soft border-success/30", text: "text-success" },
  none: { word: "No data", glyph: "○", cell: "bg-surface-secondary border-border", text: "text-muted" },
};

export const STATUS_META: Record<Status, { label: string; color: "default" | "accent" | "success" | "warning" | "danger" }> = {
  not_started: { label: "Not started", color: "default" },
  in_progress: { label: "In progress", color: "accent" },
  completed: { label: "Awaiting sign-off", color: "warning" },
  attested: { label: "Signed off", color: "success" },
  overdue: { label: "Overdue", color: "danger" },
};
export const STATUS_ORDER: Status[] = ["overdue", "not_started", "in_progress", "completed", "attested"];

export function shortDate(day: string | null | undefined): string {
  if (!day) return "—";
  const d = new Date(`${day.slice(0, 10)}T00:00:00Z`);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
}
export function ago(day: string | null | undefined, asOf: string): string {
  if (!day) return "never";
  const n = diffDays(asOf, day.slice(0, 10));
  return n <= 0 ? "today" : n === 1 ? "yesterday" : `${n} days ago`;
}
export const lessons = (r: Pick<ScoredLearner, "lessonsDone" | "lessonsTotal">) => (r.lessonsTotal ? `${r.lessonsDone}/${r.lessonsTotal}` : "—");
export const personLabel = (r: ScoredLearner) => r.personName || r.email;

/** Region '' (national roles) travels in URLs as "_national"; department '' (executives) as "executive". */
export const regionParam = (r: string) => r || "_national";
export const deptParam = (d: string) => d || "executive";
export const deptFromParam = (p: string) => (p === "executive" ? "" : p);
export const safeDecode = (s: string) => { try { return decodeURIComponent(s); } catch { return s; } };

export const STATUS_OPTIONS: { id: string; label: string }[] = [
  { id: "attention", label: "Not signed off yet" },
  ...STATUS_ORDER.map((s) => ({ id: s, label: STATUS_META[s].label })),
];
