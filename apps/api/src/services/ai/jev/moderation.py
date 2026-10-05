"""Jev-powered content moderation for user-generated content (advisory).

Screens text (forum posts, assignment submissions, chat messages) for PII,
toxicity, spam, and (assignment submissions only) academic-integrity concerns.
Consumed by ``services/moderation_ai`` (flag recording for staff review).

Scores are normalized to 0..1.  Noul answers are already probabilities.  The
integrity Score (3-level rubric, raw 0..2) is normalized as
``score / (levels - 1)`` and bucketed: high >= 0.67, medium >= 0.34, else low.

The derived ``action`` is only ``allow`` or ``flag``; this module never blocks.
Fail-open: returns ``None`` when Jev is unavailable/disabled/incomplete.
Nothing in content is logged.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.services.ai.jev.client import jev_enabled, run_system_one

NOUL_FLAG_THRESHOLD = 0.5
INTEGRITY_HIGH_NORM = 0.67
INTEGRITY_MEDIUM_NORM = 0.34
CONTENT_MAX_CHARS = 3000


@dataclass
class ModerationResult:
    """Normalized (0..1) moderation scores plus a derived action."""

    pii: float
    toxicity: float
    spam: float
    academic_integrity: float | None  # None unless kind == "assignment_submission"
    integrity_level: str  # "low" | "medium" | "high"
    action: str  # "allow" | "flag"
    reasons: list[str] = field(default_factory=list)


def integrity_level(norm: float | None) -> str:
    if norm is None:
        return "low"
    if norm >= INTEGRITY_HIGH_NORM:
        return "high"
    if norm >= INTEGRITY_MEDIUM_NORM:
        return "medium"
    return "low"


async def moderate_content(
    text: str,
    *,
    kind: str = "general",  # "forum_post" | "assignment_submission" | "chat_message" | "general"
    org_id: int | None = None,
) -> ModerationResult | None:
    """Screen *text*.  Returns ``None`` if Jev is unavailable (fail-open).

    If *org_id* is given the org opt-in is checked here too.
    """
    if not text or not text.strip():
        return None
    if org_id is not None and not jev_enabled(org_id):
        return None

    try:
        from typesafe_sdk import Noul, Score
    except Exception:  # noqa: BLE001 - SDK missing/broken: fail open
        return None

    check_integrity = kind == "assignment_submission"
    state = {"content": text[:CONTENT_MAX_CHARS], "kind": kind}
    questions: dict = {
        "pii": Noul(
            instructions="Does `content` contain personally identifiable information "
            "(email addresses, phone numbers, SSNs, passwords, credit cards, home addresses)?",
        ),
        "toxicity": Noul(
            instructions="Does `content` contain toxic, harassing, hateful, or abusive language?",
        ),
        "spam": Noul(
            instructions="Is `content` spam, promotional, or off-topic for an educational platform?",
        ),
    }
    if check_integrity:
        questions["academic_integrity"] = Score(
            instructions="How likely is this submission to be an academic integrity violation "
            "(plagiarism, contract cheating, AI-generated without disclosure)?",
            criteria=[
                "Low: appears to be original student work",
                "Medium: some signs of copied content or unattributed sources",
                "High: strong indicators of plagiarism or undisclosed AI generation",
            ],
        )

    result = await run_system_one(state, questions, capability="moderation")
    if result is None:
        return None

    pii = result.noul("pii")
    toxicity = result.noul("toxicity")
    spam = result.noul("spam")
    if pii is None or toxicity is None or spam is None:
        return None

    integrity: float | None = None
    if check_integrity:
        integrity = result.score_norm("academic_integrity")
        if integrity is None:
            return None
    level = integrity_level(integrity)

    reasons: list[str] = []
    if pii > NOUL_FLAG_THRESHOLD:
        reasons.append("Contains personally identifiable information")
    if toxicity > NOUL_FLAG_THRESHOLD:
        reasons.append("Contains toxic or abusive language")
    if spam > NOUL_FLAG_THRESHOLD:
        reasons.append("Appears to be spam or promotional content")
    if level == "high":
        reasons.append("High risk of academic integrity violation")

    return ModerationResult(
        pii=pii,
        toxicity=toxicity,
        spam=spam,
        academic_integrity=integrity,
        integrity_level=level,
        action="flag" if reasons else "allow",
        reasons=reasons,
    )
