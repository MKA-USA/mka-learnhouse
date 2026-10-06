# LearnHouse Course Design Playbook
## Best practices for building interactive, thoughtful, well-designed, skill-building courses with coding agents

**Version:** 1.0  
**Updated:** October 4, 2026  
**Primary platform:** LearnHouse  
**Purpose:** A practical specification for humans and coding agents that design courses, lessons, quizzes, assignments, simulations, discussions, and learning experiences.

---

# 1. What this guide is for

This guide is designed to prevent a common failure mode in AI-generated courses: producing a lot of polished content that looks educational but does not reliably build a skill.

A strong course is not a collection of pages, videos, and quizzes. It is a **designed sequence of experiences that changes what a learner can do**.

The standard throughout this guide is:

> **The learner should leave able to perform, explain, decide, apply, or create something they could not reliably do before.**

Coding agents should use this document as a **design specification**, not merely as inspiration.

Every major design choice should trace back to:

1. a learner need,
2. a learning objective,
3. an evidence-based learning principle,
4. an appropriate LearnHouse capability, and
5. a measurable acceptance criterion.

---

# Part I — Non-negotiable design principles

## 2. Design for capability, not content coverage

Do not begin with:

> What information should we include?

Begin with:

> What should the learner be able to do?

A course can contain accurate information and still fail educationally if the learner is never required to use it.

### Prefer observable outcomes

Use verbs such as:

- identify
- distinguish
- explain
- classify
- diagnose
- choose
- prioritize
- calculate
- demonstrate
- interpret
- compare
- critique
- produce
- apply
- troubleshoot
- teach

Avoid vague outcomes such as:

- know
- understand
- learn
- appreciate
- become familiar with
- be aware of

---

## 3. Use backward design

Design in this order:

1. **Outcome** — What should the learner be able to do?
2. **Evidence** — What would prove they can do it?
3. **Practice** — What practice would prepare them?
4. **Instruction** — What explanation, example, or media do they need?
5. **Reinforcement** — How will they retrieve and reuse the skill later?

The objective, assessment, practice, and instruction should all measure or support the **same capability**.

### Example

Weak alignment:

- Objective: Apply a process in a realistic situation.
- Lesson: Read a five-page explanation.
- Assessment: Pick the definition of the process.

Strong alignment:

- Objective: Apply the process in a realistic situation.
- Lesson: Explanation + worked case.
- Practice: Guided scenario.
- Assessment: New scenario requiring independent application.

---

## 4. Learners must do something with the material

Reading and watching are inputs. Learning requires processing.

Every meaningful unit should require one or more of these actions:

- retrieve from memory
- make a prediction
- answer a question
- make a decision
- explain reasoning
- compare examples
- categorize cases
- spot an error
- complete a partial example
- solve a problem
- perform a procedure
- create an artifact
- reflect on performance
- revise after feedback
- apply learning in a new situation

A learner should not be able to finish an important course simply by scrolling and clicking **Continue**.

---

## 5. Interactivity must have a learning purpose

Do not add interactions simply to make the page feel interactive.

Every interaction should do at least one useful job:

- activate prior knowledge,
- focus attention,
- check understanding,
- expose a misconception,
- create retrieval practice,
- provide guided practice,
- simulate a decision,
- provide feedback,
- support reflection,
- enable collaboration,
- demonstrate transfer.

### The deletion test

Ask:

> If we removed this interaction, would the learner think, practice, remember, or perform differently?

If the answer is no, the interaction is probably decorative.

---

## 6. Increase difficulty gradually

A strong learning progression often looks like:

> **Explain → Model → Guided practice → Faded support → Independent practice → Transfer**

### For novices

Provide:

- clear instructions,
- worked examples,
- constrained choices,
- hints,
- checklists,
- step-by-step models,
- immediate feedback.

### As competence increases

Gradually introduce:

- fewer hints,
- incomplete examples,
- mixed problem types,
- ambiguity,
- realistic constraints,
- independent production,
- unfamiliar cases.

Do not leave scaffolding in place forever.

---

## 7. Use retrieval, not just rereading

Learners should repeatedly try to recall important material **before looking at the answer**.

Useful retrieval activities include:

- one- or two-question knowledge checks,
- flip cards,
- “write what you remember,”
- low-stakes quizzes,
- quick classification tasks,
- “what would you do next?” scenarios,
- cumulative review,
- recalling a procedure from memory.

Important ideas should return later in the course.

---

## 8. Space important learning across time

Do not teach a concept once and assume it has been learned permanently.

A useful retrieval schedule is:

- **same activity:** immediate check,
- **next activity:** short retrieval,
- **next chapter:** mixed review,
- **final chapter:** cumulative application,
- **later refresher:** optional delayed retrieval.

The exact interval matters less than ensuring that meaningful retrieval occurs again after some forgetting has begun.

---

## 9. Interleave related skills once foundations exist

Blocked practice:

> A → A → A → A → B → B → B → B

Interleaved practice:

> A → B → A → C → B → C

Interleaving becomes especially useful when the real skill involves identifying **which method or rule applies**.

Do not introduce heavy interleaving before novices understand each individual method.

---

## 10. Feedback must help the learner improve

“Correct” and “Incorrect” are usually insufficient.

Useful feedback should answer:

1. What happened?
2. Why was the response strong or weak?
3. What principle applies?
4. What should the learner do differently next time?

Focus feedback on:

- the task,
- the reasoning,
- the process,
- the strategy,
- the next action.

Avoid feedback focused on personal traits such as:

> You are naturally talented at this.

---

## 11. Reduce unnecessary cognitive load

Learners should spend mental effort on the **skill**, not on decoding the interface.

Avoid:

- dense walls of text,
- decorative media competing with the lesson,
- unnecessary background music,
- unexplained terminology,
- inconsistent page structures,
- excessive animation,
- redundant narration plus identical text,
- instructions separated from the activity,
- confusing navigation.

Prefer:

