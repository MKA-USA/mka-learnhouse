"""MKA fork: keep audience-restricted lesson text out of what is sent to an AI model for a learner.

``mka_content_for_ai`` returns a copy of a ProseMirror document in which every ``mkaAudience`` node the viewer's EFFECTIVE attributes
do not match (fail-closed reader + the Python rule evaluator) is removed together with everything inside it. Viewers who may see
every section of the course (superadmin, admin/maintainer of the course's org, active author) get the content unchanged.

Fail closed, never raise: ANY error while resolving the viewer or walking the document strips every audience section; if even that
fails, an empty document is returned. The input is never mutated and the unfiltered document is never returned once an audience
node is present and the viewer is not entitled to it.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.users import APITokenUser, SuperadminAPITokenUser, User
from src.services.mka import attributes as attrs_svc
from src.services.mka import audience as audience_svc
from src.services.mka.audience_eval import evaluate_rule

logger = logging.getLogger(__name__)

AUDIENCE_TYPE = "mkaAudience"
MAX_DEPTH = 200  # ProseMirror documents are shallow; anything deeper is treated as hostile and fails closed
_ALL = object()  # sentinel: the viewer may see every section


class _TooDeep(Exception):
    pass


def _is_audience(node: Any) -> bool:
    return isinstance(node, dict) and node.get("type") == AUDIENCE_TYPE


def _contains_audience(content: Any) -> bool:
    """Iterative scan (no recursion limit to trip over)."""
    stack = [content]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if _is_audience(node):
                return True
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return False


def _walk(node: Any, visible: Callable[[dict], bool], depth: int = 0) -> Any:
    """Deep copy of ``node`` minus every audience node for which ``visible`` is False."""
    if depth > MAX_DEPTH:
        raise _TooDeep()
    if isinstance(node, list):
        return [_walk(child, visible, depth + 1) for child in node if not (_is_audience(child) and not visible(child))]
    if isinstance(node, dict):
        if _is_audience(node) and not visible(node):  # malformed placement (not a list item): keep no content at all
            return {"type": AUDIENCE_TYPE, "content": []}
        return {key: _walk(value, visible, depth + 1) for key, value in node.items()}
    return node  # scalars are immutable


async def _viewer(user: Any, db_session: AsyncSession, request: Any, course: Any) -> Any:
    """``_ALL`` | effective attributes dict | ``None`` (anonymous / not a user session: nobody-viewer)."""
    if user is None or isinstance(user, (APITokenUser, SuperadminAPITokenUser)):
        return None
    uid = getattr(user, "id", None)
    if not uid:
        return None
    course_uuid = getattr(course, "course_uuid", None)
    if course_uuid and await audience_svc.course_view_all(request, uid, course_uuid, db_session) is True:
        return _ALL
    row = await db_session.get(User, uid)
    if row is None:
        return None
    attrs, _stale = await attrs_svc.read_effective(db_session, row)
    return attrs


async def mka_content_for_ai(content: Any, user: Any, db_session: AsyncSession, request: Any = None, course: Optional[Any] = None) -> Any:
    """See the module docstring. ``course`` (anything with ``course_uuid``) enables the can-view-all rule; without it nobody is elevated."""
    try:
        if not _contains_audience(content):
            return _walk(content, lambda _n: True)
        viewer = await _viewer(user, db_session, request, course)
        if viewer is _ALL:
            return _walk(content, lambda _n: True)
        return _walk(content, lambda n: evaluate_rule((n.get("attrs") or {}).get("rule") if isinstance(n.get("attrs"), dict) else None, viewer))
    except Exception:  # noqa: BLE001 - contract: never raise, never leak
        logger.exception("MKA audience strip failed; removing all audience sections")
    try:
        return _walk(content, lambda _n: False)
    except Exception:  # noqa: BLE001
        return [] if isinstance(content, list) else {"type": "doc", "content": []}
