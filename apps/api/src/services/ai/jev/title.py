"""Jev-powered chat title generation.

Replaces the fast-tier LLM call with a Jev Choice + Noul classification,
then assembles a short title from templates.  Faster (~100ms vs ~2-5s) and
cheaper, though slightly less creative than free-form generation.

Degrades gracefully: returns None when Jev is unavailable so the caller
falls back to the existing LLM-based title generation.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from config.config import get_learnhouse_config

logger = logging.getLogger(__name__)


# Template map: topic → title template
# {entity} is replaced with the extracted entity if available, otherwise omitted
_TITLE_TEMPLATES = {
    "concept_explanation": "Understanding {entity}",
    "practical_help": "Help with {entity}",
    "content_lookup": "Finding {entity}",
    "comparison": "Comparing {entity}",
    "definition": "What is {entity}?",
    "troubleshooting": "Fixing {entity}",
    "general_discussion": "Discussion: {entity}",
}

_FALLBACK_TITLES = {
    "concept_explanation": "Concept Explanation",
    "practical_help": "Practical Help",
    "content_lookup": "Content Lookup",
    "comparison": "Comparison",
    "definition": "Definition",
    "troubleshooting": "Troubleshooting",
    "general_discussion": "General Discussion",
}


def _build_client():
    """Import and construct the TypeSafe client.  Returns None on import error."""
    try:
        from typesafe_sdk import TypeSafeClient
        return TypeSafeClient()
    except ImportError:
        return None
    except Exception:
        logger.exception("Failed to initialise TypeSafe client for title generation")
        return None


async def generate_chat_title_jev(
    user_message: str,
    ai_response: str,
    *,
    timeout_seconds: float = 3.0,
) -> Optional[str]:
    """Generate a chat title via Jev classification + template assembly.

    Returns ``None`` if Jev is unavailable or the call fails — the caller
    should fall back to the existing LLM-based title generation.
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

    state = {
        "user_message": user_message[:300],
        "assistant_response": ai_response[:300],
    }

    questions = {
        "topic": Choice(
            instructions="What is the primary topic of this conversation?",
            criteria={
                "concept_explanation": "User asked about a concept and got an explanation",
                "practical_help": "User asked for help with a practical task or assignment",
                "content_lookup": "User asked to find specific content in the course",
                "comparison": "User asked to compare or contrast things",
                "definition": "User asked what something means or defined a term",
                "troubleshooting": "User described a problem and got help fixing it",
                "general_discussion": "Open-ended educational discussion",
            },
        ),
        "has_entity": Noul(
            instructions="Does the conversation center on a specific named entity "
                        "(person, tool, framework, concept, topic)?",
        ),
        "entity_name": Choice(
            instructions="If there is a specific entity, what is it?  Otherwise pick 'none'.",
            criteria={
                "react": "React, React hooks, React components",
                "python": "Python, Python code, Python programming",
                "photosynthesis": "Photosynthesis, plant biology",
                "machine_learning": "Machine learning, AI, neural networks",
                "database": "Database, SQL, PostgreSQL, MongoDB",
                "none": "No specific entity — general topic only",
            },
        ),
    }

    def _call() -> str:
        response = client.system_one(state=state, questions=questions)
        topic_answer = response.answers.get("topic")
        has_entity_answer = response.answers.get("has_entity")
        entity_answer = response.answers.get("entity_name")

        topic = topic_answer.choice if topic_answer else "general_discussion"
        has_entity = bool(has_entity_answer.noul > 0.5) if has_entity_answer else False
        entity = entity_answer.choice if entity_answer else "none"

        # Assemble title from template
        template = _TITLE_TEMPLATES.get(topic, _FALLBACK_TITLES.get(topic, "Discussion"))
        if has_entity and entity != "none":
            # Format entity name nicely
            entity_display = entity.replace("_", " ").title()
            title = template.format(entity=entity_display)
        else:
            title = _FALLBACK_TITLES.get(topic, "Discussion")

        return title[:60]

    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_call),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "Jev title generation timed out after %.1fs; falling back to LLM",
            timeout_seconds,
        )
        return None
    except Exception:
        logger.exception("Jev title generation failed; falling back to LLM")
        return None