- concise sections,
- descriptive headings,
- whitespace,
- meaningful emphasis,
- examples close to explanations,
- visual cues,
- learner-controlled pacing,
- consistent patterns.

---

## 12. Design for transfer

Recall is useful, but many skills require transfer.

Learners should sometimes have to:

- distinguish similar situations,
- adapt a rule,
- use knowledge in a new example,
- diagnose an unfamiliar problem,
- make a decision with incomplete information,
- explain the idea to somebody else,
- create a realistic artifact,
- apply the same principle in a different context.

A learner who can repeat the page is not necessarily able to use the skill.

---

# Part II — Course planning

## 13. Define the learner before defining the outline

Coding agents should receive a learner model.

```yaml
learner:
  audience: ""
  age_range: ""
  prior_knowledge:
    required: []
    likely: []
    misconceptions: []
  motivation:
    why_they_care: ""
    likely_barriers: []
  context:
    device: "mobile | desktop | mixed"
    setting: "self-paced | cohort | workshop | blended"
    available_time: ""
  accessibility:
    known_needs: []
    design_for_variability: true
```

The designer should know:

- What can the learner already do?
- What are common misconceptions?
- Why would they care?
- Where will the skill be used?
- What happens when the skill is performed badly?
- What is the minimum useful mastery level?
- Are learners primarily novices or experienced?
- Are they likely to use phones?
- Is instructor feedback available?
- Is the course completed in one sitting or across days?

---

## 14. Write a performance-based course promise

Weak:

> Learn about effective communication.

Better:

> By the end of this course, you will be able to plan and deliver a five-minute briefing with a clear purpose, logical structure, and specific next action.

Useful formula:

> By the end of this course, learners will be able to **[perform an action]** in **[a realistic context]** to **[a defined quality standard]**.

---

## 15. Limit major course outcomes

A practical target is usually **3–7 major course outcomes**.

Example:

```yaml
course_outcomes:
  - id: CO1
    outcome: "Diagnose the most likely cause of a common failure from a short case."
    evidence: "Scenario-based assessment"

  - id: CO2
    outcome: "Apply the response process in the correct sequence."
    evidence: "Simulation and assignment"

  - id: CO3
    outcome: "Explain why each step matters."
    evidence: "Short explanation"
```

Every required chapter should contribute to at least one course outcome.

Every required activity should have a reason to exist.

---

## 16. Build the assessment blueprint before writing lessons

Map objective type to suitable evidence.

| Objective | Suitable evidence |
|---|---|
| Recall a fact | Retrieval question |
| Recognize a pattern | Classification |
| Explain a concept | Short explanation |
| Make a decision | Scenario |
| Perform a process | Simulation or assignment |
| Create something | Assignment |
| Diagnose a problem | Case analysis |
| Demonstrate judgment | Branching scenario |
| Collaborate | Board or structured discussion |
| Write code | Code Playground + test cases |

Never assess a high-level objective only with a lower-level recognition question.

---

## 17. Create a course map

Use a structure like:

| Chapter | Skill milestone | Evidence | Main experience | Retrieval |
|---|---|---|---|---|
| 1 | Recognize the problem | Classification | Dynamic Page | — |
| 2 | Explain the process | Short explanation | Dynamic Page + Quiz | Chapter 1 |
| 3 | Use with guidance | Scenario | Scenario/H5P | Chapters 1–2 |
| 4 | Use independently | Artifact | Assignment | Chapters 1–3 |
| 5 | Transfer | New case | Scenario/Playground | Cumulative |

The map should show progression in **capability**, not merely topic coverage.

---

# Part III — The skill-building loop

## 18. Default learning sequence

For many lessons, use:

### Activate
Connect to previous knowledge.

Examples:

- prediction,
- mini-case,
- one-question pretest,
- recall from previous lesson.

### Explain
Give the minimum information needed for the next step.

### Model
Show an expert example.

Include:

- the goal,
- the reasoning,
- the decision,
- why alternatives are weaker.

### Guided practice
Let the learner try with:

- hints,
- partial steps,
- constrained options,
- checklist,
- immediate feedback.

### Independent practice
Reduce support.

### Feedback
Explain performance.

### Reflection
Ask:

- What did you miss?
- Why?
- What clue mattered?
- What rule will you use next time?

### Retrieval
Bring the concept back later.

### Transfer
Use a fresh context.

---

## 19. Worked examples

Worked examples are especially useful for novices learning complex tasks.

A strong example contains:

1. problem,
2. goal,
3. relevant information,
4. reasoning,
5. procedure,
6. result,
7. explanation of why each major decision was made.

### Fade support progressively

**Example A:** completely worked  
**Example B:** one step missing  
**Example C:** several steps missing  
**Example D:** learner performs independently

---

## 20. Use self-explanation

Useful prompts:

- Why does this step come first?
- What clue mattered most?
- Why is option B tempting?
- Which principle did you apply?
- What would change if this detail changed?
- Explain the rule without copying the lesson.
- What mistake is being made in this example?

---

# Part IV — Lesson design

## 21. Recommended Dynamic Page structure

