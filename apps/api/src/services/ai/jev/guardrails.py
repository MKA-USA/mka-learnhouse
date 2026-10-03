"""Jev-powered output guardrails for LLM responses.

Screens LLM-generated content for hallucinations, PII, and inappropriate
material.  Designed for streaming responses: buffers the first ~500 chars,
runs Jev checks, then either proceeds or blocks with a warning.

Degrades gracefully: returns None (pass) when Jev is unavailable so the
caller proceeds without guardrails.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from config.config import get_learnhouse_config

logger = logging.getLogger(__name__)


@dataclass
class GuardrailResult:
    """Result of guardrail checks."""

    passed: bool
    reason: Optional[str] = None
    scores: Optional[dict] = None


def _build_client():
    """Import and construct the TypeSafe client.  Returns None on import error."""
    try:
        from typesafe_sdk import TypeSafeClient
        return TypeSafeClient()
    except ImportError:
        return None
    except Exception:
        logger.exception("Failed to initialise TypeSafe client for guardrails")
        return None


async def check_response_guardrails(
    response_text: str,
    *,
    user_question: str = "",
    source_context: str = "",
    timeout_seconds: float = 3.0,
) -> Optional[GuardrailResult]:
    """Check an LLM response for safety and quality issues.

    Returns ``GuardrailResult(passed=True)`` if the response is safe,
    ``GuardrailResult(passed=False, reason=...)`` if flagged, or ``None``
    if Jev is unavailable (caller should proceed without guardrails).
    """
    jev_cfg = get_learnhouse_config().jev_config
    if jev_cfg is None or not jev_cfg.enabled:
        return None

    client = _build_client()
    if client is None:
        return None

    try:
        from typesafe_sdk import Noul, Score
    except ImportError:
        return None

    state = {
        "llm_response": response_text[:2000],
    }
    if user_question:
        state["user_question"] = user_question[:500]
    if source_context:
        state["source_context"] = source_context[:2000]

    questions = {
        "has_pii": Noul(
            instructions="Does `llm_response` contain personally identifiable information "
                        "(email addresses, phone numbers, SSNs, passwords, credit cards)?",
        ),
        "is_inappropriate": Noul(
            instructions="Does `llm_response` contain inappropriate, toxic, or harmful content "
                        "for an educational setting?",
        ),
        "hallucination_risk": Score(
            instructions="How likely is `llm_response` to contain fabricated facts "
                        + ("not supported by `source_context`?" if source_context else "or unsupported claims?"),
            criteria=[
                "Low — sticks closely to provided context or well-known facts",
                "Medium — adds some unsourced details but nothing obviously wrong",
                "High — contains specific claims that seem fabricated or contradict context",
            ],
        ) if source_context else Noul(
            instructions="Does `llm_response` make specific factual claims that seem fabricated?",
        ),
    }

    def _call() -> GuardrailResult:
        response = client.system_one(state=state, questions=questions)
        pii_answer = response.answers.get("has_pii")
        inappropriate_answer = response.answers.get("is_inappropriate")
        hallucination_answer = response.answers.get("hallucination_risk")

        has_pii = bool(pii_answer.noul > 0.5) if pii_answer else False
        is_inappropriate = bool(inappropriate_answer.noul > 0.5) if inappropriate_answer else False

        # Hallucination check: Score or Noul depending on whether we have context
        hallucination_score = None
        hallucination_high = False
        if hallucination_answer:
            if hasattr(hallucination_answer, "score"):
                hallucination_score = float(hallucination_answer.score)
                hallucination_high = hallucination_score > 0.7
            else:
                # Noul fallback
                hallucination_high = bool(hallucination_answer.noul > 0.5)

        # Determine if response passes
        if has_pii:
            return GuardrailResult(
                passed=False,
                reason="PII detected",
                scores={"has_pii": pii_answer.noul if pii_answer else 0.0},
            )
        if is_inappropriate:
            return GuardrailResult(
                passed=False,
                reason="Inappropriate content",
                scores={"is_inappropriate": inappropriate_answer.noul if inappropriate_answer else 0.0},
            )
        if hallucination_high:
            return GuardrailResult(
                passed=False,
                reason="High hallucination risk",
                scores={"hallucination_risk": hallucination_score or 0.0},
            )

        return GuardrailResult(
            passed=True,
            scores={
                "has_pii": pii_answer.noul if pii_answer else 0.0,
                "is_inappropriate": inappropriate_answer.noul if inappropriate_answer else 0.0,
                "hallucination_risk": hallucination_score or 0.0,
            },
        )

    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_call),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "Jev guardrail check timed out after %.1fs; proceeding without guardrails",
            timeout_seconds,
        )
        return None
    except Exception:
        logger.exception("Jev guardrail check failed; proceeding without guardrails")
        return None
