"""Brand-compliant prompts for the Gemini image path (no tool-calling is possible there)."""

from __future__ import annotations

import json
import logging

from src.services.ai.mka_brand import breaker, config, toolset

logger = logging.getLogger(__name__)

DEFAULT_MODE = "morning-print"
TEXT_FREE_CLAUSE = (
    "Text-free: do not render any letters, words, numbers or Arabic script anywhere in the image."
)


def _negative(guardrails: str) -> str:
    """``globalNegativePrompt`` from the get_culture_guardrails JSON, or ''."""
    try:
        value = json.loads(guardrails).get("globalNegativePrompt")
    except (ValueError, AttributeError):
        return ""
    return value.strip() if isinstance(value, str) else ""


def _finish(prompt: str, max_chars: int, negative: str = "") -> str:
    # Add the global negative prompt unless the built prompt already carries it.
    extra = f" Avoid: {negative}" if negative and negative.lower() not in prompt.lower() else ""
    suffix = f"{extra} {TEXT_FREE_CLAUSE}"
    return prompt[: max(0, max_chars - len(suffix))] + suffix


async def brand_image_prompt(prompt: str, *, editing: bool = False, max_chars: int = 4000) -> str:
    """Return a brand-compliant image prompt, or the raw prompt (plus text-free clause) on any failure.

    Text-to-image goes through ``build_illustration_prompt`` and gets the guardrails' global
    negative prompt; edits only get the text-free clause (rebuilding the prompt would discard
    the user's edit instruction).
    """
    if not config.enabled():
        return prompt
    if editing or breaker.is_open():
        return _finish(prompt, max_chars)
    negative = ""
    try:
        negative = _negative(await toolset.call_tool_text("get_culture_guardrails", {}))
        built = await toolset.call_tool_text(
            "build_illustration_prompt",
            {"brand": config.brand(), "mode": DEFAULT_MODE, "subject": prompt},
        )
        # The tool returns the prompt first, then the rules applied and the layout contract.
        first = built.split("\n\n")[0].strip() if built else ""
        if not first or "rejected" in first.lower()[:80]:
            return _finish(prompt, max_chars, negative)
        return _finish(first, max_chars, negative)
    except Exception as exc:  # noqa: BLE001 (fail-open)
        breaker.trip(type(exc).__name__)
        return _finish(prompt, max_chars, negative)
