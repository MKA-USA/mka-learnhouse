"""Jev-powered quiz quality validation (advisory).

Validates AI-generated quiz questions for clarity, answer-key correctness,
distractor plausibility, and content alignment.  Questions are validated in
batched Jev requests of up to ``CHUNK_SIZE`` questions (question ids
``q{i}_{criterion}``, ``i`` local to the chunk); a quiz of <= CHUNK_SIZE
questions is a single request.

Fail-open: returns ``None`` when Jev is unavailable so the caller proceeds
without validation.  Callers must gate on ``jev_enabled(org_id)`` and the
``quiz_validation_enabled`` config flag.
"""

from __future__ import annotations

import asyncio
import logging

from src.services.ai.jev.client import run_system_one

logger = logging.getLogger(__name__)

# Each question sends 4 judgments and the client rejects >64 judgments per
# request (client.MAX_QUESTIONS), so 16 questions per call is the ceiling.
CHUNK_SIZE = 16
MAX_QUESTIONS = 64  # hard cap on total questions validated (4 chunks)
CHUNK_CONCURRENCY = 2
COURSE_CONTENT_MAX_CHARS = 3000
YES_THRESHOLD = 0.5

_CRITERIA = ("clear", "key", "distractors", "aligned")


def _question_text(q: dict) -> str:
    return str(q.get("question") or q.get("question_text") or q.get("text") or "")


async def validate_quiz_questions(
    questions: list[dict],  # [{"question": str, "answers": [{"answer": str, "correct": bool}, ...]}, ...]
    *,
    course_content: str = "",
    timeout: float | None = None,
) -> list[dict | None] | None:
    """Validate questions in chunked Jev calls (one call when <= CHUNK_SIZE).

    Returns ``None`` if Jev is unavailable/failed, otherwise a list aligned
    with *questions*.  Each entry is a dict (or ``None`` when Jev omitted any
    of that question's answers, or the question was beyond ``MAX_QUESTIONS``, or its chunk failed)::

        {
            "passed": bool,  # clear AND key correct AND aligned AND distractors != "poor"
            "question_clear": bool,
            "answer_key_correct": bool,
            "distractor_quality": str,  # "poor" | "fair" | "good"
            "content_aligned": bool,
            "issues": list[str],
        }
    """
    if not questions:
        return None

    try:
        import typesafe_sdk  # noqa: F401
    except Exception:  # noqa: BLE001 - SDK missing/broken: fail open
        return None

    batch = questions[:MAX_QUESTIONS]
    chunks = [batch[i : i + CHUNK_SIZE] for i in range(0, len(batch), CHUNK_SIZE)]
    sem = asyncio.Semaphore(CHUNK_CONCURRENCY)

    async def _one(chunk: list[dict]) -> list[dict | None] | None:
        async with sem:
            try:
                return await _validate_chunk(chunk, course_content, timeout)
            except Exception:  # noqa: BLE001 - fail open per chunk
                return None

    results = await asyncio.gather(*(_one(c) for c in chunks))
    if len(chunks) == 1:
        # Single call: preserve the "None when Jev failed" contract.
        return results[0]
    if all(r is None for r in results):
        return None
    out: list[dict | None] = []
    for chunk, res in zip(chunks, results):
        out.extend(res if res is not None else [None] * len(chunk))
    out.extend([None] * (len(questions) - len(batch)))
    return out


async def _validate_chunk(
    batch: list[dict], course_content: str, timeout: float | None
) -> list[dict | None] | None:
    from typesafe_sdk import Choice, Noul

    has_content = bool(course_content)

    state: dict = {}
    if has_content:
        state["course_content"] = course_content[:COURSE_CONTENT_MAX_CHARS]

    qs: dict = {}
    for i, q in enumerate(batch):
        answers = q.get("answers") or []
        correct = [str(a.get("answer", "")) for a in answers if a.get("correct")]
        incorrect = [str(a.get("answer", "")) for a in answers if not a.get("correct")]
        state[f"q{i}_question"] = _question_text(q)
        state[f"q{i}_correct_answers"] = ", ".join(correct) if correct else "none marked"
        state[f"q{i}_incorrect_answers"] = ", ".join(incorrect) if incorrect else "none"

        qs[f"q{i}_clear"] = Noul(
            instructions=f"Is `q{i}_question` unambiguous and clearly worded? "
            "Could a student understand what is being asked without confusion?",
        )
        qs[f"q{i}_key"] = Noul(
            instructions=f"Are the answers marked as correct (`q{i}_correct_answers`) for `q{i}_question` "
            "actually correct "
            + ("given `course_content`?" if has_content else "based on general knowledge?"),
        )
        qs[f"q{i}_distractors"] = Choice(
            instructions=f"How plausible are the incorrect answers (`q{i}_incorrect_answers`) "
            f"as distractors for `q{i}_question`?",
            criteria={
                "poor": "Obviously wrong: no student would pick them",
                "fair": "Somewhat plausible but easily eliminated by careful reading",
                "good": "Genuinely plausible distractors that test real understanding",
            },
        )
        qs[f"q{i}_aligned"] = Noul(
            instructions=(
                f"Is `q{i}_question` actually based on `course_content`?"
                if has_content
                else f"Is `q{i}_question` factually accurate and appropriate for an educational setting?"
            ),
        )

    result = await run_system_one(state, qs, capability="quiz", timeout=timeout)
    if result is None:
        return None

    out: list[dict | None] = []
    for i in range(len(batch)):
        clear = result.noul(f"q{i}_clear")
        key = result.noul(f"q{i}_key")
        distractors = result.choice(f"q{i}_distractors")
        aligned = result.noul(f"q{i}_aligned")
        if clear is None or key is None or distractors is None or aligned is None:
            out.append(None)
            continue

        question_clear = clear > YES_THRESHOLD
        answer_key_correct = key > YES_THRESHOLD
        content_aligned = aligned > YES_THRESHOLD
        distractor_quality = distractors[0]

        issues: list[str] = []
        if not question_clear:
            issues.append("Question is ambiguous or unclear")
        if not answer_key_correct:
            issues.append("Answer key appears incorrect")
        if distractor_quality == "poor":
            issues.append("Distractors are too obviously wrong")
        if not content_aligned:
            issues.append(
                "Question not aligned with course content"
                if has_content
                else "Question may be inaccurate or inappropriate"
            )

        out.append({
            "passed": question_clear and answer_key_correct and content_aligned and distractor_quality != "poor",
            "question_clear": question_clear,
            "answer_key_correct": answer_key_correct,
            "distractor_quality": distractor_quality,
            "content_aligned": content_aligned,
            "issues": issues,
        })
    return out
