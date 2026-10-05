export interface AttentionConfig {
  /** Fraction of learners expected to be attested at the deadline. */
  targetAtDeadline: number;
  /** Shape of the expected curve between a learner's window start and due date. */
  curve: "linear";
  /** Days allowed from appointment to completion for mid-year appointees. */
  appointeeWindowDays: number;
  /** Which courses must be attested for a learner to count as attested. */
  requiredCourses: ("general" | "department")[];
  weights: { shortfall: number; overdue: number; mismatch: number };
  thresholds: {
    amber: number;                 // score >= amber -> amber
    red: number;                   // score >= red -> red
    overdueRateRed: number;        // overdue/expected >= this -> at least red
    mismatchRateAmber: number;     // mismatches/expected >= this -> at least amber
    notStartedGraceDays: number;   // do not flag "not started" before this many days into the window
  };
  trend: { flatBelow: number };    // abs change in attested % points treated as flat
  nounPlural: string;
}

export const DEFAULT_CONFIG: AttentionConfig = {
  targetAtDeadline: 1,
  curve: "linear",
  appointeeWindowDays: 30,
  requiredCourses: ["general", "department"],
  weights: { shortfall: 0.6, overdue: 0.25, mismatch: 0.15 },
  thresholds: { amber: 10, red: 25, overdueRateRed: 0.2, mismatchRateAmber: 0.1, notStartedGraceDays: 3 },
  trend: { flatBelow: 1 },
  nounPlural: "officeholders",
};

export function withConfig(partial?: DeepPartial<AttentionConfig>): AttentionConfig {
  const c = DEFAULT_CONFIG, p = partial ?? {};
  return {
    ...c, ...(p as object),
    weights: { ...c.weights, ...(p.weights ?? {}) },
    thresholds: { ...c.thresholds, ...(p.thresholds ?? {}) },
    trend: { ...c.trend, ...(p.trend ?? {}) },
    requiredCourses: (p.requiredCourses as AttentionConfig["requiredCourses"] | undefined) ?? c.requiredCourses,
  } as AttentionConfig;
}
export type DeepPartial<T> = { [K in keyof T]?: T[K] extends object ? (T[K] extends unknown[] ? T[K] : DeepPartial<T[K]>) : T[K] };
