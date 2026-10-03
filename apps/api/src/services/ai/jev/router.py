"""Jev-powered query intent classification.

Classifies a student's question to decide whether the RAG pipeline is needed
or the LLM can answer directly from general knowledge.  Degrades gracefully:
returns ``None`` when Jev is unavailable so the caller falls through to the
default RAG pipeline.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from config.config import get_learnhouse_config

logger = logging.getLogger(__name__)


@dataclass
class QuestionIntent:
    """Result of intent classification."""

    intent: str  # content_lookup | concept_explanation | practical_help | general_knowledge | meta_question | clarification
    needs_rag: bool
    is_followup: bool


def _build_client():
    """Import and construct the TypeSafe client.  Returns None on import error."""
    try:
        from typesafe_sdk import TypeSafeClient
        return TypeSafeClient()
    except ImportError:
        return None
    except Exception:
        logger.exception("Failed to initialise TypeSafe client for routing")
        return None


async def classify_question(
    question: str,
    *,
    course_name: str = "",
    timeout_seconds: float = 5.0,
) -> Optional[QuestionIntent]:
    """Classify a student question's intent.

    Returns ``None`` if Jev is unavailable or the call fails — the caller
    should fall through to the default RAG pipeline.
    """
    jev_cfg = get_learnhouse_config().jev_config
    if jev_cfg is None or not jev_cfg.enabled:
        return None

    client = _build_client()
    if client is None:
        return None

    try:
        from typesafe_sdk import Choice, Noul
    except ImportError:
        return None

    state: dict = {"user_question": question}
    if course_name:
        state["course_name"] = course_name

    questions = {
        "intent": Choice(
            instructions=(
                "What does the student need from `user_question`?"
                + (" The course is `course_name`." if course_name else "")
            ),
            criteria={
                "content_lookup": "Finding specific content, a topic, or a section in the course",
                "concept_explanation": "Understanding a concept or idea from the course material",
                "practical_help": "Help with an assignment, exercise, or practical task related to the course",
                "general_knowledge": "A question beyond the course scope that needs general knowledge to answer",
                "meta_question": "About the course itself — deadlines, grading, logistics, schedule",
                "clarification": "Asking to clarify, simplify, or re-explain something from a previous turn",
            },
        ),
        "needs_rag": Noul(
            instructions=(
                "Does answering `user_question` require retrieving specific course content?"
            ),
        ),
        "is_followup": Noul(
            instructions=(
                "Is `user_question` a follow-up to a previous conversation turn "
                "(e.g. 'can you explain that more', 'what about the second one', 'thanks')?"
            ),
        ),
    }

    def _call() -> QuestionIntent:
        response = client.system_one(state=state, questions=questions)
        intent_answer = response.answers.get("intent")
        needs_rag_answer = response.answers.get("needs_rag")
        is_followup_answer = response.answers.get("is_followup")

        return QuestionIntent(
            intent=intent_answer.choice if intent_answer else "concept_explanation",
            needs_rag=bool(needs_rag_answer.noul > 0.5) if needs_rag_answer else True,
            is_followup=bool(is_followup_answer.noul > 0.5) if is_followup_answer else False,
        )

    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_call),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "Jev intent classification timed out after %.1fs; using default RAG pipeline",
            timeout_seconds,
        )
        return None
    except Exception:
        logger.exception("Jev intent classification failed; using default RAG pipeline")
        return None
