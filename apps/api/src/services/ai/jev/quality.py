"""Jev-powered quiz quality validation.

Validates AI-generated quiz questions for correctness, clarity, and quality
before returning them to the user.  Checks answer keys, question clarity,
and distractor plausibility.

Degrades gracefully: returns None (pass) when Jev is unavailable so the
caller proceeds without validation.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from config.config import get_learnhouse_config

logger = logging.getLogger(__name__)


def _build_client():
    """Import and construct the TypeSafe client.  Returns None on import error."""
    try:
        from typesafe_sdk import TypeSafeClient
        return TypeSafeClient()
    except ImportError:
        return None
    except Exception:
        logger.exception("Failed to initialise TypeSafe client for quiz validation")
        return None


async def validate_quiz_question(
    question_text: str,
    answers: list[dict],  # [{"answer": str, "correct": bool}, ...]
    *,
    course_content: str = "",
    timeout_seconds: float = 3.0,
) -> Optional[dict]:
    """Validate a single quiz question for quality.

    Returns a dict with validation results or ``None`` if Jev is unavailable:
    {
        "passed": bool,
        "question_clear": bool,
        "answer_key_correct": bool,
        "distractor_quality": str,  # "poor" | "fair" | "good"
        "issues": list[str],
    }
    """
    jev_cfg = get_learnhouse_config().jev_config
    if jev_cfg is None or not jev_cfg.enabled:
        return None

    client = _build_client()
    if client is None:
        return None

    try:
        from typesafe_sdk import Noul, Score, Choice
    except ImportError:
        return None

    # Format answers for the prompt
    correct_answers = [a["answer"] for a in answers if a.get("correct")]
    incorrect_answers = [a["answer"] for a in answers if not a.get("correct")]

    state = {
        "quiz_question": question_text,
        "correct_answers": ", ".join(correct_answers) if correct_answers else "none marked",
        "incorrect_answers": ", ".join(incorrect_answers) if incorrect_answers else "none",
    }
    if course_content:
        state["course_content"] = course_content[:3000]

    questions = {
        "question_clear": Noul(
            instructions="Is `quiz_question` unambiguous and clearly worded? "
                        "Could a student understand what is being asked without confusion?",
        ),
        "answer_key_correct": Noul(
            instructions="Are the answers marked as correct (`correct_answers`) actually correct "
                        + ("given `course_content`?" if course_content else "based on general knowledge?"),
        ),
        "distractor_quality": Choice(
            instructions="How plausible are the incorrect answers (`incorrect_answers`) as distractors?",
            criteria={
                "poor": "Obviously wrong — no student would pick them",
                "fair": "Somewhat plausible but easily eliminated by careful reading",
                "good": "Genuinely plausible distractors that test real understanding",
            },
        ),
        "content_aligned": Noul(
            instructions="Is this question actually based on `course_content`?"
        ) if course_content else Noul(
            instructions="Is this question factually accurate and appropriate for an educational setting?",
        ),
    }

    def _call() -> dict:
        response = client.system_one(state=state, questions=questions)
        clear_answer = response.answers.get("question_clear")
        key_answer = response.answers.get("answer_key_correct")
        distractor_answer = response.answers.get("distractor_quality")
        aligned_answer = response.answers.get("content_aligned")

        question_clear = bool(clear_answer.noul > 0.5) if clear_answer else True
        answer_key_correct = bool(key_answer.noul > 0.5) if key_answer else True
        distractor_quality = distractor_answer.choice if distractor_answer else "fair"
        content_aligned = bool(aligned_answer.noul > 0.5) if aligned_answer else True

        issues = []
        if not question_clear:
            issues.append("Question is ambiguous or unclear")
        if not answer_key_correct:
            issues.append("Answer key appears incorrect")
        if distractor_quality == "poor":
            issues.append("Distractors are too obviously wrong")
        if not content_aligned:
            issues.append("Question not aligned with course content")

        return {
            "passed": question_clear and answer_key_correct and content_aligned,
            "question_clear": question_clear,
            "answer_key_correct": answer_key_correct,
            "distractor_quality": distractor_quality,
            "issues": issues,
        }

    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_call),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "Jev quiz validation timed out after %.1fs; proceeding without validation",
            timeout_seconds,
        )
        return None
    except Exception:
        logger.exception("Jev quiz validation failed; proceeding without validation")
        return None
