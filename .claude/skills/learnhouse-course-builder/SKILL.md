---
name: learnhouse-course-builder
description: >
  Build and deploy complete courses in Learnhouse with AI-generated content, quizzes,
  assignments, and interactive scenarios. Use when the user wants to create a course,
  generate course content, build quizzes or assessments, structure chapters and activities,
  or populate a Learnhouse platform with educational material. Triggers on: "create a course",
  "build a course", "generate course content", "make a quiz", "create lessons", "build curriculum",
  "add course material", "create assignment", "generate learning content", "deploy a course".
---

# Learnhouse Course Builder Skill

Build complete, structured courses in Learnhouse — from curriculum planning through content generation, quiz creation, and deployment. This skill teaches agents how to use Learnhouse's existing AI-powered APIs and data model to efficiently create production-ready courses.

## When to Use

- User wants to create a new course from scratch or from a topic description
- User wants to generate content for existing course activities
- User needs quizzes, assignments, or interactive scenarios for course validation
- User wants to bulk-create or restructure course material
- User asks to "deploy" or "publish" a course

## Architecture Overview

Learnhouse uses a hierarchical content model:

```
Course
├── Chapter 1
│   ├── Activity 1 (TYPE_DYNAMIC — ProseMirror JSON content)
│   ├── Activity 2 (TYPE_ASSIGNMENT — graded tasks)
│   └── Activity 3 (TYPE_VIDEO — video content)
├── Chapter 2
│   └── ...
└── Chapter N
    └── ...
```

### Key Concepts

| Concept | Description |
|---------|-------------|
| **Course** | Top-level container with name, description, tags, learnings, thumbnail, SEO |
| **Chapter** | Ordered section within a course; has lock_type (public/authenticated/restricted) |
| **Activity** | A single learning unit within a chapter; type determines rendering |
| **Block** | Media objects attached to activities (video, image, audio, PDF, quiz) |
| **Assignment** | Graded assessment with multiple tasks; lives inside an activity |
| **ProseMirror JSON** | Rich content format for TYPE_DYNAMIC activities (text, quizzes, flipcards, embeds, etc.) |

### Activity Types

| Type | Subtype | Use Case |
|------|---------|----------|
| `TYPE_DYNAMIC` | `SUBTYPE_DYNAMIC_PAGE` | Rich content page (text, media, quizzes, flipcards) — **primary type** |
| `TYPE_ASSIGNMENT` | `SUBTYPE_ASSIGNMENT_ANY` | Graded assessments with auto/manual grading |
| `TYPE_VIDEO` | `SUBTYPE_VIDEO_YOUTUBE` / `SUBTYPE_VIDEO_HOSTED` | Video-only activities |
| `TYPE_DOCUMENT` | `SUBTYPE_DOCUMENT_PDF` / `SUBTYPE_DOCUMENT_DOC` | Document-only activities |
| `TYPE_CUSTOM` | `SUBTYPE_CUSTOM` | Custom content |
| `TYPE_SCORM` | `SUBTYPE_SCORM_12` / `SUBTYPE_SCORM_2004` | SCORM packages |

### ProseMirror Block Types (for TYPE_DYNAMIC content)

These are the block types available inside a dynamic activity's `content` JSON:

| Block Type | Description | AI-Generatable |
|------------|-------------|----------------|
| `paragraph` | Text paragraphs with bold/italic marks | ✅ |
| `heading` | Headers levels 1-6 | ✅ |
| `bulletList` / `orderedList` | Lists with listItem children | ✅ |
| `codeBlock` | Code with syntax highlighting (language attr) | ✅ |
| `blockQuiz` | Inline multiple-choice quiz (single or multiple response) | ✅ |
| `flipcard` | Flashcard with question/answer/color/size | ✅ |
| `flipcardGrid` | Grid of flipcards (columns 1-4) | ✅ |
| `calloutInfo` | Information callout box | ✅ |
| `calloutWarning` | Warning callout box | ✅ |
| `blockEmbed` | YouTube videos and external embeds | ✅ |
| `blockImage` | Image block (references media) | Via block API |
| `blockVideo` | Video block | Via block API |
| `blockPDF` | PDF document block | Via block API |
| `blockAudio` | Audio block | Via block API |
| `blockMathEquation` | LaTeX math equation | ✅ |
| `scenarios` | Interactive branching scenario | ✅ (AI API) |
| `button` | Clickable button | ✅ |
| `badge` | Badge/label element | ✅ |
| `blockLibrary` | Reusable content library block | Via block API |
| `H5P` | H5P interactive content | Via block API |
| `CodePlayground` | Live code editor | ✅ |

