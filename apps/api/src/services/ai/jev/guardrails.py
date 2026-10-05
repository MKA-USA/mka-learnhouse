"""Jev-powered audit of LLM responses (log-only).

Screens a *finished* LLM response for PII, inappropriate content, and
hallucination risk.  This is an after-the-fact audit: it never blocks or
alters what the student already received.  ``audit_response`` is meant to run
as a fire-and-forget background task; it swallows every error.

Fail-open (deliberate): when Jev is unavailable, times out, or omits an
answer, nothing is flagged.  Guardrails here are a monitoring signal, not an
enforcement point.

Logs contain flag names and scores only, never response/question content.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.services.ai.jev.client import jev_enabled, run_system_one

logger = logging.getLogger(__name__)

NOUL_FLAG_THRESHOLD = 0.5
# Hallucination rubric has 3 levels (0..2); flag when the normalized score
# (score / (levels - 1)) is >= 0.67, i.e. raw score >= ~1.34 (leaning "High").
HALLUCINATION_FLAG_NORM = 0.67

RESPONSE_MAX_CHARS = 2000
QUESTION_MAX_CHARS = 500
CONTEXT_MAX_CHARS = 2000


@dataclass
class GuardrailResult:
    """Result of guardrail checks."""

    passed: bool
    reason: str | None = None
    scores: dict | None = None


async def check_response_guardrails(
    response_text: str,
    *,
    user_question: str = "",
    source_context: str = "",
    timeout: float | None = None,
) -> GuardrailResult | None:
    """Check an LLM response; ``None`` means Jev was unavailable (fail-open).

    Callers must gate on ``jev_enabled(org_id)`` / ``guardrails_enabled``.
    """
    try:
        from typesafe_sdk import Noul, Score
    except Exception:  # noqa: BLE001 - SDK missing/broken: fail open
        return None

    state: dict = {"llm_response": response_text[:RESPONSE_MAX_CHARS]}
    if user_question:
        state["user_question"] = user_question[:QUESTION_MAX_CHARS]
    if source_context:
        state["source_context"] = source_context[:CONTEXT_MAX_CHARS]

    questions: dict = {
        "has_pii": Noul(
            instructions="Does `llm_response` contain personally identifiable information "
            "(email addresses, phone numbers, SSNs, passwords, credit cards)?",
        ),
        "is_inappropriate": Noul(
            instructions="Does `llm_response` contain inappropriate, toxic, or harmful content "
            "for an educational setting?",
        ),
    }
    if source_context:
        questions["hallucination_risk"] = Score(
            instructions="How likely is `llm_response` to contain fabricated facts "
            "not supported by `source_context`?",
            criteria=[
                "Low: sticks closely to provided context or well-known facts",
                "Medium: adds some unsourced details but nothing obviously wrong",
                "High: contains specific claims that seem fabricated or contradict context",
            ],
        )
    else:
        questions["hallucination_risk"] = Noul(
            instructions="Does `llm_response` make specific factual claims that seem fabricated?",
        )

    result = await run_system_one(state, questions, capability="guardrails", timeout=timeout)
    if result is None:
        return None

    scores: dict[str, float] = {}
    reasons: list[str] = []

    pii = result.noul("has_pii")
    if pii is not None:
        scores["has_pii"] = pii
        if pii > NOUL_FLAG_THRESHOLD:
            reasons.append("PII detected")

    inappropriate = result.noul("is_inappropriate")
    if inappropriate is not None:
        scores["is_inappropriate"] = inappropriate
        if inappropriate > NOUL_FLAG_THRESHOLD:
            reasons.append("Inappropriate content")

    if source_context:
        halluc = result.score_norm("hallucination_risk")
        flagged = halluc is not None and halluc >= HALLUCINATION_FLAG_NORM
    else:
        halluc = result.noul("hallucination_risk")
        flagged = halluc is not None and halluc > NOUL_FLAG_THRESHOLD
    if halluc is not None:
        scores["hallucination_risk"] = halluc
        if flagged:
            reasons.append("High hallucination risk")

    if reasons:
        return GuardrailResult(passed=False, reason="; ".join(reasons), scores=scores)
    return GuardrailResult(passed=True, scores=scores)


async def audit_response(
    response_text: str,
    *,
    user_question: str = "",
    source_context: str = "",
    org_id: int | None = None,
    label: str = "",
) -> None:
    """Background audit: run the checks and log the verdict.  Never raises
    (except ``CancelledError``) and never logs content.

    If *org_id* is given, the org opt-in is re-checked here as a safety net.
    """
    try:
        if not response_text or not response_text.strip():
            return
        if org_id is not None and not jev_enabled(org_id):
            return
        result = await check_response_guardrails(
            response_text,
            user_question=user_question,
            source_context=source_context,
        )
        if result is None:
            return
        tag = f" [{label}]" if label else ""
        if result.passed:
            logger.debug("Jev guardrail audit passed%s scores=%s", tag, result.scores)
        else:
            logger.warning(
                "Jev guardrail audit flagged response%s: %s scores=%s",
                tag, result.reason, result.scores,
            )
    except Exception as exc:  # noqa: BLE001 - background task must never raise
        logger.warning("Jev guardrail audit error (%s)", type(exc).__name__)
