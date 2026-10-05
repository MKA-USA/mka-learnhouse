import { createHash } from "node:crypto";
import type { CourseSpec, QuizQuestion, FormQuestion } from "./types";

export const sha = (s: string, n = 12) => createHash("sha256").update(s).digest("hex").slice(0, n);
/** Deterministic ids so re-renders are byte-identical (and learner answers can be decoded later). */
export const qid = (key: string) => `question_${sha(key)}`;
export const oid = (key: string) => `option_${sha(key)}`;
export const bid = (key: string) => `blank_${sha(key)}`;

export function seededShuffle<T>(arr: T[], seed: string): T[] {
  const a = [...arr]; let h = parseInt(sha(seed, 8), 16) >>> 0;
  const rnd = () => { h = (Math.imul(h ^ (h >>> 15), 2246822519) + 0x9e3779b9) >>> 0; return h / 0xffffffff; };
  for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(rnd() * (i + 1)); [a[i], a[j]] = [a[j]!, a[i]!]; }
  return a;
}

export function mcq(key: string, text: string, options: { text: string; correct: boolean }[], multiple = false): QuizQuestion {
  return { questionUUID: qid(key), questionText: text, response_type: multiple ? "multiple" : "single",
    options: options.map((o, i) => ({ optionUUID: oid(`${key}:${i}:${o.text}`), text: o.text, fileID: "", type: "text", assigned_right_answer: o.correct })) };
}
export function blankQ(key: string, text: string, placeholder: string): FormQuestion {
  return { questionUUID: qid(key), questionText: text, blanks: [{ blankUUID: bid(key), placeholder, correctAnswer: "" }] };
}

/** Stable hash of a spec for change detection (file abs paths excluded). */
export function specHash(spec: CourseSpec): string {
  return sha(JSON.stringify(spec, (k, v) => (k === "abs" ? undefined : v)), 16);
}

export const COURSE_PREFIX = "MKA";
export const courseName = (cycle: string, suffix: string) => `${COURSE_PREFIX} ${cycle} · ${suffix}`;
