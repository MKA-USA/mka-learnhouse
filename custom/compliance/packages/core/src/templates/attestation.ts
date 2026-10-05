import { MAJLIS_NAMES } from "../roster/generate";
import { blankQ, mcq } from "./util";
import type { TaskSpec } from "./types";

/** Contact self-check: select Majlis (decodable option ids) + type regional Qaid and department head. No answer key (ungraded). */
export function contactSelfCheckTasks(cycle: string, deptName: string): TaskSpec[] {
  const k = `${cycle}:${deptName}:selfcheck`;
  const majlis = [...MAJLIS_NAMES].sort();
  return [
    { key: "select-majlis", type: "QUIZ", title: "Your Majlis", description: "Select the Majlis where you serve.", hint: "Choose the Majlis you are an officeholder in.",
      contents: { grading_mode: "ALL_OR_NOTHING", questions: [mcq(`${k}:majlis`, "Which Majlis do you serve in?", majlis.map((m) => ({ text: m, correct: false })))] } },
    { key: "name-contacts", type: "FORM", title: "Your counterparts", description: `Type the names of your Regional Qaid and the National Mohtamim of ${deptName}. Use the contacts table in the previous lesson.`, hint: "First and last name.",
      contents: { questions: [blankQ(`${k}:regional`, "Name of your Regional Qaid", "Regional Qaid"), blankQ(`${k}:head`, `Name of the National Mohtamim ${deptName}`, "Department head")] } },
  ];
}

export function signOffTasks(cycle: string, scope: string): TaskSpec[] {
  const k = `${cycle}:${scope}:signoff`;
  return [
    { key: "confirm", type: "QUIZ", title: "Confirmation", description: "Confirm that you have completed this course.", hint: "Choose Yes only if you have read each lesson.",
      contents: { grading_mode: "ALL_OR_NOTHING", questions: [mcq(`${k}:confirm`, "I have read and understood the lessons in this course and my responsibilities as an officeholder.", [{ text: "Yes", correct: true }, { text: "No", correct: false }])] } },
    { key: "full-name", type: "FORM", title: "Sign with your full name", description: "Type your full name as your signature. This is kept as your attestation record.", hint: "Your legal first and last name.",
      contents: { questions: [blankQ(`${k}:name`, "Type your full name", "Full name")] } },
  ];
}