```markdown
# Lesson title

## Why this matters
Short context or scenario.

## By the end
You will be able to...

## Quick check
Prediction or retrieval.

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

Do not mechanically force every section into every page.

---

## 22. Keep activities focused

One activity should usually perform one coherent learning job:

- What is it?
- Why does it matter?
- How do I recognize it?
- How do I do it?
- How do I choose?
- Can I apply it?

If one activity tries to teach three independent skills, split it.

---

## 23. Video length

Do not treat a rigid duration as a law.

A useful principle is:

> **One video = one instructional purpose.**

Short instructional videos are usually preferable to uploading long lecture recordings unchanged.

Historically, edX guidance recommended roughly **3–7 minute instructional snippets** interleaved with exercises, while acknowledging that some demonstrations or topics require longer.

A 12-minute demonstration may be excellent.

A 45-minute lecture with no learner action is usually a weak default for self-paced instruction.

---

## 24. Write for the screen

Use:

- short paragraphs,
- descriptive headings,
- one main idea per paragraph,
- examples directly after concepts,
- restrained bolding,
- meaningful callouts,
- tables for genuine comparisons.

Avoid:

- enormous text blocks,
- excessive bold,
- deeply nested bullets,
- long introductions before meaningful content,
- repetitive summary paragraphs,
- unnecessary jargon.

Within the first screen, learners should understand:

> What am I learning and why?

---

# Part V — Purposeful interaction

## 25. Choose interactions according to the learning job

### Retrieval

Use:
- Quiz
- Flip Card
- short answer
- recall prompt

### Discrimination

Use:
- misconception-based multiple choice
- H5P sorting
- drag-and-drop
- classification Playground
- scenario choice

### Decision-making

Use:
- Scenarios
- branching H5P
- Playground
- case question

### Procedure

Use:
- ordering task
- interactive checklist
- scenario
- assignment
- simulation

### Creation

Use:
- Assignment
- file submission
- Board
- Code Playground
- written response

### Collaboration

Use:
- Discussion
- Board
- peer critique

### Exploration

Use:
- Playground
- simulation
- interactive visual model

### Reflection

Use:
- formative assignment
- short response
- discussion
- confidence + reasoning prompt

---

## 26. Do not manufacture interactions

The rule is not:

> A learner must click something every 60 seconds.

Instead ask:

> Has the learner recently retrieved, chosen, explained, practiced, predicted, compared, or applied anything?

If not, look for a meaningful interaction point.

---

## 27. Branching scenario design

A useful scenario contains:

1. realistic context,
2. meaningful decision,
3. plausible alternatives,
4. consequences,
5. reasoning-based feedback,
6. another decision or debrief.

```yaml
scenario:
  context: ""
  decision:
    prompt: ""
    options:
      - choice: ""
        consequence: ""
        feedback: ""
      - choice: ""
        consequence: ""
        feedback: ""
  debrief:
    principle: ""
    transfer_prompt: ""
```

### Scenario standards

- Wrong answers must be plausible.
- Do not signal the correct choice through wording.
- Consequences should teach rather than punish.
- Debrief the general principle.
- Include realistic uncertainty when judgment is part of the skill.
- Use authentic language from the environment where the skill will be applied.

---

## 28. LearnHouse Playgrounds

Use Playgrounds when manipulation or exploration adds learning value.

Good uses:

- simulations,
- adjustable models,
- decision tools,
- timelines,
- interactive diagrams,
- sorting systems,
- practice generators,
- process visualizers,
- “what happens if?” experiments.

Poor uses:

- visual effects with no instructional purpose,
- replacing a simple quiz with an unnecessarily complex widget,
- mouse-only interfaces,
- unlabelled experimentation,
- custom interactions without feedback.

### Playground spec

```yaml
playground:
  learning_objective: ""
  learner_action: ""
  variables: []
  expected_insight: ""
  feedback_logic: ""
  reset_behavior: true
  keyboard_usable: true
  mobile_usable: true
  text_alternative: true
```

---

# Part VI — LearnHouse design system

## 29. Platform architecture

Think in terms of:

> **Course → Chapters → Activities**

Activities can include:

- Dynamic Pages,
- Videos,
- Documents/PDFs,
- Assignments,
- Custom activities,
- SCORM where available.

Dynamic Pages can combine text, media, quizzes, and interactive blocks.

---

## 30. LearnHouse block selection

### Paragraph, headings, and lists

Use for:

- explanations,
- instructions,
- debriefs,
- framing,
- summaries.

### Code Block

Use when learners need to **read** code.

### Code Playground

Use when learners need to:

- write code,
- modify code,
- run it,
- test it,
- receive pass/fail results from test cases.

### Image

Use for:

- diagrams,
- comparison,
- visual evidence,
- screenshots,
- annotations,
- process maps.

### Video

Use for:

- demonstration,
- motion,
- walkthrough,
- storytelling,
- instructor presence.

### Audio

Use for:

- listening practice,
- pronunciation,
- interviews,
- reflective material,
- optional alternate modality.

### PDF

Prefer PDFs as references and downloads rather than as the only delivery format for essential learning.

### Embed

Use external content only when:

- it genuinely helps,
- it loads reliably,
- the destination permits embedding,
- accessibility is acceptable.

### Quiz

Use for:

- retrieval,
- misconception detection,
- discrimination,
- low-stakes practice.

### Flip Card

Use for brief retrieval.

Do not hide entire lecture paragraphs behind flip cards.

### Scenarios

Use for:

- judgment,
- consequences,
- decisions,
- application.

### H5P

Strong use cases include:

- interactive video,
- drag-and-drop,
- branching,
- ordering,
- course presentations,
- richer interaction.

Important platform consideration:

LearnHouse embeds H5P from an external H5P provider. The H5P provider—not LearnHouse—tracks the learner's internal H5P progress.

### Callout Info

Use for:

- remember,
- helpful context,
- important distinctions.

### Callout Warning

Use sparingly for:

- common mistakes,
- critical exceptions,
- safety or process warnings.

### Table

Use where structured comparison is easier to scan than prose.

---

## 31. Assignments

Use assignments when meaningful learning evidence requires production.

Possible evidence includes:

- written work,
- case analysis,
- file artifact,
- quiz task,
- short answer,
- code,
- numeric response,
- custom task.

Assignments may support:

- retries,
- grading,
- passing thresholds,
- automatic grading for supported task types,
- model answers,
- formative/no-grade workflows.

---

## 32. Formative assignment pattern

LearnHouse supports an especially useful workflow:

> **Submit → unlock model answer → compare → retry or reflect**

Good for:

- writing,
- planning,
- worked problems,
- case analyses,
- self-evaluation,
- reflection,
- practice before graded performance.

Do not assume everything valuable must receive a numerical score.

---

## 33. Discussions

Good uses:

- defend a decision,
- explain reasoning,
- compare approaches,
- commit to an answer before seeing peers,
- critique an example,
- share transfer examples.

Weak:

> What did you think of this lesson?

Strong:

> Which option would you choose in this case? Give two reasons from the lesson, then identify one condition that would make you change your choice.

---

## 34. Boards

LearnHouse Boards can support:

- collaborative planning,
- concept maps,
- workshops,
- group projects,
- visual case analysis,
- retrospectives,
- idea sorting,
- workflows.

Do not use a Board just because it looks collaborative. Give the collaboration a clear learning purpose.

---

## 35. Trails

Trails can help learners see:

- completed activities,
- quiz performance,
- overall progress.

Progress is useful for self-regulation.

Do not equate a completed Trail with demonstrated mastery.

---

## 36. Analytics

Use LearnHouse analytics to investigate:

- activity views,
- progress,
- interaction patterns,
- time spent,
- assignment behavior,
- course engagement,
- platform usage.

The purpose of analytics should be **course improvement**, not surveillance or rewarding time-on-page.

---

# Part VII — Quiz and assessment design

## 37. Decide what each quiz is for

### Diagnostic
Measures prior knowledge.

### Retrieval
Strengthens memory.

### Formative
Finds gaps and provides feedback.

### Mastery
Determines readiness.

### Summative
Measures final performance.

One quiz design should not automatically be reused for all five jobs.

---

## 38. Multiple-choice questions

A strong multiple-choice question has:

- one clear problem,
- one defensible best answer,
- plausible distractors,
- no accidental clues,
- content worth assessing.

### Use misconception-based distractors

Weak distractor:

> Eat lunch.

Strong distractor:

> Take corrective action before confirming the cause.

The second choice reflects a believable reasoning error.

### Avoid

- double negatives,
- trick wording,
- trivia,
- obviously ridiculous distractors,
- correct answer always being longest,
- two technically correct answers,
- grammatical clues,
- excessive use of “all of the above,”
- excessive use of “none of the above.”

### Option count

Three strong options can be better than five options containing two implausible distractors.

---

## 39. Scenario-based quiz format

```markdown
### Situation
[Short realistic case]