## Available AI APIs

Learnhouse has **built-in AI generation endpoints** that agents should call directly. These handle LLM interaction, structured output validation, ID stamping, and session management.

### 1. Course Planning (Multi-turn, Streaming)

**Purpose**: Generate a complete course structure (chapters + activities) from a topic description.

**Endpoints**:
```
POST /ai/courseplanning/start        — Start new planning session (SSE stream)
POST /ai/courseplanning/iterate      — Refine the plan with follow-up messages
POST /ai/courseplanning/finalize     — Create course/chapters/activities in DB
POST /ai/courseplanning/generate-activity — Generate ProseMirror content for an activity
POST /ai/courseplanning/save-activity-content — Save generated content to DB
```

**Request (start)**:
```json
{
  "org_id": 1,
  "prompt": "Create a course on Islamic finance fundamentals",
  "language": "en",
  "attachments": [
    {"type": "youtube", "url": "https://youtube.com/watch?v=..."},
    {"type": "file", "name": "syllabus.pdf", "content_base64": "...", "mime_type": "application/pdf"}
  ]
}
```

**Output schema (CoursePlan)**:
```json
{
  "name": "Course Title",
  "description": "Compelling description...",
  "learnings": "Outcome 1, Outcome 2, Outcome 3",
  "tags": ["tag1", "tag2"],
  "chapters": [
    {
      "name": "Chapter Title",
      "description": "Chapter description",
      "activities": [
        {
          "name": "Activity Title",
          "type": "TYPE_DYNAMIC",
          "description": "What learners will do",
          "suggested_blocks": ["heading", "paragraph", "blockQuiz", "flipcard"]
        }
      ]
    }
  ]
}
```

**Workflow**:
1. `POST /start` with topic → SSE stream of JSON course plan
2. `POST /iterate` (optional) with refinements → updated plan
3. `POST /finalize` with the plan → creates Course, Chapters, Activities in DB
4. `POST /generate-activity` per activity → SSE stream of ProseMirror JSON content
5. `POST /save-activity-content` → persists content to the activity

### 2. Quiz Generation (In-Editor, Inline)

**Purpose**: Generate multiple-choice quiz questions for embedding in activities.

**Endpoint**: `POST /ai/quiz/generate`

**Request**:
```json
{
  "org_id": 1,
  "prompt": "Test knowledge of halal investment principles",
  "activity_uuid": "activity_abc123",
  "num_questions": 5,
  "difficulty": "medium"
}
```

**Output** (ready to insert as `blockQuiz` attrs):
```json
{
  "quizId": "quiz_<uuid>",
  "questions": [
    {
      "question_id": "question_<uuid>",
      "question": "What is...",
      "type": "multiple_choice",
      "response_type": "single",
      "answers": [
        {"answer_id": "answer_<uuid>", "answer": "Correct answer", "correct": true},
        {"answer_id": "answer_<uuid>", "answer": "Wrong answer", "correct": false}
      ]
    }
  ]
}
```

**Features**: Multi-turn refinement via `session_uuid`, content-grounded when `activity_uuid` provided.

### 3. Assignment Generation (Graded Assessments)

**Purpose**: Generate complete graded assignments with diverse task types.

**Endpoint**: `POST /ai/assignments/generate`

**Supported task types**:
| Type | Description | Auto-gradable |
|------|-------------|---------------|
| `QUIZ` | Multiple-choice (single/multiple response) | ✅ |
| `FORM` | Fill-in-the-blank with hints | ✅ |
| `SHORT_ANSWER` | Open text with accepted answers + match modes | ✅ |
| `NUMBER_ANSWER` | Numeric answer with tolerance | ✅ |
| `FILE_SUBMISSION` | File upload (manual grading) | ❌ |

