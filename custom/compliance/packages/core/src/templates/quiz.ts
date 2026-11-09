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

/** Knowledge check from the department's own plan objectives (stale ones too: it quizzes what the lesson shows); distractors are other departments' objectives. */
export function buildPlanQuiz(args: { cycle: string; deptSlug: string; deptName: string; ownObjectives: string[]; otherObjectives: string[] }): QuizBuild {
  const { cycle, deptSlug, deptName, ownObjectives } = args;
  const own = ownObjectives.filter((o) => !args.otherObjectives.includes(o));
  const pool = [...new Set(args.otherObjectives)];
  if (own.length >= 1 && pool.length >= 3) {
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

/**
 * Majlis Plan knowledge check: "Which department's plan has this objective?" across departments.
 * `items`: each department's own objectives. Needs 4+ departments with objectives, else a single generic fallback question.
 */
export function buildMajlisQuiz(args: { cycle: string; items: { slug: string; name: string; objectives: string[] }[]; count?: number }): QuizBuild {
  const { cycle } = args; const withObj = args.items.filter((i) => i.objectives.length);
  const key = `${cycle}:majlis-plan`;
  if (withObj.length >= 4) {
    const picks = seededShuffle(withObj, `${key}:depts`).slice(0, args.count ?? 4);
    const questions = picks.map((d, i) => {
      const unique = d.objectives.filter((o) => !args.items.some((x) => x.slug !== d.slug && x.objectives.includes(o)));
      const obj = seededShuffle(unique.length ? unique : d.objectives, `${key}:o${i}`)[0]!;
      const distract = seededShuffle(withObj.filter((x) => x.slug !== d.slug && !x.objectives.includes(obj)), `${key}:d${i}`).slice(0, 3);
      const options = seededShuffle([{ text: d.name, correct: true }, ...distract.map((x) => ({ text: x.name, correct: false }))], `${key}:opt${i}`);
      return mcq(`${key}:q${i}`, `Which department's annual plan includes this objective: "${obj}"?`, options);
    });
    return { questions, basis: "plan" };
  }
  const q = mcq(`${key}:fallback`, "As Qaid or Naib Qaid, whose Local key results do you need to know?", seededShuffle([
    { text: "Every department's Local key results", correct: true },
    { text: "Only the Qaid's own", correct: false },
    { text: "None; departments handle their own", correct: false },
  ], `${key}:fb`));
  return { questions: [q], basis: "fallback" };
}
