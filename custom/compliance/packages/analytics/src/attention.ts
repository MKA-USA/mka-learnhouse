import { diffDays } from "./dates";
import { DEFAULT_CONFIG, type AttentionConfig } from "./config";
import type { Aggregate } from "./aggregate";
import type { CycleInfo, Rag } from "./types";

export interface Attention {
  score: number;                   // 0..100, higher = needs more attention
  rag: Rag;
  shortfall: number;               // 0..1, expected attested minus actual attested
  reasons: string[];               // human-readable, most important first
  summary: string;                 // reasons joined, or a plain "on track" line
}

const RAG_ORDER: Record<Rag, number> = { red: 3, amber: 2, green: 1, none: 0 };
export const ragSeverity = (r: Rag) => RAG_ORDER[r];

const round = (n: number) => Math.round(n * 10) / 10;
const p0 = (x: number) => `${Math.round(x * 100)}%`;

/**
 * Attention for one group (department, region, department x region cell, ...).
 * score = 100 * (w.shortfall * shortfall + w.overdue * overdueRate + w.mismatch * min(1, 3 * mismatches / n))
 * RAG = score thresholds, plus hard rules: a high overdue rate is always red; many contact mismatches are at least amber.
 */
export function attention(a: Aggregate, cycle: CycleInfo, asOf: string, cfg: AttentionConfig = DEFAULT_CONFIG): Attention {
  const n = a.expected;
  if (n === 0) return { score: 0, rag: "none", shortfall: 0, reasons: [], summary: `No ${cfg.nounPlural} in scope` };
  const shortfall = Math.max(0, a.expectedAttestedPct - a.attestedPct);
  const overdueRate = a.overdue / n;
  const mismatchRate = a.selfCheckMismatches / n;
  const w = cfg.weights, t = cfg.thresholds;
  const score = round(100 * (w.shortfall * shortfall + w.overdue * overdueRate + w.mismatch * Math.min(1, 3 * mismatchRate)));

  let rag: Rag = score >= t.red ? "red" : score >= t.amber ? "amber" : "green";
  if (a.overdue > 0 && overdueRate >= t.overdueRateRed) rag = "red";
  else if (rag === "green" && mismatchRate >= t.mismatchRateAmber) rag = "amber";

  const reasons: string[] = [];
  if (a.overdue > 0) reasons.push(`${a.overdue} of ${n} overdue`);
  const sinceStart = diffDays(asOf, cycle.startsOn);
  if (a.notStarted > 0 && sinceStart >= t.notStartedGraceDays) reasons.push(`${a.notStarted} of ${n} haven't started`);
  if (shortfall >= 0.05) reasons.push(`attested ${p0(a.attestedPct)} vs ${p0(a.expectedAttestedPct)} expected`);
  if (a.selfCheckMismatches > 0) reasons.push(`${a.selfCheckMismatches} contact self-check mismatch${a.selfCheckMismatches === 1 ? "" : "es"}`);
  const summary = reasons.length ? reasons.join("; ") : rag === "green" ? "On track" : "Needs a look";
  return { score, rag, shortfall, reasons, summary };
}

/** Worst first: RAG, then score, then size. */
export function compareAttention(a: { att: Attention; agg: Aggregate }, b: { att: Attention; agg: Aggregate }): number {
  return ragSeverity(b.att.rag) - ragSeverity(a.att.rag) || b.att.score - a.att.score || b.agg.expected - a.agg.expected;
}