### Question
What is the best next action?

A. [plausible option]
B. [plausible option]
C. [best option]

### Feedback

**Best answer: C**

Why:
[reasoning]

Why A is tempting:
[misconception]

Why B is weaker:
[misconception]
```

---

## 40. Feedback on correct answers

Do not stop at:

> Correct.

Prefer:

> Correct. You confirmed the cause before selecting a corrective action. That sequence reduces the risk of solving the wrong problem.

Correct answers also deserve instructional feedback.

---

## 41. Feedback on wrong answers

Good:

> Not quite. This action may be appropriate later, but it skips the confirmation step. Look for the option that reduces uncertainty before action.

Bad:

> Incorrect. Try again.

---

## 42. Design retries for learning

Good retry patterns:

- similar but new item,
- scenario variation,
- hint ladder,
- explanation followed by retry,
- reflection before second attempt.

Weak:

- unlimited identical attempts,
- no feedback,
- easy answer-hunting.

---

## 43. Use cumulative assessment

Later assessments should revisit older objectives.

Example heuristic:

```yaml
quiz_mix:
  current_chapter: 60
  previous_chapter: 25
  older_material: 15
```

These percentages are not a universal law. The principle is cumulative retrieval.

---

## 44. Question QA checklist

- [ ] Maps to a stated objective.
- [ ] Tests an important idea.
- [ ] Stem clearly asks one question.
- [ ] One answer is defensibly best.
- [ ] Distractors are plausible.
- [ ] Distractors reflect real misconceptions.
- [ ] Answer is not revealed by grammar or length.
- [ ] Feedback explains reasoning.
- [ ] Does not test irrelevant trivia.
- [ ] Reading burden matches the skill.
- [ ] Accessibility is acceptable.
- [ ] Another reviewer has checked correctness.

---

# Part VIII — Authentic practice and assignments

## 45. Assess the real skill

If the outcome is:

- **writing** → write,
- **speaking** → speak or record,
- **diagnosing** → diagnose,
- **coding** → code,
- **planning** → produce a plan,
- **evaluating** → evaluate,
- **designing** → design.

Do not replace performance assessment with multiple choice merely because multiple choice is easier to grade.

---

## 46. Assignment specification

Every assignment should communicate:

1. **Purpose**
2. **Task**
3. **Context**
4. **Deliverable**
5. **Success criteria**
6. **Example/model where appropriate**
7. **Common errors**
8. **Feedback/revision path**

Template:

```markdown
## Purpose
This task practices...

## Your task
...

## Context
...

## Deliverable
Submit...

## Success criteria
Your work should:
- ...
- ...
- ...

