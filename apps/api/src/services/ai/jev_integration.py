"""Call-site glue for the optional Jev (TypeSafe) integration.

Lives outside ``services/ai/jev/`` and keeps upstream routers/services down to
tiny additive hunks. Every helper is a no-op unless Jev is enabled *and* the
organization is on the explicit ``allowed_org_ids`` allow-list, and none of
them can raise into the request path. Neither user content nor the API key is
ever logged here.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

from config.config import get_learnhouse_config

logger = logging.getLogger(__name__)

# Strong references to in-flight fire-and-forget tasks. asyncio only keeps weak
# references to tasks, so an unreferenced task can be garbage collected mid-run.
_background_tasks: set[asyncio.Task] = set()


def _cfg():
    return get_learnhouse_config().jev_config


def _spawn(coro: Coroutine[Any, Any, Any]) -> None:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def schedule_guardrail_audit(
    response: str,
    *,
    user_question: str,
    org_id: int | None,
    source_context: str = "",
    chat_id: str | None = None,
) -> None:
    """Fire-and-forget output audit. Never awaited by the caller, never raises."""
    try:
        from src.services.ai.jev.client import jev_enabled

        cfg = _cfg()
        if cfg is None or not cfg.guardrails_enabled or not jev_enabled(org_id):
            return
        from src.services.ai.jev.guardrails import audit_response

        _spawn(
            audit_response(
                response,
                user_question=user_question,
                source_context=source_context,
                org_id=org_id,
                label=chat_id or "",
            )
        )
    except Exception as exc:  # noqa: BLE001 - fail open by design
        logger.debug("Jev guardrail audit not scheduled: %s", type(exc).__name__)


async def should_route_to_general(
    message: str,
    *,
    org_id: int | None,
    mode: str | None,
    course_name: str = "",
    history: list | None = None,
) -> bool:
    """True when Jev is confident the question is general knowledge.

    The caller then switches the chat to ``general`` mode: retrieval still runs,
    but the course-only grounding is loosened so the model may answer from its
    own knowledge. Opt-in via ``intent_routing_enabled``. Routing applies ONLY
    when the client sent no ``mode`` (``None``); any explicit choice, including
    ``course_only``, is always respected. Any failure resolves to False.
    """
    if mode is not None:
        return False
    try:
        from src.services.ai.jev.client import jev_enabled

        cfg = _cfg()
        if cfg is None or not cfg.intent_routing_enabled or not jev_enabled(org_id):
            return False
        from src.services.ai.jev.router import classify_question, is_confident_general_knowledge

        result = await classify_question(
            message, course_name=course_name, history=history
        )
        return bool(result is not None and is_confident_general_knowledge(result))
    except Exception as exc:  # noqa: BLE001 - fail open by design
        logger.debug("Jev intent routing skipped: %s", type(exc).__name__)
        return False


async def validate_generated_quiz(
    questions: list[dict], *, org_id: int | None, course_content: str = ""
) -> None:
    """Log-only batched quiz validation. Can never fail quiz generation."""
    try:
        from src.services.ai.jev.client import jev_enabled

        cfg = _cfg()
        if cfg is None or not cfg.quiz_validation_enabled or not jev_enabled(org_id):
            return
        from src.services.ai.jev.quality import validate_quiz_questions

        results = await validate_quiz_questions(
            questions, course_content=course_content
        )
        if results is None:
            return
        failed = sum(1 for r in results if r is not None and not r.get("passed", True))
        unscored = sum(1 for r in results if r is None)
        log = logger.warning if failed else logger.info
        log(
            "Jev quiz validation: %d/%d questions flagged, %d unscored",
            failed, len(results), unscored,
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - fail open by design
        logger.debug("Jev quiz validation skipped: %s", type(exc).__name__)
