import type { SelfCheckAnswers, SelfCheckExpected, SelfCheckResult } from "./types";

const norm = (s: string) => s.toLowerCase().trim();
const alnum = (s: string) => norm(s).replace(/[^a-z0-9]/g, "");

/** Loose match: emails compare in full, names compare alphanumerics, and a titled answer ("Qaid Jane Doe") still matches. */
export function looseMatch(expected: string, got: string): boolean {
  if (expected.includes("@") || got.includes("@")) return norm(expected) === norm(got);
  const e = alnum(expected), g = alnum(got);
  if (!e || !g) return false;
  if (e === g) return true;
  const [short, long] = e.length <= g.length ? [e, g] : [g, e];
  return short.length >= 4 && long.includes(short);
}

const FIELDS: (keyof SelfCheckAnswers)[] = ["majlis", "regionalQaid", "deptHead"];

/**
 * Compare a learner's contact self-check (FORM answers) with what the roster says.
 * Blank answers are not mismatches (the learner just skipped); an unanswered form is `answered: false`.
 */
export function evaluateSelfCheck(answers: SelfCheckAnswers | null | undefined, expected: SelfCheckExpected): SelfCheckResult {
  if (!answers) return { answered: false, mismatches: [] };
  const given = FIELDS.filter((f) => (answers[f] ?? "").trim() !== "");
  if (!given.length) return { answered: false, mismatches: [] };
  const mismatches: string[] = [];
  for (const f of given) {
    const exp = expected[f];
    if (exp && !looseMatch(exp, answers[f]!)) mismatches.push(f);
  }
  return { answered: true, mismatches };
}