## Before submitting
Check:
- ...
- ...
```

---

## 47. Rubrics

Rubrics should describe visible performance.

Weak:

> Shows excellent understanding.

Better:

> Selects the appropriate method, explains why it fits the situation, and addresses the two major risks in the case.

Assess the objectives rather than superficial polish unless polish is itself part of the skill.

---

## 48. Mastery learning

For foundational or critical skills:

1. define mastery,
2. assess,
3. identify gaps,
4. provide corrective instruction,
5. practice again,
6. reassess with a comparable task.

Allow additional time where appropriate.

Do not advance someone solely because they spent time on a page.

---

# Part IX — Multimedia design

## 49. Choose the simplest medium that teaches well

### Video is useful when:

- motion matters,
- timing matters,
- demonstration matters,
- human delivery matters,
- seeing the process is faster than describing it.

### Images are useful when:

- spatial relationships matter,
- visual comparison matters,
- diagrams simplify explanation,
- learners need to analyze visual evidence.

### Audio is useful when:

- the sound itself matters,
- listening is part of the skill,
- learners may benefit from an audio option,
- conversation adds instructional value.

### Text is useful when:

- precision matters,
- scanning matters,
- learners need a reference,
- information is easy to communicate in writing.

---

## 50. Apply multimedia-learning principles

### Coherence

Remove irrelevant material.

### Signaling

Use:

- headings,
- labels,
- arrows,
- emphasis,
- spoken cues.

Help learners identify what matters.

### Spatial contiguity

Put words near the visual they explain.

### Temporal contiguity

Synchronize related narration and visual events.

### Segmenting

Allow the learner to progress through complex explanations in manageable pieces.

### Pre-training

Introduce major components or terminology before explaining a complex system.

### Redundancy caution

Avoid forcing a learner to read a dense paragraph while hearing the identical paragraph spoken over a complex visual.

---

## 51. Video QA

- [ ] One instructional purpose.
- [ ] Relevance established quickly.
- [ ] Minimal unnecessary introduction.
- [ ] Important details visible on mobile.
- [ ] Captions available.
- [ ] Important captions manually reviewed.
- [ ] Learner can pause.
- [ ] Practice follows or precedes the video.
- [ ] Text support available when appropriate.
- [ ] Background music does not compete with speech.

LearnHouse can generate captions for hosted videos, but important names and technical terms should be manually reviewed.

---

# Part X — Visual and UX design

## 52. Clarity comes before decoration

The interface should make these answers obvious:

- Where am I?
- What am I learning?
- What should I do?
- What is most important?
- What happened after I responded?
- What comes next?

---

## 53. Use consistent visual hierarchy

```text
H1 — Activity title
H2 — Major section
H3 — Subsection
Body — Explanation
Callout — Important note
Practice — Learner action
Feedback — Response
```

Do not use heading levels only to change font size.

---

## 54. Build reusable page patterns

Standardize:

- activity introductions,
- objectives,
- worked examples,
- practice sections,
- callouts,
- warnings,
- debriefs,
- summaries,
- quiz feedback,
- assignments,
- chapter recaps.

Consistency reduces extraneous cognitive effort.

---

## 55. Design mobile-first

Check every important experience at phone width.

Inspect:

- text,
- headings,
- tables,
- video,
- images,
- quizzes,
- H5P,
- Playgrounds,
- Boards,
- buttons,
- tap targets,
- horizontal scrolling.

If a course requires desktop, say so explicitly.

---

# Part XI — Accessibility and inclusive design

## 56. Apply Universal Design for Learning

Design multiple means of:

- **engagement,**
- **representation,**
- **action and expression.**

The purpose is not to make three versions of every lesson.

The purpose is to remove avoidable barriers.

---

## 57. Accessibility baseline

### Keyboard use

Custom interactions should work without requiring a mouse.

### Visible focus

Keyboard focus must be visible.

### Contrast

Text, important controls, and states need sufficient contrast.

### Alt text

Write instructional alt text.

Weak:

> Image of a chart.

Better:

> Bar chart showing a sharp drop in completion after Activity 6.

### Captions

Videos containing speech should include captions.

### Transcripts

Provide transcripts when helpful for accessibility or review.

### No color-only information

Do not communicate correctness only through red and green.

### Avoid drag-only requirements

Where possible, provide alternate keyboard/control methods.

### Meaningful links

Use:

> Read the assessment guide

rather than:

> Click here

### Motion

Avoid unnecessary motion and support reduced-motion preferences in custom interfaces.

### Time

Do not impose strict timers unless speed is genuinely part of the skill.

---

## 58. Allow multiple forms of expression when appropriate

If the communication medium is not itself the skill, consider:

- text,
- audio,
- diagram,
- presentation,
- file,
- Board,
- code.

Do not offer alternatives that undermine the objective.

A writing course eventually has to assess writing.

---

# Part XII — Motivation and engagement

## 59. Lead with relevance

Weak:

> Welcome to Module 4. This module covers escalation procedures.

Stronger:

> You have five minutes to decide whether this problem can be handled locally or must be escalated. Which evidence should drive your choice?

Connect the skill to:

- learner goals,
- real decisions,
- real problems,
- real consequences.

---

## 60. Give meaningful autonomy

Useful:

- choose a case,
- choose a project,
- choose an optional challenge,
- choose an artifact format where format is not assessed.

Not useful:

- cosmetic choices that do not alter the learning experience.

---

## 61. Balance challenge and support

Avoid:

- trivial tasks that create boredom,
- impossible tasks requiring untaught skills.

Use scaffolding to create visible progress.

---

## 62. Use a respectful tone

Write as if learners are capable and expected to improve.

Avoid:

- sarcasm,
- trick questions,
- humiliation,
- “this is easy” language,
- condescension,
- assumptions about background knowledge.

Wrong answers should be treated as information useful for learning.

---

## 63. Design discussions around thinking

Strong prompts require a contribution.

Examples:

> Choose one approach and defend it with two pieces of evidence.

> Identify the step you are most likely to overlook and describe how you will remember it.

> Review one peer response. Identify one strength and one specific improvement.

Weak:

- Any thoughts?
- What did you think?
- Do you agree?
- What did you learn?

---

# Part XIII — AI-supported learning

## 64. AI should increase thinking rather than replace it

If a learner is supposed to build a capability, AI should not simply perform that capability for them.

Weak workflow:

> Ask AI to write your response.

Better:

1. learner creates first attempt,
2. AI asks diagnostic questions,
3. learner revises,
4. AI critiques using the rubric,
5. learner makes another revision,
6. learner explains the changes.

---

## 65. Recommended AI tutor modes

### Socratic coach

Ask one question at a time.

### Hint ladder

1. small cue,
2. stronger cue,
3. partial step,
4. full explanation only if needed.

### Error analyst

Ask the learner to explain their reasoning, then identify the first important reasoning error.

### Practice generator

Generate another case testing the same principle.

### Transfer coach

Generate a new surface context that requires the same underlying skill.

### Reflection coach

Ask:

- What did you miss?
- Why?
- What evidence should you notice next time?
- Which rule will you use?

---

## 66. AI guardrails

### Course-generation agents

Agents must:

- not invent citations,
- not invent LearnHouse capabilities,
- distinguish native features from custom development,
- validate quiz keys,
- validate distractors,
- validate scenario logic,
- test generated code,
- review generated media scripts,
- enforce project-specific source policies,
- surface uncertainty,
- preserve an audit trail for important source material.

### Learner-facing AI

Prefer:

- hints before solutions,
- questions before explanations,
- critique before rewriting,
- grounded course context,
- additional practice.

Do not let AI silently defeat assessments.

---

# Part XIV — Coding-agent course specification

## 67. Never prompt only: “Make a great course”

A vague request encourages the agent to invent:

- requirements,
- objectives,
- platform behavior,
- assessment rules,
- quality standards.

Use a specification.

LearnHouse itself uses an **Agent Spec** pattern for software development, including hard rules, API contracts, build order, and acceptance criteria.

Apply the same discipline to instructional design.

---

## 68. Master course-generation specification

```yaml
# COURSE BUILD SPEC

