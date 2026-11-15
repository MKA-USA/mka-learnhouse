import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { bold, p, text, type PMNode } from "../content/pm";
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

/** "Maal (Finance)", but just "Amoomi" when the translation is the same word. */
export const deptLabel = (name: string, translation: string): string => (translation && translation.trim().toLowerCase() !== name.trim().toLowerCase() ? `${name} (${translation})` : name);

/** Seconds of a local video via ffprobe, or `fallback` when ffprobe is unavailable (estimates only; never throws). */
export function videoSeconds(abs: string, fallback = 120): number {
  try {
    const out = execFileSync("ffprobe", ["-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", abs], { encoding: "utf8", timeout: 10_000 }).trim();
    const n = Number(out); return Number.isFinite(n) && n > 0 ? n : fallback;
  } catch { return fallback; }
}

/** Round to the nearest 5 minutes (minimum 5) for course descriptions. */
export const roundMinutes = (m: number): number => Math.max(5, Math.round(m / 5) * 5);
export const READING_WPM = 200; // plain-text reading speed used for time estimates
export const SECONDS_PER_QUESTION = 30;

/** Instruction lines for assignment pages. Deliberately label-neutral about the button text ("Submit" in both the current and the renamed UI): they must stay true across LearnHouse button renames. "Finish course" is course.finish_course in apps/web/locales/en.json. */
/** Total attempts a learner gets on a graded knowledge check. LearnHouse semantics: `max_retries` is the cap on total attempts (the first submission is attempt 1; the retry endpoint refuses once attempt_number >= max_retries), so 3 means initial + 2 retries. */
export const QUIZ_MAX_ATTEMPTS = 3;
export const QUIZ_INSTRUCTION = (passThreshold?: number | null): string =>
  `Answer each question, then press the Submit button at the bottom of the page. ${passThreshold ? `You need ${passThreshold}% to pass, and you have` : "You have"} ${QUIZ_MAX_ATTEMPTS} attempts.`;
export const SIGNOFF_INSTRUCTION = "Before you finish, check that every page, video and PDF in this course shows as complete. Then answer the question and type your full name, press the Submit button at the bottom of the page, and press Finish course.";

/** LearnHouse shows a "Mark as complete" control (activities.mark_as_complete in apps/web/locales/en.json) on every non-assignment activity: pages, videos and PDFs. Course progress only counts activities the learner ticked. */
export const COMPLETION_SENTENCE = "To finish this course, every page must show as complete: tick Mark as complete on each page, video and PDF, then press Next.";
export const completionLine = (): PMNode => p([text("When you have read this page, tick "), bold("Mark as complete"), text(", then press "), bold("Next"), text(".")]);
/** Append the completion line to a generated page's content. */
export const withCompletion = (content: PMNode[]): PMNode[] => [...content, completionLine()];

export const COURSE_PREFIX = "MKA";
export const courseName = (cycle: string, suffix: string) => `${COURSE_PREFIX} ${cycle} · ${suffix}`;