**Request**:
```json
{
  "org_id": 1,
  "course_uuid": "course_abc123",
  "prompt": "Create a midterm exam covering chapters 1-3",
  "num_tasks": 5,
  "allowed_task_types": ["QUIZ", "SHORT_ANSWER", "NUMBER_ANSWER"]
}
```

**Features**: Grounded on actual course content via RAG, answer-key validation (drops tasks with no correct answer), multi-turn refinement.

### 4. Interactive Scenario Generation

**Purpose**: Generate branching decision-tree scenarios for immersive learning.

**Endpoint**: `POST /ai/scenario/generate`

**Output** (ready to insert as `scenarios` block):
```json
{
  "title": "Ethical Dilemma Scenario",
  "scenarios": [
    {
      "id": "1",
      "text": "You discover a compliance violation. What do you do?",
      "imageUrl": "",
      "options": [
        {"id": "opt_abc", "text": "Report immediately", "nextScenarioId": "2"},
        {"id": "opt_def", "text": "Investigate further", "nextScenarioId": "3"}
      ]
    }
  ],
  "currentScenarioId": "1"
}
```

### 5. MagicBlocks (Per-Block AI Content)

**Purpose**: Generate HTML content for individual editor blocks via conversational AI.

**Endpoints**:
```
POST /ai/magicblocks/start    — Start block content session
POST /ai/magicblocks/message  — Iterate on block content (streaming)
```

### 6. AI Image Generation

**Endpoint**: `POST /ai/images/generate` — Generate course thumbnails and illustrations.

## Agent Workflow: Building a Complete Course

### Phase 1: Plan the Course Structure

```
1. Call POST /ai/courseplanning/start with:
   - Topic description
   - Target audience
   - Language preference
   - Any reference materials (YouTube URLs, documents)

2. Review the generated CoursePlan
3. Optionally iterate: POST /ai/courseplanning/iterate with refinements
4. Finalize: POST /ai/courseplanning/finalize
   → Returns course_uuid, chapter_uuids, activity_uuids
```

### Phase 2: Generate Activity Content

For each activity returned by finalize:

```
1. Call POST /ai/courseplanning/generate-activity with:
   - activity_uuid, activity_name, activity_description
   - chapter_name, course_name, course_description
   - Optional: additional instructions prompt

2. Parse the SSE stream into ProseMirror JSON
3. Review/edit the generated content
4. Save: POST /ai/courseplanning/save-activity-content
```

**Content generation tips**:
- The AI generates ProseMirror JSON with mixed block types
- Include `suggested_blocks` hints in the activity plan for better targeting
- YouTube embeds use `blockEmbed` with the video URL
- Quiz questions use `blockQuiz` with auto-generated IDs
- Flashcards use `flipcard` or `flipcardGrid` blocks

### Phase 3: Add Assessments

**Option A: Inline Quizzes (formative, within activities)**
```
For each activity that needs a knowledge check:
1. Call POST /ai/quiz/generate with:
   - activity_uuid (for content grounding)
   - prompt describing what to test
   - num_questions, difficulty
2. Insert the returned quiz into the activity's ProseMirror content
```

**Option B: Graded Assignments (summative)**
```
1. Create a TYPE_ASSIGNMENT activity in the target chapter
2. Call POST /ai/assignments/generate with:
   - course_uuid (for RAG grounding)
   - prompt describing the assessment scope
   - num_tasks, allowed_task_types
3. Save each returned task to the assignment
```

**Option C: Interactive Scenarios (experiential)**
```
1. Call POST /ai/scenario/generate with:
   - activity_uuid (for content grounding)
   - prompt describing the decision scenario
   - num_scenarios (number of branching nodes)
2. Insert the returned scenario block into the activity content
```

### Phase 4: Review and Publish

```
1. Review all generated content via the editor UI
2. Edit any content that needs refinement
3. Set activities to published=true
4. Set course to published=true, public=true (when ready)
```

## ProseMirror JSON Reference

### Document Structure
```json
{
  "type": "doc",
  "content": [
    { "type": "heading", "attrs": { "level": 1 }, "content": [...] },
    { "type": "paragraph", "content": [...] },
    ...
  ]
}
```

