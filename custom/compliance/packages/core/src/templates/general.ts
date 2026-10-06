import { existsSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { htmlToProseMirror } from "../content/html";
import { type ContentFlag, scanContent } from "../content/flags";
import { calloutInfo, calloutWarning, doc, p, plainText, text, type PMNode } from "../content/pm";
import { allLessons, lessonHtml, type TkCourse, type TkLesson } from "../thinkific/load";
import { signOffTasks } from "./attestation";
import type { ActivitySpec, ChapterSpec, CourseSpec, QuizQuestion, SourceRef } from "./types";
import { courseName, mcq } from "./util";
import { STALE_NOTE } from "./department";

export interface FoundationQuiz { name: string; passingScore: number | null; questions: { prompt: string; multiple: boolean; choices: { text: string; correct: boolean }[] }[] }
export interface FoundationPage { name: string; html: string; source: SourceRef }
export interface FoundationFile { name: string; rel: string; abs: string; size: number; source: SourceRef }
export interface FoundationInput {
  courseId: number; introVideo: FoundationFile | null;
  jamaat: FoundationPage; jamaatQuiz: FoundationQuiz; khuddam: FoundationPage; khuddamQuiz: FoundationQuiz;
  resources: FoundationPage[]; rules: FoundationPage; rulesQuiz: FoundationQuiz; pdfs: FoundationFile[];
}

const strip = (html: string) => htmlToProseMirror(html || "");
const PREV_YEAR_RE = /\b(20(?:1\d|2[0-5]))\b/;

function quizOf(c: TkCourse, l: TkLesson): FoundationQuiz {
  const j = JSON.parse(readFileSync(join(c.dir, l.raw), "utf8")) as { detail: { passingScore: number | null; questions: { edges: { node: { prompt: string; displayType: string; position: number; choices: { edges: { node: { text: string; credited: boolean; position: number } }[] } } }[] } } };
  const qs = j.detail.questions.edges.map((e) => e.node).sort((a, b) => a.position - b.position).map((q) => ({
    prompt: plainText(htmlToProseMirror(q.prompt).doc).trim(),
    multiple: q.displayType === "checkbox",
    choices: q.choices.edges.map((e) => e.node).sort((a, b) => a.position - b.position).map((c2) => ({ text: plainText(htmlToProseMirror(c2.text).doc).trim(), correct: !!c2.credited })),
  }));
  return { name: l.name, passingScore: j.detail.passingScore, questions: qs };
}

/** Load the Foundation Course export (folder 3280094_ai-placeholder is really the Foundation course). */
export function loadFoundation(c: TkCourse): FoundationInput {
  const L = allLessons(c);
  const byName = (re: RegExp, type?: string) => { const l = L.find((x) => re.test(x.name) && (!type || x.type === type)); if (!l) throw new Error(`Foundation lesson not found: ${re}`); return l; };
  const src = (l: TkLesson): SourceRef => ({ system: "thinkific", courseId: c.id, chapterId: l.chapterId, lessonId: l.id, path: l.raw });
  const page = (l: TkLesson): FoundationPage => ({ name: l.name.replace(/\s+/g, " ").trim(), html: lessonHtml(c, l), source: src(l) });
  const file = (l: TkLesson, key: "file" | "video_file"): FoundationFile | null => {
    const rel = l[key]; if (!rel) return null;
    const abs = key === "video_file" ? join(c.dir, "..", rel) : join(c.dir, rel);
    return existsSync(abs) ? { name: l.name, rel, abs, size: statSync(abs).size, source: src(l) } : null;
  };
  const intro = L.find((x) => x.type === "Video");
  return {
    courseId: c.id, introVideo: intro ? file(intro, "video_file") : null,
    jamaat: page(byName(/^Jama.at Ahmadiyya and its/, "Text")), jamaatQuiz: quizOf(c, byName(/^Quiz.*Jama.at Ahmadiyya/, "Quiz")),
    khuddam: page(byName(/^Khuddamul Ahmadiyya Organizational/, "Text")), khuddamQuiz: quizOf(c, byName(/^Quiz.*Khuddamul/, "Quiz")),
    resources: ["Submitting your Report", "Info Center", "Accessing Tajneed", "Calendar of Events"].map((n) => page(byName(new RegExp(`^${n}`), "Text"))),
    rules: page(byName(/^Rules and Procedures/, "Text")), rulesQuiz: quizOf(c, byName(/^Quiz.*Rules/, "Quiz")),
    pdfs: L.filter((x) => x.type === "Pdf").map((x) => file(x, "file")).filter((f): f is FoundationFile => !!f),
  };
}

function quizTasks(cycle: string, scope: string, q: FoundationQuiz): QuizQuestion[] {
  return q.questions.map((qq, i) => mcq(`${cycle}:${scope}:${i}:${qq.prompt}`, qq.prompt, qq.choices.map((c) => ({ text: c.text, correct: c.correct })), qq.multiple));
}

export function buildGeneralCourse(args: { cycle: string; deadline: string; foundation: FoundationInput }): { spec: CourseSpec; flags: { lesson: string; flag: ContentFlag }[] } {
  const { cycle, deadline, foundation: F } = args;
  const cflags: { lesson: string; flag: ContentFlag }[] = [];
  const flagsOut: string[] = [];

  const makePage = (pg: FoundationPage, key: string, extra: PMNode[] = []): ActivitySpec => {
    const r = strip(pg.html);
    for (const f of scanContent({ text: plainText(r.doc), links: r.links, imagesDropped: r.imagesDropped })) cflags.push({ lesson: pg.name, flag: f });
    const leading: PMNode[] = PREV_YEAR_RE.test(plainText(r.doc)) ? [calloutWarning(`${STALE_NOTE}: this lesson mentions a previous year.`)] : [];
    if (leading.length) flagsOut.push(`${pg.name}: mentions a previous year`);
    return { kind: "page", key, name: pg.name, doc: doc(...leading, ...extra, ...r.doc.content), source: pg.source };
  };
  const quiz = (key: string, name: string, q: FoundationQuiz, src?: SourceRef): ActivitySpec => ({
    kind: "assignment", key, name, title: name, description: "Answer all questions.", ungraded: false, ...(q.passingScore ? { passThreshold: q.passingScore } : {}), source: src,
    tasks: [{ key: `${key}-q`, type: "QUIZ", title: name, description: "Choose the best answer.", hint: "Review the lesson if unsure.", contents: { grading_mode: "ALL_OR_NOTHING", questions: quizTasks(cycle, key, q) } }],
  });

  const resourceConfirm: ActivitySpec = {
    kind: "assignment", key: "resources-confirm", name: "Resources: log in and confirm", title: "Resources: log in and confirm", description: "Confirm that you can access each resource.", ungraded: true,
    tasks: [{ key: "resources-q", type: "QUIZ", title: "Access check", description: "Confirm each item.", hint: "Log in to each resource before answering Yes.",
      contents: { grading_mode: "ALL_OR_NOTHING", questions: ["your MKA email account", "the Info Center", "the Tajneed system (Daftar)", "the national events calendar", "the report submission system"].map((x, i) =>
        mcq(`${cycle}:general:resources:${i}`, `I have logged in to / opened ${x} and confirmed I can access it.`, [{ text: "Yes", correct: true }, { text: "No", correct: false }])) } }],
  };

  const chapters: ChapterSpec[] = [];
  if (F.introVideo) chapters.push({ key: "ch-intro", name: "Course Introduction", description: "Start here", activities: [{ kind: "video", key: "intro-video", name: "Course Introduction Video", file: { rel: F.introVideo.rel, abs: F.introVideo.abs, size: F.introVideo.size }, source: F.introVideo.source }] });
  chapters.push(
    { key: "ch-structures", name: "Organizational Structures", description: "Jama'at and Khuddam structure", activities: [
      makePage(F.jamaat, "jamaat-structure"), quiz("quiz-jamaat", F.jamaatQuiz.name, F.jamaatQuiz), makePage(F.khuddam, "khuddam-structure"), quiz("quiz-khuddam", F.khuddamQuiz.name, F.khuddamQuiz) ] },
    { key: "ch-resources", name: "Resources for Officeholders", description: "Systems and resources you will use", activities: [...F.resources.map((r, i) => makePage(r, `resource-${i + 1}`)), resourceConfirm] },
    { key: "ch-rules", name: "Housekeeping Rules", description: "Rules and procedures", activities: [makePage(F.rules, "rules"), quiz("quiz-rules", F.rulesQuiz.name, F.rulesQuiz)] },
    { key: "ch-message", name: "Huzoor's Latest Message to the US Khuddam", description: "Read and confirm", activities: [
      { kind: "page", key: "message-intro", name: "Read Huzoor's message", doc: doc(calloutWarning(`${STALE_NOTE}: the PDFs below are last year's message. The ${cycle} message will replace them.`), p("Read the message and its translation, then continue.")) },
      ...F.pdfs.map((f, i): ActivitySpec => ({ kind: "pdf", key: `message-pdf-${i + 1}`, name: f.name, file: { rel: f.rel, abs: f.abs, size: f.size }, source: f.source })),
    ] },
    { key: "ch-signoff", name: "Sign-off", description: "Complete the course", activities: [
      { kind: "assignment", key: "signoff", name: "Final sign-off", title: "Final sign-off", description: "Confirm and sign to complete this course.", ungraded: true, tasks: signOffTasks(cycle, "general") } ] },
  );
  flagsOut.push("Huzoor's message PDFs are last year's; replace for the new cycle");

  return {
    flags: cflags,
    spec: { key: `${cycle}|general`, kind: "general", departmentSlug: "", cycle, name: courseName(cycle, "General"),
      description: `Foundation training for all MKA officeholders, ${cycle}. Complete by ${deadline}.`,
      about: "Required annual foundation course: organizational structure, resources, housekeeping rules and Huzoor's message.",
      learnings: "Jama'at and Khuddam structure, officeholder resources, housekeeping rules", tags: `mka,compliance,${cycle},general`, chapters, flags: flagsOut },
  };
}
export { calloutInfo };