project:
  platform: "LearnHouse"
  course_title: ""
  audience: ""
  delivery_mode: "self-paced | cohort | blended"
  target_completion_time: ""

  source_policy:
    allowed_sources: []
    forbidden_sources: []
    citation_required: true

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
  likely_devices:
    - mobile
    - desktop

design_rules:
  backward_design: true
  active_learning_required: true
  retrieval_practice_required: true
  cumulative_review_required: true
  authentic_practice_required: true
  accessibility_required: true
  mobile_first: true
  decorative_interactivity: false

chapter_requirements:
  each_chapter:
    - "advances a skill milestone"
    - "retrieves earlier learning when appropriate"
    - "includes learner action beyond reading/watching"
    - "ends with evidence of progress"

activity_requirements:
  each_activity:
    - "states relevance early"
    - "maps to an objective"
    - "contains only necessary explanation"
    - "uses model/example when appropriate"
    - "contains practice"
    - "provides feedback or comparison"
    - "is scannable on mobile"
    - "passes accessibility QA"

assessment_rules:
  distractors_from_misconceptions: true
  one_best_answer_for_single_choice: true
  feedback_on_correct_answers: true
  feedback_on_incorrect_answers: true
  avoid_trivia: true
  application_assessed_with_application: true
  cumulative_retrieval: true

learnhouse_preferences:
  dynamic_page_for:
    - "mixed text/media/practice"

  quiz_for:
    - retrieval
    - misconception_checks

  flip_card_for:
    - short_retrieval

  scenarios_for:
    - judgment
    - decisions

  h5p_for:
    - sorting
    - drag_drop
    - interactive_video
    - branching

  playground_for:
    - simulation
    - interactive_visual_model

  assignment_for:
    - authentic_production
    - performance_evidence

  formative_assignment_for:
    - submit_then_compare

  board_for:
    - collaboration
    - mapping
    - workshops

  discussion_for:
    - reasoning
    - peer_explanation

  code_playground_for:
    - executable_programming_practice

agent_behavior:
  - "Do not invent platform features."
  - "Flag custom development."
  - "Show objective-to-assessment alignment."
  - "Explain the purpose of each interaction."
  - "Prefer fewer meaningful interactions over decorative ones."
  - "Do not mass-produce content before the design pattern is validated."
  - "Run QA before calling the course complete."

deliverables:
  - course_design_brief
  - assessment_blueprint
  - course_map
  - chapter_specs
  - activity_specs
  - quiz_bank
  - assignment_specs
  - rubrics
  - media_list
  - accessibility_report
  - mobile_report
  - analytics_plan
  - final_QA_report
