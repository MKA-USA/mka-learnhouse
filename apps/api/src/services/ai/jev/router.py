"""Jev-powered query intent classification.

Classifies a student's question to decide whether the chat may switch from
``course_only`` to ``general`` mode.  Retrieval itself still runs; ``general``
only loosens the course-only grounding prompt so the model may answer from its
own knowledge.  Fails toward the default: ``None`` (Jev unavailable) or anything
short of a confident ``general_knowledge`` verdict keeps ``course_only``.

Callers must gate on ``jev_enabled(org_id)`` and the ``intent_routing_enabled``
config flag before calling.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from src.services.ai.jev.client import run_system_one

# Loosen grounding only on a confident, clearly out-of-scope verdict.
SKIP_RAG_MIN_CHOICE_CONFIDENCE = 0.7
SKIP_RAG_MAX_NEEDS_RAG = 0.2

HISTORY_MAX_TURNS = 4
HISTORY_MAX_CHARS_PER_TURN = 300
QUESTION_MAX_CHARS = 500


@dataclass
class QuestionIntent:
    """Result of intent classification (only the fields callers use)."""

    intent: str  # content_lookup | concept_explanation | practical_help | general_knowledge | meta_question | clarification
    intent_confidence: float  # 0..1 confidence in ``intent``
    needs_rag: float  # 0..1 probability the answer needs course content


def is_confident_general_knowledge(result: QuestionIntent | None) -> bool:
    """True only when Jev is confident the question is general knowledge.

    ``intent == general_knowledge`` AND choice confidence >= 0.7 AND
    needs_rag probability < 0.2.  Anything else (including ``None``) is False,
    i.e. stay in the default ``course_only`` mode.
    """
    if result is None:
        return False
    return (
        result.intent == "general_knowledge"
        and result.intent_confidence >= SKIP_RAG_MIN_CHOICE_CONFIDENCE
        and result.needs_rag < SKIP_RAG_MAX_NEEDS_RAG
    )


def _turn_parts(turn: Any) -> tuple[str, str] | None:
    if isinstance(turn, dict):
        role, content = turn.get("role"), turn.get("content")
    elif isinstance(turn, (tuple, list)) and len(turn) == 2:
        role, content = turn
    else:
        role, content = getattr(turn, "role", None), getattr(turn, "content", None)
    if not isinstance(content, str) or not content.strip():
        return None
    return str(role or "user"), content.strip()


def _format_history(history: Sequence[Any] | None) -> str:
    if not history:
        return ""
    lines = []
    for turn in list(history)[-HISTORY_MAX_TURNS:]:
        parts = _turn_parts(turn)
        if parts is None:
            continue
        role, content = parts
        lines.append(f"{role}: {content[:HISTORY_MAX_CHARS_PER_TURN]}")
    return "\n".join(lines)


async def classify_question(
    question: str,
    *,
    course_name: str = "",
    history: Sequence[Any] | None = None,
    timeout: float | None = None,
) -> QuestionIntent | None:
    """Classify a student question's intent.

    *history* is the recent chat (dicts with ``role``/``content``, or objects
    with those attributes); the last ~4 turns are included, truncated, so
    follow-ups like "explain that more" are not misread as general knowledge.

    Returns ``None`` if Jev is unavailable, the call fails, or an answer is
    missing; the caller keeps the default RAG pipeline.
    """
    try:
        from typesafe_sdk import Choice, Noul
    except Exception:  # noqa: BLE001 - SDK missing/broken: fail open
        return None

    state: dict = {"user_question": question[:QUESTION_MAX_CHARS]}
    if course_name:
        state["course_name"] = course_name[:200]
    history_text = _format_history(history)
    if history_text:
        state["recent_conversation"] = history_text

    followup_hint = (
        " Take `recent_conversation` into account: a follow-up to earlier turns "
        "is about the same subject as those turns."
        if history_text
        else ""
    )

    questions = {
        "intent": Choice(
            instructions=(
                "What does the student need from `user_question`?"
                + (" The course is `course_name`." if course_name else "")
                + followup_hint
            ),
            criteria={
                "content_lookup": "Finding specific content, a topic, or a section in the course",
                "concept_explanation": "Understanding a concept or idea from the course material",
                "practical_help": "Help with an assignment, exercise, or practical task related to the course",
                "general_knowledge": "A question beyond the course scope that needs general knowledge to answer",
                "meta_question": "About the course itself: deadlines, grading, logistics, schedule",
                "clarification": "Asking to clarify, simplify, or re-explain something from a previous turn",
            },
        ),
        "needs_rag": Noul(
            instructions="Does answering `user_question` require retrieving specific course content?"
            + followup_hint,
        ),
    }

    result = await run_system_one(state, questions, capability="intent", timeout=timeout)
    if result is None:
        return None

    choice = result.choice("intent")
    needs_rag = result.noul("needs_rag")
    if choice is None or needs_rag is None:
        return None

    return QuestionIntent(intent=choice[0], intent_confidence=choice[1], needs_rag=needs_rag)
