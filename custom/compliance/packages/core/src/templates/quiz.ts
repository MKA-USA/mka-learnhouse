import { plainText, type PMDoc } from "../content/pm";
import { mcq, seededShuffle } from "./util";
import type { QuizQuestion } from "./types";

const OBJ_RE = /objective\s*\d*\s*[:.–—-]\s*([^\n|]{6,160})/gi;
/** "Objective 1: Increase Engagement of Khuddam" -> "Increase Engagement of Khuddam" */
export function extractObjectives(doc: PMDoc | null | undefined): string[] {
  if (!doc) return [];
  const out: string[] = []; const t = plainText(doc);
  for (const m of t.matchAll(OBJ_RE)) { const s = m[1]!.trim().replace(/\s+/g, " ").replace(/[.;:,]+$/, ""); if (s && !out.includes(s)) out.push(s); }
  return out;
}

export interface QuizBuild { questions: QuizQuestion[]; basis: "plan" | "fallback" }

/** Knowledge check from the department's own plan objectives; distractors are other departments' objectives. */
export function buildPlanQuiz(args: { cycle: string; deptSlug: string; deptName: string; ownObjectives: string[]; otherObjectives: string[]; stale: boolean }): QuizBuild {
  const { cycle, deptSlug, deptName, ownObjectives, stale } = args;
  const own = ownObjectives.filter((o) => !args.otherObjectives.includes(o));
  const pool = [...new Set(args.otherObjectives)];
  if (!stale && own.length >= 1 && pool.length >= 3) {
    const picks = seededShuffle(own, `${cycle}:${deptSlug}:own`).slice(0, 3);
    const qs = picks.map((o, i) => {
      const distract = seededShuffle(pool, `${cycle}:${deptSlug}:d${i}`).slice(0, 3);
      const options = seededShuffle([{ text: o, correct: true }, ...distract.map((d) => ({ text: d, correct: false }))], `${cycle}:${deptSlug}:o${i}`);
      return mcq(`${cycle}:${deptSlug}:plan:${i}`, `Which of these is an objective in the ${deptName} annual plan?`, options);
    });
    return { questions: qs, basis: "plan" };
  }
  const q = mcq(`${cycle}:${deptSlug}:fallback`, "If you have questions about your responsibilities or the department plan, whom should you contact?", seededShuffle([
    { text: "Your regional or national officeholder", correct: true },
    { text: "Wait for the next annual meeting", correct: false },
    { text: "No one; each officeholder decides alone", correct: false },
  ], `${cycle}:${deptSlug}:fb`));
  return { questions: [q], basis: "fallback" };
}
