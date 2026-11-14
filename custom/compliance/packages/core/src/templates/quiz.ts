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

/**
 * Knowledge check from the department's own plan objectives (stale ones too: it quizzes what the lesson shows). Every stem is different:
 *  1. "Which of these is an objective in the X annual plan?"  (one own objective + 3 from other departments)
 *  2. "Which of these is NOT an objective in the X annual plan?" (one other-department objective + 3 own; needs 3+ own objectives)
 *  3. "Which of these is Objective N in the X annual plan?"      (own objective N + other own objectives, topped up from other departments; needs 2+ own)
 * Deterministic (seeded by cycle and department); the number of questions matches the number of own objectives, up to 3.
 */
export function buildPlanQuiz(args: { cycle: string; deptSlug: string; deptName: string; ownObjectives: string[]; otherObjectives: string[] }): QuizBuild {
  const { cycle, deptSlug, deptName, ownObjectives } = args;
  const own = ownObjectives.filter((o) => !args.otherObjectives.includes(o));
  const pool = [...new Set(args.otherObjectives)];
  const seed = `${cycle}:${deptSlug}`;
  if (own.length >= 1 && pool.length >= 3) {
    const questions: QuizQuestion[] = [];
    const [pick] = seededShuffle(own, `${seed}:own`);
    questions.push(mcq(`${seed}:plan:0`, `Which of these is an objective in the ${deptName} annual plan?`,
      seededShuffle([{ text: pick!, correct: true }, ...seededShuffle(pool, `${seed}:d0`).slice(0, 3).map((d) => ({ text: d, correct: false }))], `${seed}:o0`)));
    if (own.length >= 3) {
      const [outsider] = seededShuffle(pool, `${seed}:d1`);
      const insiders = seededShuffle(own, `${seed}:in1`).slice(0, 3);
      questions.push(mcq(`${seed}:plan:1`, `Which of these is NOT an objective in the ${deptName} annual plan?`,
        seededShuffle([{ text: outsider!, correct: true }, ...insiders.map((d) => ({ text: d, correct: false }))], `${seed}:o1`)));
    }
    if (own.length >= 2) {
      const idx = seededShuffle(own.map((o) => ownObjectives.indexOf(o)), `${seed}:n2`)[0]!; // position in the plan, 0-based
      const target = ownObjectives[idx]!;
      const others = [...seededShuffle(own.filter((o) => o !== target), `${seed}:in2`), ...seededShuffle(pool, `${seed}:d2`)].slice(0, 3);
      questions.push(mcq(`${seed}:plan:2`, `Which of these is Objective ${idx + 1} in the ${deptName} annual plan?`,
        seededShuffle([{ text: target, correct: true }, ...others.map((d) => ({ text: d, correct: false }))], `${seed}:o2`)));
    }
    return { questions, basis: "plan" };
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
/** Four different framings, one per question, so the stems never repeat. */
const MAJLIS_STEMS: ((obj: string) => string)[] = [
  (o) => `Which department's annual plan includes this objective: "${o}"?`,
  (o) => `A Khadim asks who at the national level is responsible for "${o}". Which department is it?`,
  (o) => `You want an update on "${o}". Whose Mohtamim do you contact?`,
  (o) => `Which department reports on this objective to your Majlis: "${o}"?`,
];

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
      return mcq(`${key}:q${i}`, MAJLIS_STEMS[i % MAJLIS_STEMS.length]!(obj), options);
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