```

---

# Part XV — Recommended agent build process

## 69. Stage 1 — Requirements

Produce:

- learner profile,
- skill gap,
- real-world context,
- course promise,
- prerequisites,
- course outcomes.

Do not draft full lessons yet.

---

## 70. Stage 2 — Evidence

Produce:

- assessment blueprint,
- evidence for every outcome,
- mastery standard,
- major rubric criteria.

---

## 71. Stage 3 — Course map

Produce:

- chapters,
- skill milestones,
- activity types,
- retrieval schedule,
- cumulative practice,
- transfer task.

---

## 72. Stage 4 — Prototype

Before generating the entire course, build representative examples:

- one Dynamic Page,
- one quiz,
- one scenario,
- one assignment,
- one Playground if needed,
- one discussion/Board activity if needed.

Review those patterns before scaling.

---

## 73. Stage 5 — Build

Use approved patterns to create the course.

Do not allow the agent to become less rigorous simply because it is generating content in bulk.

---

## 74. Stage 6 — QA

Run:

- instructional alignment review,
- quiz review,
- source verification,
- accessibility review,
- mobile review,
- interaction testing,
- platform compatibility review.

---

## 75. Stage 7 — Pilot

Where practical, test with a small learner group.

Observe:

- misunderstandings,
- slow points,
- drop-offs,
- incorrect choices,
- technical issues,
- unexpected interpretations.

Then revise.

---

# Part XVI — Acceptance criteria

## 76. Course-level release checklist

A course is not done until:

- [ ] Target learner is explicit.
- [ ] Real-world capability is explicit.
- [ ] Outcomes are observable.
- [ ] Every chapter contributes to an outcome.
- [ ] Required activities map to outcomes.
- [ ] Every outcome has suitable evidence.
- [ ] Assessments match objective level.
- [ ] Learners practice before major assessment.
- [ ] Important learning is retrieved repeatedly.
- [ ] Practice becomes progressively less supported.
- [ ] Some learning is cumulative.
- [ ] Transfer is assessed where relevant.
- [ ] Feedback is actionable.
- [ ] Accessibility has been checked.
- [ ] Mobile behavior has been checked.
- [ ] Media accessibility is handled.
- [ ] Interactive elements function.
- [ ] External embeds have been tested.
- [ ] H5P dependencies are documented.
- [ ] Playgrounds have appropriate alternatives/instructions.
- [ ] Analytics questions are defined.
- [ ] Sources have been verified.
- [ ] A pilot learner can state what they learned to **do**.

---

## 77. Activity-level release checklist

### Alignment

- [ ] Clear instructional purpose.
- [ ] Maps to an objective.
- [ ] No substantial irrelevant content.

### Learning

- [ ] Connects to prior learning where useful.
- [ ] Explanation is concise.
- [ ] Example/model included when appropriate.
- [ ] Learner performs an action.
- [ ] Feedback or comparison exists.
- [ ] Evidence of progress exists.

### UX

- [ ] Relevance is clear early.
- [ ] Headings are descriptive.
- [ ] Text is readable.
- [ ] Instructions are close to the interaction.
- [ ] Next step is obvious.

### Accessibility

- [ ] Keyboard usable.
- [ ] Focus visible.
- [ ] Useful alt text.
- [ ] Captions/transcripts addressed.
- [ ] No color-only communication.
- [ ] Interaction works at mobile width.

---

# Part XVII — Analytics and improvement

## 78. Start with questions, not dashboards

Before launch decide what you want analytics to tell you.

Examples:

- Where do learners stop?
- Which question exposes a misconception?
- Which activity takes unexpectedly long?
- Which rubric criterion is weakest?
- Do retries improve performance?
- Are instructions causing errors?
- Which scenario branch is most common?
- Do learners use optional assistance?
- Is mobile completion materially different?

---

## 79. Interpret analytics cautiously

High time spent may mean:

- engagement,
- confusion,
- difficulty,
- technical friction,
- abandoned browser tab.

Low time spent may mean:

- efficiency,
- prior mastery,
- skimming,
- abandonment.

High completion may mean:

- strong design,
- easy content,
- mandatory compliance.

Never interpret one metric in isolation.

---

## 80. Use item data diagnostically

If many learners miss a question, investigate:

1. Was the concept taught clearly?
2. Is the question ambiguous?
3. Is a distractor defensible?
4. Is the item harder than the objective?
5. Is prerequisite knowledge absent?
6. Was there enough practice?
7. Is terminology inconsistent?

Poor performance can reveal a **course design problem**.

---

## 81. Maintain a course changelog

```markdown
## v1.1
- Rewrote Lesson 2 example after many learners chose distractor B.
- Added retrieval from Chapter 1 to Chapter 3.
- Split one long video into three concept-focused videos.
- Added keyboard controls to the simulation.
- Replaced final definition quiz with a scenario assessment.
```

Treat courses as products that improve over time.

---

# Part XVIII — Anti-patterns

## 82. Textbook dump

Symptoms:

- huge reading pages,
- little practice,
- quiz only at the end.

Fix:

- define skill milestones,
- cut low-value content,
- interleave explanation with practice.

---

## 83. Engagement theater

Symptoms:

- many clicks,
- many cards,
- lots of animation,
- little meaningful thinking.

Fix:

- require retrieval,
- decisions,
- explanation,
- production,
- feedback.

---

## 84. Trivia assessment

Symptoms:

- obscure dates,
- wording recall,
- unimportant definitions.

Fix:

- assess decisions and distinctions that matter in practice.

---

## 85. Obvious-answer multiple choice

Symptoms:

- one reasonable answer,
- silly alternatives,
- correct answer much longer.

Fix:

- build distractors from real misconceptions.

---

## 86. Final-assessment surprise

Symptoms:

- lessons teach definitions,
- final requires complex performance.

Fix:

- practice the same cognitive operations before the final.

---

## 87. Endless lecture

Symptoms:

- long uninterrupted video,
- no prediction,
- no retrieval,
- no practice.

Fix:

- segment,
- interleave learner action.

---

## 88. Over-scaffolding

Symptoms:

- every decision is obvious,
- learner never produces independently.

Fix:

- fade support.

---

## 89. Inaccessible interactivity

Symptoms:

- mouse-only,
- drag-only,
- tiny controls,
- poor contrast,
- no labels,
- unusable on phones.

Fix:

- include accessibility in the specification before development.

---

## 90. AI answer machine

Symptoms:

- AI does the target skill,
- learner copies it,
- platform records completion.

Fix:

- use AI for:
  - questioning,
  - hints,
  - critique,
  - practice generation,
  - reflection.

---

## 91. Completion equals mastery

Symptoms:

- clicking through is sufficient evidence.

Fix:

- require performance where important outcomes require performance.

---

# Part XIX — Reusable learning patterns

## 92. Concept + misconception

1. Present a realistic problem.
2. Ask learner to choose.
3. Surface a common misconception.
4. Explain the distinction.
5. Show examples.
6. Give a new classification problem.
7. Retrieve later.

Use for concepts that are commonly confused.

---

## 93. Demonstrate → imitate → perform

1. Expert demonstration.
2. Annotated replay.
3. Partial completion.
4. Independent performance.
5. Feedback.
6. New case.

Use for procedures.

---

## 94. Case conference

1. Give a case.
2. Learner commits to a decision.
3. Learner explains reasoning.
4. Learner examines peers.
5. Model reasoning appears.
6. Learner revises.

Use for judgment and leadership.

---

## 95. Submit → compare → revise

Ideal with LearnHouse formative assignments:

1. learner creates,
2. learner submits,
3. model answer unlocks,
4. learner compares,
5. learner identifies differences,
6. learner retries or reflects.

Use for:

- writing,
- planning,
- case analysis,
- worked solutions.

---

## 96. Simulation → debrief

1. State goal.
2. Learner manipulates variables.
3. Simulation displays consequences.
4. Learner predicts next result.
5. Learner explains pattern.
6. Lesson names the principle.
7. Learner solves transfer question.

Use for causal or systems learning.

---

## 97. Cumulative challenge

At the end of a chapter:

- two questions from current learning,
- one from previous chapter,
- one older retrieval,
- one integrated scenario.

---

# Part XX — 100-point course QA rubric

## 98. Alignment — 20

- Observable outcomes: **5**
- Assessments match outcomes: **5**
- Practice prepares for assessments: **5**
- Content stays relevant: **5**

## 99. Learning science — 20

- Retrieval: **4**
- Spacing/cumulative review: **4**
- Scaffolding/worked examples: **4**
- Feedback: **4**
- Transfer: **4**

## 100. Engagement — 15

- Relevance: **3**
- Meaningful learner action: **4**
- Appropriate autonomy: **2**
- Realistic scenarios: **3**
- Reflection/metacognition: **3**

## 101. Assessment quality — 15

- Important skills assessed: **4**
- Plausible distractors: **3**
- Feedback quality: **3**
- Authentic evidence: **3**
- Retry/mastery logic: **2**

## 102. UX — 10

- Hierarchy/scannability: **2**
- Consistency: **2**
- Mobile usability: **3**
- Low unnecessary cognitive load: **3**

## 103. Accessibility — 10

- Keyboard/focus: **2**
- Captions/transcripts: **2**
- Alt text: **2**
- Contrast/non-color cues: **2**
- Interaction alternatives: **2**

## 104. LearnHouse implementation — 10

- Suitable blocks/activity types: **3**
- Interactive features function: **2**
- External dependencies documented: **1**
- Trail/progress behavior checked: **1**
- Analytics plan: **2**
- AI behavior reviewed: **1**

### Interpretation

**90–100:** strong release candidate  
**80–89:** targeted fixes before release  
**70–79:** redesign weak areas  
**Below 70:** substantial redesign

A critical accessibility, factual, or assessment problem can block release regardless of total score.

---

# Part XXI — Required coding-agent output

When an agent builds a course, require output in this order:

```markdown
# Course Design Brief
- Audience
- Problem
- Course promise
- Prerequisites
- Delivery assumptions