### Text Formatting (Marks)
```json
{ "type": "text", "marks": [{ "type": "bold" }], "text": "bold text" }
{ "type": "text", "marks": [{ "type": "italic" }], "text": "italic text" }
```
**IMPORTANT**: Use `"bold"` NOT `"strong"`, and `"italic"` NOT `"em"`.

### Quiz Block
```json
{
  "type": "blockQuiz",
  "attrs": {
    "quizId": null,
    "questions": [
      {
        "question_id": "q1",
        "question": "What is...?",
        "type": "multiple_choice",
        "response_type": "single",
        "answers": [
          { "answer_id": "a1", "answer": "Correct", "correct": true },
          { "answer_id": "a2", "answer": "Wrong", "correct": false }
        ]
      }
    ]
  }
}
```

### Flipcard
```json
{
  "type": "flipcard",
  "attrs": {
    "question": "What is photosynthesis?",
    "answer": "Process by which plants convert sunlight into energy",
    "color": "blue",
    "alignment": "center",
    "size": "medium"
  }
}
```

### Embed (YouTube)
```json
{
  "type": "blockEmbed",
  "attrs": {
    "embedUrl": "https://www.youtube.com/watch?v=VIDEO_ID",
    "embedType": "url",
    "embedHeight": 400,
    "embedWidth": "100%",
    "alignment": "center"
  }
}
```

### Callout
```json
{ "type": "calloutInfo", "content": [{ "type": "text", "text": "Key concept..." }] }
{ "type": "calloutWarning", "content": [{ "type": "text", "text": "Common mistake..." }] }
```

## Non-Negotiable Design Principles

These principles come from learning science and must govern every course an agent builds. The full research playbook is at `playbook-source.md` in this skill directory — read it for deeper context on any principle below.

### 1. Design for capability, not content coverage

Begin with: "What should the learner be able to **do**?" — not "What information should we include?"

Use observable outcome verbs: identify, distinguish, explain, classify, diagnose, choose, prioritize, calculate, demonstrate, interpret, compare, critique, produce, apply, troubleshoot, teach.

Avoid vague outcomes: know, understand, learn, appreciate, become familiar with, be aware of.

### 2. Use backward design

Design in this order:
1. **Outcome** — What should the learner be able to do?
2. **Evidence** — What would prove they can do it?
3. **Practice** — What practice would prepare them?
4. **Instruction** — What explanation/example/media do they need?
5. **Reinforcement** — How will they retrieve and reuse the skill later?

The objective, assessment, practice, and instruction must all target the **same capability**.

### 3. Learners must DO something with the material

Every meaningful unit must require one or more of: retrieve from memory, make a prediction, answer a question, make a decision, explain reasoning, compare examples, categorize cases, spot an error, complete a partial example, solve a problem, perform a procedure, create an artifact, reflect on performance, revise after feedback, apply learning in a new situation.

**A learner should not be able to finish an important course simply by scrolling and clicking Continue.**

### 4. Interactivity must have a learning purpose

Every interaction must do at least one useful job: activate prior knowledge, focus attention, check understanding, expose a misconception, create retrieval practice, provide guided practice, simulate a decision, provide feedback, support reflection, enable collaboration, or demonstrate transfer.

**The deletion test**: If we removed this interaction, would the learner think, practice, remember, or perform differently? If no, it's decorative.

### 5. Increase difficulty gradually

Progression: **Explain → Model → Guided practice → Faded support → Independent practice → Transfer**

For novices: clear instructions, worked examples, constrained choices, hints, checklists, immediate feedback.
As competence increases: fewer hints, incomplete examples, mixed problem types, ambiguity, realistic constraints, independent production.

### 6. Use retrieval, not just rereading

Learners should repeatedly try to recall important material **before looking at the answer**. Use: knowledge checks, flip cards, "write what you remember," low-stakes quizzes, classification tasks, "what would you do next?" scenarios, cumulative review.

Important ideas must return later in the course. Spacing schedule:
- Same activity: immediate check
- Next activity: short retrieval
- Next chapter: mixed review
- Final chapter: cumulative application

### 7. Feedback must help the learner improve

"Correct" and "Incorrect" are insufficient. Useful feedback answers:
1. What happened?
2. Why was the response strong or weak?
3. What principle applies?
4. What should the learner do differently next time?

### 8. Design for transfer

