import { appendFileSync, readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { LhApi, LhClient, LhHttpError, STAGING_API_BASE, assertStaging } from "@mka/compliance-core/lh";

process.env.LH_API_BASE ||= STAGING_API_BASE;
assertStaging(process.env.LH_API_BASE);
if (!process.argv.includes("--confirm-staging")) { console.error("pass --confirm-staging"); process.exit(2); }
const slug = process.env.LH_ORG_SLUG || "default";
const client = LhClient.fromEnv({ ...process.env, LH_ORG_SLUG: slug }, { delayMs: 1200, maxRetries: 1 });
const api = new LhApi(client);

const NAME = "ZZ-TEST provisioner write probe";
const log: { step: string; status: number | string; ok: boolean; note?: string }[] = [];
let courseUuid: string | undefined;
let stop = false;

async function step<T>(name: string, fn: () => Promise<T>, note?: (r: T) => string): Promise<T | undefined> {
  if (stop) return undefined;
  try { const r = await fn(); log.push({ step: name, status: "2xx", ok: true, note: note?.(r) }); return r; }
  catch (e) {
    const st = e instanceof LhHttpError ? e.status : "-";
    log.push({ step: name, status: st, ok: false, note: e instanceof LhHttpError ? (e.detail ?? "").slice(0, 160) : "error" });
    stop = true; return undefined;
  }
}

const doc = { type: "doc", content: [
  { type: "heading", attrs: { level: 2 }, content: [{ type: "text", text: "Probe lesson" }] },
  { type: "paragraph", content: [{ type: "text", text: "Probe ", marks: [{ type: "bold" }] }, { type: "text", text: "content." }] },
  { type: "calloutInfo", content: [{ type: "text", text: "callout" }] },
  { type: "bulletList", content: [{ type: "listItem", content: [{ type: "paragraph", content: [{ type: "text", text: "item" }] }] }] },
  { type: "table", content: [{ type: "tableRow", content: [
    { type: "tableHeader", content: [{ type: "paragraph", content: [{ type: "text", text: "Role" }] }] },
    { type: "tableHeader", content: [{ type: "paragraph", content: [{ type: "text", text: "Mailbox" }] }] }] }] },
] };

try {
  const courses = await step("GET courses (find org_id)", () => api.listCourses(1, 1, true));
  const orgId = courses?.[0]?.org_id ?? 1;
  const existing = (courses ?? []).find((c) => c.name === NAME);
  if (existing) { log.push({ step: "abort: probe course already exists", status: "-", ok: false }); stop = true; }

  const course = await step("POST /courses/ (draft)", () => api.createCourse(orgId, { name: NAME, description: "temporary write probe", about: "temporary", public: false }), (r) => `published=${r.published}`);
  courseUuid = course?.course_uuid;
  const chapter = course && await step("POST /chapters/", () => api.createChapter({ name: "Probe chapter", org_id: orgId, course_id: course.id }));
  const act = chapter && course && await step("POST /activities/ (dynamic page)", () => api.createActivity({ chapter_id: chapter.id, name: "Probe lesson", activity_type: "TYPE_DYNAMIC", activity_sub_type: "SUBTYPE_DYNAMIC_PAGE" }));
  if (act) await step("PUT /activities/{uuid} (ProseMirror incl. table)", () => api.updateActivity(act.activity_uuid, { content: doc }));
  const aact = chapter && course && await step("POST /activities/ (assignment)", () => api.createActivity({ chapter_id: chapter.id, name: "Probe assignment", activity_type: "TYPE_ASSIGNMENT", activity_sub_type: "SUBTYPE_ASSIGNMENT_ANY" }));
  const asg = aact && chapter && course && await step("POST /assignments/ (ungraded)", () => api.createAssignment({
    title: "Probe assignment", description: "probe", grading_type: "PERCENTAGE", org_id: orgId, course_id: course.id,
    chapter_id: chapter.id, activity_id: aact.id, ungraded: true, published: false }));
  if (asg) {
    await step("POST task QUIZ", () => api.createAssignmentTask(asg.assignment_uuid, { title: "Quiz", description: "q", hint: "h", assignment_type: "QUIZ", contents: { grading_mode: "ALL_OR_NOTHING", questions: [{
      questionUUID: "question_probe1", questionText: "Pick A", response_type: "single",
      options: [{ optionUUID: "option_p1", text: "A", fileID: "", type: "text", assigned_right_answer: true }, { optionUUID: "option_p2", text: "B", fileID: "", type: "text", assigned_right_answer: false }] }] } }));
    await step("POST task FORM (blank with empty correctAnswer)", () => api.createAssignmentTask(asg.assignment_uuid, { title: "Form", description: "f", hint: "h", assignment_type: "FORM", contents: { questions: [{
      questionUUID: "question_probe2", questionText: "Type your full name", blanks: [{ blankUUID: "blank_p1", placeholder: "Full name", correctAnswer: "" }] }] } }));
  }
  // read back
  if (course) await step("GET /courses/{uuid}/meta (readback)", () => api.getCourseMeta(course.course_uuid), (r) => `published=${String((r as { published?: unknown }).published)}`);
  if (act) await step("GET /activities/{uuid} (readback content)", () => api.getActivity(act.activity_uuid), (r) => `content.type=${String((r.content as { type?: unknown }).type)}, nodes=${(r.content as { content?: unknown[] }).content?.length ?? 0}`);
  if (asg) {
    await step("GET /assignments/{uuid} (readback)", () => api.getAssignment(asg.assignment_uuid));
    await step("GET /assignments/{uuid}/tasks (readback)", () => api.listAssignmentTasks(asg.assignment_uuid), (r) => `${r.length} tasks`);
  }
} finally {
  stop = false;
  if (courseUuid) await step("DELETE /courses/{uuid} (test course only)", () => api.deleteCourse(courseUuid!));
  if (courseUuid) { stop = false; await step("GET courses (verify test course gone)", () => api.listCourses(1, 50, true), (r) => `probe course still listed: ${r.some((c) => c.course_uuid === courseUuid)}`); }
}

const rows = log.map((l) => `| ${l.step} | ${l.status} | ${l.ok ? "OK" : "FAILED"} | ${(l.note ?? "").replace(/\|/g, "/")} |`);
const section = ["", "## Write probe (staging, test course only)", "", `Generated: ${new Date().toISOString()}. Created one draft course "${NAME}", exercised chapter/activity/assignment/tasks, read back, then deleted that course only.`, "",
  "| Step | HTTP | Result | Note |", "|---|---|---|---|", ...rows, ""].join("\n");
const out = fileURLToPath(new URL("../../../docs/probe-report.md", import.meta.url));
let cur = ""; try { cur = readFileSync(out, "utf8"); } catch {}
writeFileSync(out, cur.replace(/\n## Write probe[\s\S]*$/, "") + section);
console.log(section);
if (log.some((l) => !l.ok)) process.exit(1);