# Learning Outcomes

# Assessment Blueprint

# Course Map
| Chapter | Skill milestone | Evidence | Activities | Retrieval |

# Chapter 1

## Activity 1 Specification
- Objective
- LearnHouse type
- Expected learner effort
- Sequence
- Interaction
- Feedback
- Accessibility
- Analytics question

## Activity 2 Specification
...

# Quiz Bank

# Assignment Specifications

# Rubrics

# Media Production List

# Accessibility QA

# Mobile QA

# Analytics Plan

# Final Acceptance Test
```

This makes instructional decisions inspectable.

---

# Part XXII — Research and platform references

## Learning design

### Backward design

University of Illinois Chicago:  
https://teaching.uic.edu/cate-teaching-guides/syllabus-course-design/backward-design/

University of Michigan:  
https://onlineteaching.umich.edu/articles/alignment-of-your-assessments-and-learning-objectives/

### Spacing, retrieval, and worked examples

U.S. Institute of Education Sciences / What Works Clearinghouse:  
https://ies.ed.gov/ncee/wwc/PracticeGuide/1

Australian Education Research Organisation:  
https://www.edresearch.edu.au/guides-resources/practice-guides/spacing-and-retrieval-practice-guide-full-publication

### Active learning

Freeman et al., 2014:  
https://doi.org/10.1073/pnas.1319030111

### Multimedia learning

Cambridge Handbook of Multimedia Learning — reducing extraneous processing:  
https://www.cambridge.org/core/books/cambridge-handbook-of-multimedia-learning/principles-for-reducing-extraneous-processing-in-multimedia-learning/F29A19FCD34C542806F736E0661C05F5

Cambridge Handbook — segmenting and pre-training:  
https://www.cambridge.org/core/books/cambridge-handbook-of-multimedia-learning/principles-for-managing-essential-processing-in-multimedia-learning/A9E77D0172F905AC957689D1771E2888

### Quiz and assessment design

University of Waterloo:  
https://uwaterloo.ca/centre-for-teaching-excellence/catalogs/tip-sheets/designing-multiple-choice-questions

Carnegie Mellon University:  
https://www.cmu.edu/teaching/assessment/assesslearning/creatingexams.html

### Feedback and mastery

Education Endowment Foundation — Feedback:  
https://educationendowmentfoundation.org.uk/education-evidence/teaching-learning-toolkit/feedback

Education Endowment Foundation — Mastery learning:  
https://educationendowmentfoundation.org.uk/education-evidence/teaching-learning-toolkit/mastery-learning

### Universal Design for Learning

CAST UDL Guidelines 3.0:  
https://udlguidelines.cast.org/

### Accessibility

W3C WCAG 2.2:  
https://www.w3.org/TR/WCAG22/

### Online instructional video

edX course creation guidance:  
https://files.edx.org/Overview_of_Creating_an_Online_Course-V1.pdf

---

# LearnHouse references

## Platform

https://docs.learnhouse.app/platform

## Courses

https://docs.learnhouse.app/platform/courses

## Editor

https://docs.learnhouse.app/platform/editor

## Blocks

https://docs.learnhouse.app/platform/editor/blocks

## H5P

https://docs.learnhouse.app/platform/editor/h5p

## Assignments

https://docs.learnhouse.app/platform/assignments

## Formative assignments

https://docs.learnhouse.app/platform/assignments/formative

## Code execution

https://docs.learnhouse.app/platform/code-execution

## Playgrounds

https://docs.learnhouse.app/platform/playgrounds

## Discussions

https://docs.learnhouse.app/platform/discussions

## Boards

https://docs.learnhouse.app/platform/boards

## Trails

https://docs.learnhouse.app/platform/courses/trails

## Analytics

https://docs.learnhouse.app/platform/analytics

## AI for students

https://docs.learnhouse.app/platform/ai/for-students

## AI for teachers

https://docs.learnhouse.app/platform/ai/for-teachers

## Video captions

https://docs.learnhouse.app/platform/courses/video-captions

## LearnHouse Agent Spec

https://docs.learnhouse.app/guides/build-learning-platform/agent-spec

## Let an Agent Build It

https://docs.learnhouse.app/guides/build-learning-platform/with-an-agent

---

# Final standard

When reviewing any lesson, quiz, assignment, simulation, or course, ask:

> **What is the learner doing that causes learning to happen?**

If the answer is mainly:

> reading, watching, scrolling, and clicking Continue,

the course is not finished.

A strong course repeatedly creates this loop:

> **Think → Attempt → Feedback → Adjust → Retrieve → Apply**

That is the standard coding agents should optimize for.