Learners should sometimes: distinguish similar situations, adapt a rule, use knowledge in a new example, diagnose an unfamiliar problem, make a decision with incomplete information, explain the idea to somebody else, create a realistic artifact.

A learner who can repeat the page is not necessarily able to use the skill.

## Interaction Selection Guide

Choose blocks based on the **learning job**, not aesthetics:

| Learning Job | Use These Blocks |
|---|---|
| **Retrieval** | Quiz, Flip Card, short answer, recall prompt |
| **Discrimination** | Misconception-based MCQ, H5P sorting, classification, scenario choice |
| **Decision-making** | Scenarios, branching H5P, Playground, case question |
| **Procedure** | Ordering task, interactive checklist, scenario, assignment, simulation |
| **Creation** | Assignment, file submission, Code Playground, written response |
| **Collaboration** | Discussion, Board, peer critique |
| **Exploration** | Playground, simulation, interactive visual model |
| **Reflection** | Formative assignment, short response, discussion, confidence + reasoning prompt |

## Default Learning Sequence

For each activity, use this structure (adapt, don't mechanically force every section):

```
1. ACTIVATE    — Connect to prior knowledge (prediction, mini-case, pretest, recall)
2. EXPLAIN     — Minimum information needed for the next step
3. MODEL       — Show an expert example with reasoning and why alternatives are weaker
4. GUIDED      — Let learner try with hints, partial steps, constrained options, feedback
5. INDEPENDENT — Reduce support
6. FEEDBACK    — Explain performance (reasoning, not just correct/incorrect)
7. REFLECT     — "What did you miss? Why? What clue mattered? What rule next time?"
8. RETRIEVE    — Bring the concept back later in the course
9. TRANSFER    — Use a fresh context
```

## Dynamic Page Structure Template

```markdown
# Lesson title

## Why this matters
Short context or scenario.

## By the end
You will be able to...

## Quick check
Prediction or retrieval from prior learning.

## The idea
Concise explanation.

## Example
Worked example, diagram, video, or annotated case.

## Your turn
Quiz, scenario, flip card, H5P, code task, or other practice.

## Feedback / compare
Reasoning, model answer, or debrief.

## Apply it
Second task with less support.

## Remember
3–5 important ideas.

## Before you move on
One retrieval or reflection prompt.
```

## Quiz Design Rules

### What each quiz is for (pick one per quiz)
- **Diagnostic** — Measures prior knowledge
- **Retrieval** — Strengthens memory
- **Formative** — Finds gaps and provides feedback
- **Mastery** — Determines readiness
- **Summative** — Measures final performance

### Multiple-choice quality rules
- One clear problem, one defensible best answer, plausible distractors, no accidental clues
- **Build distractors from real misconceptions**, not random wrong answers
- 3 strong options > 5 options with 2 implausible distractors
- Avoid: double negatives, trick wording, trivia, obviously ridiculous distractors, correct answer always being longest, grammatical clues, excessive "all/none of the above"

### Feedback on correct answers
Don't stop at "Correct." Add: "You confirmed the cause before selecting a corrective action. That sequence reduces the risk of solving the wrong problem."

### Feedback on wrong answers
Good: "Not quite. This action may be appropriate later, but it skips the confirmation step. Look for the option that reduces uncertainty before action."

### Cumulative assessment
Later assessments should revisit older objectives. Heuristic: 60% current chapter, 25% previous, 15% older material.

### Question QA checklist
- [ ] Maps to a stated objective
- [ ] Tests an important idea (not trivia)
- [ ] Stem clearly asks one question
- [ ] One answer is defensibly best
- [ ] Distractors are plausible and reflect real misconceptions
- [ ] Answer not revealed by grammar or length
- [ ] Feedback explains reasoning
- [ ] Accessibility acceptable

## Scenario Design Standards

A useful scenario contains:
1. Realistic context
2. Meaningful decision
3. Plausible alternatives (wrong answers must be plausible)
4. Consequences that teach rather than punish
5. Reasoning-based feedback
6. Debrief the general principle + transfer prompt

Do not signal the correct choice through wording. Include realistic uncertainty when judgment is part of the skill. Use authentic language from the environment where the skill will be applied.

## Assignment Design

Every assignment must communicate: Purpose, Task, Context, Deliverable, Success criteria, Example/model, Common errors, Feedback/revision path.

### Formative assignment pattern (powerful)
Submit → unlock model answer → compare → retry or reflect. Use for: writing, planning, worked problems, case analyses, self-evaluation, practice before graded performance.

### Rubrics
Describe visible performance. Weak: "Shows excellent understanding." Better: "Selects the appropriate method, explains why it fits the situation, and addresses the two major risks in the case."

## Reusable Learning Patterns

### Concept + Misconception
Present problem → Ask learner to choose → Surface misconception → Explain distinction → Show examples → New classification problem → Retrieve later.

### Demonstrate → Imitate → Perform
Expert demonstration → Annotated replay → Partial completion → Independent performance → Feedback → New case.

### Submit → Compare → Revise
Learner creates → Submits → Model answer unlocks → Compares → Identifies differences → Retries or reflects.

### Simulation → Debrief
State goal → Learner manipulates variables → Simulation displays consequences → Learner predicts → Explains pattern → Lesson names principle → Transfer question.

### Cumulative Challenge (end of chapter)
2 questions from current learning + 1 from previous chapter + 1 older retrieval + 1 integrated scenario.

## Anti-Patterns to Avoid

| Anti-Pattern | Symptom | Fix |
|---|---|---|
| **Textbook dump** | Huge reading pages, little practice, quiz only at end | Define skill milestones, cut low-value content, interleave explanation with practice |
| **Engagement theater** | Many clicks/cards/animation, little meaningful thinking | Require retrieval, decisions, explanation, production, feedback |
| **Trivia assessment** | Obscure dates, wording recall, unimportant definitions | Assess decisions and distinctions that matter in practice |
| **Obvious-answer MCQ** | One reasonable answer, silly alternatives | Build distractors from real misconceptions |
| **Final-assessment surprise** | Lessons teach definitions, final requires complex performance | Practice the same cognitive operations before the final |
| **Endless lecture** | Long uninterrupted video, no prediction/retrieval/practice | Segment, interleave learner action |
| **Over-scaffolding** | Every decision is obvious, learner never produces independently | Fade support progressively |
| **AI answer machine** | AI does the target skill, learner copies it | Use AI for questioning, hints, critique, practice generation, reflection |
| **Completion = mastery** | Clicking through is sufficient evidence | Require performance where outcomes require performance |

## Course Build Spec Template

When building a course, produce this specification first:

```yaml
project:
  platform: "LearnHouse"
  course_title: ""
  audience: ""
  delivery_mode: "self-paced | cohort | blended"

learning_problem:
  current_state: ""
  desired_state: ""
  real_world_context: ""
  consequences_of_failure: ""

course_outcomes:
  - id: CO1
    observable_outcome: ""
    mastery_standard: ""
    evidence: ""

learner_profile:
  prior_knowledge: []
  misconceptions: []
  motivations: []
  barriers: []
  likely_devices: [mobile, desktop]

design_rules:
  backward_design: true
  active_learning_required: true
  retrieval_practice_required: true
  cumulative_review_required: true
  authentic_practice_required: true
  accessibility_required: true
  mobile_first: true
  decorative_interactivity: false

assessment_rules:
  distractors_from_misconceptions: true
  one_best_answer_for_single_choice: true
  feedback_on_correct_answers: true
  feedback_on_incorrect_answers: true
  avoid_trivia: true
  application_assessed_with_application: true
  cumulative_retrieval: true
```

## Course QA Rubric (100 points)

### Alignment — 20
- Observable outcomes (5), Assessments match outcomes (5), Practice prepares for assessments (5), Content stays relevant (5)

### Learning Science — 20
- Retrieval (4), Spacing/cumulative review (4), Scaffolding/worked examples (4), Feedback (4), Transfer (4)

### Engagement — 15
- Relevance (3), Meaningful learner action (4), Appropriate autonomy (2), Realistic scenarios (3), Reflection/metacognition (3)

### Assessment Quality — 15
- Important skills assessed (4), Plausible distractors (3), Feedback quality (3), Authentic evidence (3), Retry/mastery logic (2)

### UX — 10
- Hierarchy/scannability (2), Consistency (2), Mobile usability (3), Low unnecessary cognitive load (3)

### Accessibility — 10
- Keyboard/focus (2), Captions/transcripts (2), Alt text (2), Contrast/non-color cues (2), Interaction alternatives (2)

### LearnHouse Implementation — 10
- Suitable blocks/activity types (3), Interactive features function (2), External dependencies documented (1), Trail/progress checked (1), Analytics plan (2), AI behavior reviewed (1)

**Scoring**: 90-100 = strong release candidate, 80-89 = targeted fixes, 70-79 = redesign weak areas, <70 = substantial redesign. A critical accessibility, factual, or assessment problem can block release regardless of total score.

## Course-Level Release Checklist

- [ ] Target learner is explicit
- [ ] Real-world capability is explicit
- [ ] Outcomes are observable
- [ ] Every chapter contributes to an outcome
- [ ] Every outcome has suitable evidence
- [ ] Assessments match objective level (application assessed with application, not just recall)
- [ ] Learners practice before major assessment
- [ ] Important learning is retrieved repeatedly
- [ ] Practice becomes progressively less supported
- [ ] Some learning is cumulative
- [ ] Transfer is assessed where relevant
- [ ] Feedback is actionable (explains reasoning, not just correct/incorrect)
- [ ] Accessibility checked (keyboard, captions, alt text, contrast, no color-only cues)
- [ ] Mobile behavior checked
- [ ] Interactive elements function
- [ ] Sources verified, no invented citations
- [ ] A pilot learner can state what they learned to **do**

## Agent Behavior Rules

- Do not invent platform features. Flag custom development.
- Show objective-to-assessment alignment.
- Explain the purpose of each interaction.
- Prefer fewer meaningful interactions over decorative ones.
- Do not mass-produce content before the design pattern is validated.
- Run QA before calling the course complete.
- AI must not silently defeat assessments (learner-facing AI should give hints before solutions, questions before explanations, critique before rewriting).
- Agents must not invent citations or LearnHouse capabilities.
- Validate quiz keys, distractors, and scenario logic.
- Surface uncertainty and preserve audit trail for source material.

## MKA Ilm Brand Considerations
- Content should align with MKA's voice: Reverent, Brotherly, Purposeful, Uplifting
- Use Amiri Quran font (Google Font) for Arabic content
- Respect Islamic content guidelines when generating religious material
- Tag courses appropriately for the MKA Ilm platform

## Error Handling

| Error | Cause | Resolution |
|-------|-------|------------|
| 403 insufficient credits | Org AI quota exhausted | Top up credits or wait for reset |
| 400 max iterations reached | Too many refinement rounds | Finalize current plan or start new session |
| 502 generation failed | LLM provider error | Retry; system auto-refunds credits |
| Empty quiz returned | Model produced no valid questions | Retry with more specific prompt |
| Content parse failure | Invalid ProseMirror JSON | Check block type names and structure |

## Key Source Files

| Area | Path |
|------|------|
| Course planning service | `apps/api/src/services/ai/courseplanning.py` |
| Course planning schemas | `apps/api/src/services/ai/schemas/courseplanning.py` |
| Quiz generation | `apps/api/src/services/ai/quiz.py` |
| Assignment generation | `apps/api/src/services/ai/assignment_gen.py` |
| Scenario generation | `apps/api/src/services/ai/scenario.py` |
| MagicBlocks | `apps/api/src/services/ai/magicblocks.py` |
| Content extraction (RAG) | `apps/api/src/services/ai/rag/content_extraction.py` |
| Course DB model | `apps/api/src/db/courses/courses.py` |
| Chapter DB model | `apps/api/src/db/courses/chapters.py` |
| Activity DB model | `apps/api/src/db/courses/activities.py` |
| Assignment DB model | `apps/api/src/db/courses/assignments.py` |
| Block DB model | `apps/api/src/db/courses/blocks.py` |
| Course planning router | `apps/api/src/routers/ai/courseplanning.py` |
| Frontend content gen | `apps/web/components/Objects/Modals/Course/Create/AICourse/ContentGenerationPanel.tsx` |
| Quiz block component | `apps/web/components/Objects/Editor/Extensions/Quiz/QuizBlockComponent.tsx` |
| Editor extensions | `apps/web/components/Objects/Editor/Extensions/` |
