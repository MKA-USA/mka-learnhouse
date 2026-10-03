"""TypeSafe Jev client wrapper.

Thin abstraction over the TypeSafe SDK so the rest of the codebase never
imports ``typesafe_sdk`` directly.  Every public function degrades gracefully:
if the SDK is missing, the API key is unset, or the call times out, the caller
gets ``None`` and falls back to its existing behaviour.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Sequence

from config.config import get_learnhouse_config, JevConfig

logger = logging.getLogger(__name__)


@dataclass
class RerankResult:
    """One chunk's reranking score from Jev."""

    index: int
    score: float
    confidence: float


def _get_jev_config() -> JevConfig | None:
    cfg = get_learnhouse_config().jev_config
    if cfg is None or not cfg.enabled:
        return None
    return cfg


def _build_client():
    """Import and construct the TypeSafe client.  Returns None on import error."""
    try:
        from typesafe_sdk import TypeSafeClient
        return TypeSafeClient()
    except ImportError:
        logger.warning(
            "typesafe-sdk not installed; Jev reranking disabled. "
            "Install with: pip install typesafe-sdk"
        )
        return None
    except Exception:
        logger.exception("Failed to initialise TypeSafe client")
        return None


async def jev_rerank_chunks(
    question: str,
    chunks: Sequence[str],
    *,
    timeout_seconds: float = 5.0,
) -> list[RerankResult] | None:
    """Score each chunk's relevance to *question* via Jev.

    Returns a list of ``RerankResult`` sorted by score descending, or ``None``
    if Jev is unavailable / the call failed.  The caller should fall back to
    the original ordering on ``None``.

    All chunks are scored in a single batched request (parallel questions).
    """
    jev_cfg = _get_jev_config()
    if jev_cfg is None or not jev_cfg.rerank_enabled:
        return None

    if not chunks:
        return None

    client = _build_client()
    if client is None:
        return None

    try:
        from typesafe_sdk import Score
    except ImportError:
        return None

    state: dict = {"user_question": question}
    questions: dict = {}
    for i, chunk_text in enumerate(chunks):
        state[f"chunk_{i}"] = chunk_text[:2000]
        questions[f"rel_{i}"] = Score(
            instructions=(
                f"How relevant is `chunk_{i}` to the student's question `user_question`?"
            ),
            criteria=[
                "Not relevant — different topic entirely.",
                "Tangentially related — same domain but doesn't answer the question.",
                "Partially relevant — some useful info but not a direct answer.",
                "Highly relevant — directly answers or substantially addresses the question.",
            ],
        )

    def _call() -> list[RerankResult]:
        response = client.system_one(state=state, questions=questions)
        results: list[RerankResult] = []
        for i in range(len(chunks)):
            answer = response.answers.get(f"rel_{i}")
            if answer is None:
                results.append(RerankResult(index=i, score=0.0, confidence=0.0))
            else:
                results.append(RerankResult(
                    index=i,
                    score=float(answer.score),
                    confidence=float(answer.confidence),
                ))
        results.sort(key=lambda r: r.score, reverse=True)
        return results

    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_call),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "Jev reranking timed out after %.1fs; falling back to vector ordering",
            timeout_seconds,
        )
        return None
    except Exception:
        logger.exception("Jev reranking failed; falling back to vector ordering")
        return None
