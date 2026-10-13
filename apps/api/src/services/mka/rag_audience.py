"""MKA fork: audience sections (``mkaAudience`` ProseMirror nodes) never enter the shared per-course RAG index.

The RAG index is shared by every learner of a course, so text only some learners may see must not be embedded at all
(retrieval-time filtering is not possible: chunks carry no audience). ``install()`` is called once from the end of
``services/ai/rag/sources/__init__.py`` (the single upstream hook, logged in ``.codebase-memory/upstream-modifications.md``).
Every extraction goes through that package, so web, queue consumer, scheduler and CLI backfill all get it. It:

1. registers a no-op handler for ``mkaAudience`` in the upstream ProseMirror walker (``dynamic._NODE_HANDLERS``), and
2. wraps every registered source extractor: when ``activity.content`` contains an audience node, the extractor sees a COPY of
   the content with all audience nodes (and descendants) removed, and any segment tied to an uploaded block (pdf, audio,
   video, image, custom) that is referenced from inside an audience section is dropped. Activities without audience nodes
   are passed through untouched.

Fail closed: if stripping raises, the extractor result is replaced by nothing (the activity stays findable by name only).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

AUDIENCE_TYPE = "mkaAudience"
_WRAPPED = "_mka_audience_wrapped"


def contains_audience(value: Any) -> bool:
    """Iterative scan (no recursion limit to trip over) for an audience node anywhere in a JSON value."""
    stack = [value]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if node.get("type") == AUDIENCE_TYPE:
                return True
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return False


def strip_audience(value: Any) -> Any:
    """Copy of ``value`` with every audience node removed (iterative; arbitrary depth). Input is never mutated."""
    if isinstance(value, dict) and value.get("type") == AUDIENCE_TYPE:
        return None
    root: Any = [] if isinstance(value, list) else {} if isinstance(value, dict) else value
    stack = [(value, root)]
    while stack:
        src, dst = stack.pop()
        items = enumerate(src) if isinstance(src, list) else src.items()
        for key, child in items:
            if isinstance(child, dict) and child.get("type") == AUDIENCE_TYPE:
                continue
            if isinstance(child, (dict, list)):
                copy: Any = [] if isinstance(child, list) else {}
                stack.append((child, copy))
                child = copy
            if isinstance(dst, list):
                dst.append(child)
            else:
                dst[key] = child
    return root


def restricted_strings(value: Any) -> set[str]:
    """Every string inside any audience node. Block ids referenced from a restricted section show up here."""
    out: set[str] = set()
    stack = [(value, False)]
    while stack:
        node, inside = stack.pop()
        if isinstance(node, dict):
            inside = inside or node.get("type") == AUDIENCE_TYPE
            stack.extend((child, inside) for child in node.values())
        elif isinstance(node, list):
            stack.extend((child, inside) for child in node)
        elif inside and isinstance(node, str):
            out.add(node)
    return out


def _noop_audience(node: dict, parts: list) -> None:
    """Walker handler: an audience section contributes nothing (its children are never visited)."""


class _ActivityView:
    """Read-only stand-in for an Activity whose ``content`` is replaced; everything else is delegated. The ORM row is never touched."""

    def __init__(self, activity: Any, content: Any):
        object.__setattr__(self, "_activity", activity)
        object.__setattr__(self, "content", content)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._activity, name)


def _guard(extractor):
    if getattr(extractor, _WRAPPED, False):
        return extractor

    async def guarded(activity, ctx):
        content = getattr(activity, "content", None)
        if not contains_audience(content):
            return await extractor(activity, ctx)
        try:
            restricted = restricted_strings(content)
            view = _ActivityView(activity, strip_audience(content))
        except Exception:  # noqa: BLE001 - fail closed: nothing from an activity we could not filter
            logger.exception("MKA RAG audience guard failed for activity %s; indexing none of its content", getattr(activity, "id", "?"))
            return []
        segments = await extractor(view, ctx)
        return [s for s in segments if not (s.block_uuid and s.block_uuid in restricted)]

    setattr(guarded, _WRAPPED, True)
    guarded.__wrapped__ = extractor
    return guarded


def install() -> None:
    """Idempotent. Registers the walker handler and wraps all currently registered extractors."""
    from src.services.ai.rag import sources
    from src.services.ai.rag.sources import dynamic

    dynamic._NODE_HANDLERS[AUDIENCE_TYPE] = _noop_audience
    for activity_type, extractor in list(sources._EXTRACTORS.items()):
        sources._EXTRACTORS[activity_type] = _guard(extractor)
