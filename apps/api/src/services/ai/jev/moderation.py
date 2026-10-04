"""Jev-powered content moderation for user-generated content.

Screens user submissions (forum posts, assignment text, chat messages) for
toxicity, PII, spam, and academic integrity concerns.

Degrades gracefully: returns None (pass) when Jev is unavailable so the
caller proceeds without moderation.
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
        logger.exception("Failed to initialise TypeSafe client for moderation")
        return None


async def moderate_content(
    content: str,
    *,
    context: str = "general",  # "forum_post" | "assignment_submission" | "chat_message" | "general"
    timeout_seconds: float = 3.0,
) -> Optional[dict]:
    """Screen user-generated content for safety and policy violations.

    Returns a dict with moderation results or ``None`` if Jev is unavailable:
    {
        "passed": bool,
        "has_pii": bool,
        "is_toxic": bool,
        "is_spam": bool,
        "academic_integrity": str,  # "low" | "medium" | "high"
        "reasons": list[str],
    }
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
        "content": content[:3000],
        "context": context,
    }

    questions = {
        "has_pii": Noul(
            instructions="Does `content` contain personally identifiable information "
                        "(email addresses, phone numbers, SSNs, passwords, credit cards, home addresses)?",
        ),
        "is_toxic": Noul(
            instructions="Does `content` contain toxic, harassing, hateful, or abusive language?",
        ),
        "is_spam": Noul(
            instructions="Is `content` spam, promotional, or off-topic for an educational platform?",
        ),
    }

    # Add academic integrity check for assignment submissions
    if context == "assignment_submission":
        questions["academic_integrity"] = Score(
            instructions="How likely is this submission to be an academic integrity violation "
                        "(plagiarism, contract cheating, AI-generated without disclosure)?",
            criteria=[
                "Low — appears to be original student work",
                "Medium — some signs of copied content or unattributed sources",
                "High — strong indicators of plagiarism or undisclosed AI generation",
            ],
        )

    def _call() -> dict:
        response = client.system_one(state=state, questions=questions)
        pii_answer = response.answers.get("has_pii")
        toxic_answer = response.answers.get("is_toxic")
        spam_answer = response.answers.get("is_spam")
        integrity_answer = response.answers.get("academic_integrity")

        has_pii = bool(pii_answer.noul > 0.5) if pii_answer else False
        is_toxic = bool(toxic_answer.noul > 0.5) if toxic_answer else False
        is_spam = bool(spam_answer.noul > 0.5) if spam_answer else False

        academic_integrity = "low"
        if integrity_answer and hasattr(integrity_answer, "score"):
            score = float(integrity_answer.score)
            if score > 0.7:
                academic_integrity = "high"
            elif score > 0.4:
                academic_integrity = "medium"

        reasons = []
        if has_pii:
            reasons.append("Contains personally identifiable information")
        if is_toxic:
            reasons.append("Contains toxic or abusive language")
        if is_spam:
            reasons.append("Appears to be spam or promotional content")
        if academic_integrity == "high":
            reasons.append("High risk of academic integrity violation")

        passed = not (has_pii or is_toxic or is_spam) and academic_integrity != "high"

        return {
            "passed": passed,
            "has_pii": has_pii,
            "is_toxic": is_toxic,
            "is_spam": is_spam,
            "academic_integrity": academic_integrity,
            "reasons": reasons,
        }

    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_call),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "Jev content moderation timed out after %.1fs; proceeding without moderation",
            timeout_seconds,
        )
        return None
    except Exception:
        logger.exception("Jev content moderation failed; proceeding without moderation")
        return None
