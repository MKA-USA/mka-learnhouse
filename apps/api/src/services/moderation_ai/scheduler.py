"""Fire-and-forget AI moderation (phase 1: record flags for staff review).

``schedule_moderation`` is called AFTER content is saved/committed. It never
blocks, never raises into the request path, and never blocks or hides content.
The background task opens its OWN DB session, is fail-open, and logs only
ids/scores (never user text). Org opt-in is checked inside the task because it
needs the org config.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from src.db.moderation_flags import CONTENT_TYPES, ModerationFlag
from src.services.moderation_ai.extractors import TextLoader
from src.services.moderation_ai.settings import jev_available, load_org_config_dict, org_opted_in

logger = logging.getLogger(__name__)

MIN_TEXT_CHARS = 20
RATE_LIMIT_SECONDS = 60
# Per-content cap on provider calls (any hash) per rolling RATE_LIMIT_SECONDS.
CONTENT_CALL_CAP = 5
HIGH_SCORE = 0.8
NOUL_FLAG_THRESHOLD = 0.5  # mirrors jev.moderation.NOUL_FLAG_THRESHOLD

# Strong refs so fire-and-forget tasks are not GC'd mid-run; drained on shutdown.
_background_tasks: set[asyncio.Task] = set()

# In-memory fallbacks (Redis is preferred for the rate limit when available).
_rate_seen: dict[str, float] = {}
_content_calls: dict[str, list[float]] = {}
_scored: OrderedDict[str, None] = OrderedDict()
_SCORED_MAX = 4096

# Trailing re-check for content whose latest edit hit the per-content cap.
# Keyed ``content_type:content_uuid``; holds only the LATEST loader callable
# (never text) and is replaced by each further capped edit.
_TRAILING_MAX_ATTEMPTS = 3
_TRAILING_SLACK_SECONDS = 0.25


@dataclass
class _Trailing:
    kind: str
    content_type: str
    content_uuid: str
    org_id: int | None
    author_user_id: int
    text_loader: TextLoader
    wake: asyncio.Event
    attempts: int = 0


_pending_trailing: dict[str, _Trailing] = {}
_draining = False


def _now() -> float:
    return time.monotonic()


async def _wait_window(delay: float, wake: asyncio.Event) -> None:
    """Sleep *delay* seconds or until *wake* is set (shutdown). Patched in tests."""
    try:
        await asyncio.wait_for(wake.wait(), timeout=delay)
    except TimeoutError:
        pass


def session_factory():
    """The shared async session factory (indirection so tests can patch it)."""
    from src.core.events.database import _async_session_factory

    return _async_session_factory


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def schedule_moderation(
    *,
    kind: str,
    content_type: str,
    content_uuid: str,
    org_id: int | None,
    author_user_id: int,
    text_loader: TextLoader,
) -> None:
    """Schedule a background moderation pass. No-op unless Jev is available."""
    try:
        if content_type not in CONTENT_TYPES or not content_uuid or not author_user_id:
            return
        if not jev_available():
            return
        task = asyncio.get_running_loop().create_task(
            _run(
                kind=kind,
                content_type=content_type,
                content_uuid=content_uuid,
                org_id=org_id,
                author_user_id=author_user_id,
                text_loader=text_loader,
            )
        )
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
    except Exception as exc:  # noqa: BLE001 - never raise into the request path
        logger.debug("AI moderation not scheduled (%s)", type(exc).__name__)


async def drain_moderation_tasks() -> None:
    """Wait for in-flight moderation tasks (call from app shutdown).

    Pending trailing re-checks are woken immediately (no window sleep) so the
    latest edit is still scanned once; if still capped they are dropped.
    """
    global _draining
    _draining = True
    try:
        for pending in list(_pending_trailing.values()):
            pending.wake.set()
        # Loop: a woken task may (rarely) spawn another before finishing.
        while _background_tasks:
            await asyncio.gather(*list(_background_tasks), return_exceptions=True)
    finally:
        _draining = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def content_hash_of(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8", errors="replace")).hexdigest()[:32]


def _acquire_rate_slot(key: str) -> bool:
    """True if at most one call per *key* per RATE_LIMIT_SECONDS is respected.

    The key includes the content hash, so an edit (new hash) is always scanned
    and only an identical resubmission inside the window is skipped.
    """
    try:
        from src.core.redis import get_redis_client

        r = get_redis_client()
        if r is not None:
            return bool(r.set(f"moderation_ai:rl:{key}", "1", nx=True, ex=RATE_LIMIT_SECONDS))
    except Exception:  # noqa: BLE001 - fall back to the in-memory limiter
        pass
    now = time.monotonic()
    if len(_rate_seen) > 5000:
        for k in [k for k, t in _rate_seen.items() if now - t >= RATE_LIMIT_SECONDS]:
            _rate_seen.pop(k, None)
    last = _rate_seen.get(key)
    if last is not None and now - last < RATE_LIMIT_SECONDS:
        return False
    _rate_seen[key] = now
    return True


def _acquire_content_slot(key: str) -> bool:
    """True if *key* (content_type:content_uuid) is under CONTENT_CALL_CAP calls
    in the rolling window. Redis first (sorted set), in-memory fallback."""
    now_wall = time.time()
    try:
        from src.core.redis import get_redis_client

        r = get_redis_client()
        if r is not None:
            rkey = f"moderation_ai:cc:{key}"
            member = f"{now_wall}:{uuid4().hex[:8]}"
            # Single MULTI/EXEC transaction: trim, count, add (the add is
            # undone below when over the cap), set TTL. Atomic against other
            # workers, unlike separate remove/count/add round trips.
            pipe = r.pipeline(transaction=True)
            pipe.zremrangebyscore(rkey, 0, now_wall - RATE_LIMIT_SECONDS)
            pipe.zadd(rkey, {member: now_wall})
            pipe.zcard(rkey)
            pipe.expire(rkey, RATE_LIMIT_SECONDS)
            results = pipe.execute()
            if int(results[2]) > CONTENT_CALL_CAP:
                r.zrem(rkey, member)  # over cap: give the slot back
                return False
            return True
    except Exception:  # noqa: BLE001 - fall back to the in-memory limiter
        pass
    now = _now()
    if len(_content_calls) > 5000:
        for k in [k for k, ts in _content_calls.items() if not ts or now - ts[-1] >= RATE_LIMIT_SECONDS]:
            _content_calls.pop(k, None)
    recent = [t for t in _content_calls.get(key, []) if now - t < RATE_LIMIT_SECONDS]
    if len(recent) >= CONTENT_CALL_CAP:
        _content_calls[key] = recent
        return False
    recent.append(now)
    _content_calls[key] = recent
    return True


def _content_wait_seconds(key: str) -> float:
    """Seconds until the oldest slot in the content's window expires."""
    try:
        from src.core.redis import get_redis_client

        r = get_redis_client()
        if r is not None:
            oldest = r.zrange(f"moderation_ai:cc:{key}", 0, 0, withscores=True)
            if oldest:
                return max(0.0, float(oldest[0][1]) + RATE_LIMIT_SECONDS - time.time())
            return 0.0
    except Exception:  # noqa: BLE001
        pass
    ts = _content_calls.get(key) or []
    if not ts:
        return 0.0
    return max(0.0, min(ts) + RATE_LIMIT_SECONDS - _now())


def _release_rate_slot(key: str) -> None:
    """Undo _acquire_rate_slot (job was capped, not scanned)."""
    try:
        from src.core.redis import get_redis_client

        r = get_redis_client()
        if r is not None:
            r.delete(f"moderation_ai:rl:{key}")
            return
    except Exception:  # noqa: BLE001
        pass
    _rate_seen.pop(key, None)


def _register_trailing(
    kind: str,
    content_type: str,
    content_uuid: str,
    org_id: int | None,
    author_user_id: int,
    text_loader: TextLoader,
    attempts: int = 0,
) -> None:
    """Record ONE pending trailing scan per content, keeping only the latest
    loader. The first registration spawns the waiter; later ones just replace
    the entry (the waiter reads the entry when it fires)."""
    if _draining and attempts:
        return  # shutting down and still capped: drop (fail-open)
    key = f"{content_type}:{content_uuid}"
    existing = _pending_trailing.get(key)
    if existing is not None:
        existing.kind = kind
        existing.org_id = org_id
        existing.author_user_id = author_user_id
        existing.text_loader = text_loader
        return
    delay = _content_wait_seconds(f"{content_type}:{content_uuid}") + _TRAILING_SLACK_SECONDS
    entry = _Trailing(kind, content_type, content_uuid, org_id, author_user_id, text_loader,
                      asyncio.Event(), attempts)
    _pending_trailing[key] = entry
    task = asyncio.get_running_loop().create_task(_trailing_waiter(key, entry, delay))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def _trailing_waiter(key: str, entry: _Trailing, delay: float) -> None:
    try:
        await _wait_window(delay, entry.wake)
    except asyncio.CancelledError:
        _pending_trailing.pop(key, None)
        raise
    except Exception:  # noqa: BLE001
        pass
    # Pop BEFORE running so edits arriving during the scan register a new one.
    latest = _pending_trailing.pop(key, None)
    if latest is None:
        return
    await _run(
        kind=latest.kind,
        content_type=latest.content_type,
        content_uuid=latest.content_uuid,
        org_id=latest.org_id,
        author_user_id=latest.author_user_id,
        text_loader=latest.text_loader,
        _trailing_attempt=latest.attempts + 1,
    )


def _already_scored(key: str) -> bool:
    if key in _scored:
        _scored.move_to_end(key)
        return True
    return False


def _mark_scored(key: str) -> None:
    _scored[key] = None
    while len(_scored) > _SCORED_MAX:
        _scored.popitem(last=False)


def _severity(scores: dict[str, Any]) -> str:
    integrity = scores.get("academic_integrity")
    if (
        (integrity is not None and integrity >= 0.67)
        or scores.get("toxicity", 0) >= HIGH_SCORE
        or scores.get("pii", 0) >= HIGH_SCORE
    ):
        return "high"
    return "medium"


def _reasons(scores: dict[str, Any], content_type: str) -> list[str]:
    """Calm, non-accusatory reasons derived from scores (no content echoed)."""
    out: list[str] = []
    if scores.get("pii", 0) > NOUL_FLAG_THRESHOLD:
        out.append("Possible personal information")
    if scores.get("toxicity", 0) > NOUL_FLAG_THRESHOLD:
        out.append("Possible toxic or abusive language")
    if content_type != "user_profile" and scores.get("spam", 0) > NOUL_FLAG_THRESHOLD:
        out.append("Possible spam or off-topic content")
    integrity = scores.get("academic_integrity")
    if integrity is not None and integrity >= 0.67:
        out.append("Possible integrity concern - review the work yourself")
    return out


async def _target_org_ids(session, content_type: str, org_id: int | None, author_user_id: int) -> list[int]:
    if org_id is not None:
        return [org_id]
    if content_type != "user_profile":
        return []
    from src.db.user_organizations import UserOrganization

    rows = (
        await session.execute(select(UserOrganization.org_id).where(UserOrganization.user_id == author_user_id))
    ).scalars().all()
    return [int(r) for r in rows]


# ---------------------------------------------------------------------------
# Background task
# ---------------------------------------------------------------------------


async def _run(
    *,
    kind: str,
    content_type: str,
    content_uuid: str,
    org_id: int | None,
    author_user_id: int,
    text_loader: TextLoader,
    _trailing_attempt: int = 0,
) -> None:
    """Never raises (except cancellation on shutdown)."""
    try:
        await _run_inner(
            kind, content_type, content_uuid, org_id, author_user_id, text_loader, _trailing_attempt
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - fail open, log type + message only
        logger.warning(
            "AI moderation task failed (%s: %.200s) content_type=%s",
            type(exc).__name__,
            str(exc),
            content_type,
        )


async def _run_inner(
    kind: str,
    content_type: str,
    content_uuid: str,
    org_id: int | None,
    author_user_id: int,
    text_loader: TextLoader,
    trailing_attempt: int = 0,
) -> None:
    from src.services.ai.jev.moderation import moderate_content

    async with session_factory()() as session:
        # 1. Which orgs opted in (for this surface)?
        candidates = await _target_org_ids(session, content_type, org_id, author_user_id)
        enabled_orgs: list[int] = []
        for oid in candidates:
            if org_opted_in(await load_org_config_dict(oid, session), content_type):
                enabled_orgs.append(oid)
        if not enabled_orgs:
            return

        # 2. Load text (own session) and apply cheap guards.
        text = (await text_loader(session) or "").strip()
        if len(text) < MIN_TEXT_CHARS:
            return

        chash = content_hash_of(text)
        dedupe_key = f"{content_type}:{content_uuid}:{chash}"
        if _already_scored(dedupe_key):
            return

        existing = (
            await session.execute(
                select(ModerationFlag.org_id).where(
                    ModerationFlag.content_type == content_type,
                    ModerationFlag.content_uuid == content_uuid,
                    ModerationFlag.content_hash == chash,
                )
            )
        ).scalars().all()
        enabled_orgs = [o for o in enabled_orgs if o not in set(existing)]
        if not enabled_orgs:
            return

        rate_key = f"{content_type}:{content_uuid}:{chash}"
        if not _acquire_rate_slot(rate_key):
            logger.debug("AI moderation rate-limited content_type=%s", content_type)
            return
        if not _acquire_content_slot(f"{content_type}:{content_uuid}"):
            logger.info("ai_moderation content_type=%s outcome=content_cap_deferred", content_type)
            # The per-hash key must not swallow the trailing scan of this text.
            _release_rate_slot(rate_key)
            if trailing_attempt < _TRAILING_MAX_ATTEMPTS:
                _register_trailing(
                    kind, content_type, content_uuid, org_id, author_user_id, text_loader, trailing_attempt
                )
            return

        # 3. Score. Org opt-in already verified, so no allowlist check here.
        # Profile text only screens pii + toxicity (kind stays "general").
        result = await moderate_content(text, kind=kind, org_id=None)
        if result is None:
            logger.info("ai_moderation content_type=%s kind=%s outcome=unavailable", content_type, kind)
            return
        _mark_scored(dedupe_key)

        scores: dict[str, Any] = {
            "pii": float(result.pii),
            "toxicity": float(result.toxicity),
            "spam": float(result.spam),
            "academic_integrity": (
                float(result.academic_integrity) if result.academic_integrity is not None else None
            ),
        }
        reasons = _reasons(scores, content_type)
        if content_type == "user_profile":
            action = "flag" if reasons else "allow"
        else:
            action = result.action if reasons else "allow"

        logger.info(
            "ai_moderation content_type=%s kind=%s action=%s pii=%.2f toxicity=%.2f spam=%.2f integrity=%s",
            content_type,
            kind,
            action,
            scores["pii"],
            scores["toxicity"],
            scores["spam"],
            "n/a" if scores["academic_integrity"] is None else f"{scores['academic_integrity']:.2f}",
        )
        if action != "flag":
            return

        # 4. Record one flag per opted-in org (no content text stored).
        now = datetime.now(timezone.utc).isoformat()
        for oid in enabled_orgs:
            session.add(
                ModerationFlag(
                    flag_uuid=f"modflag_{uuid4()}",
                    org_id=oid,
                    content_type=content_type,
                    content_uuid=content_uuid,
                    content_hash=chash,
                    author_user_id=author_user_id,
                    kind=kind,
                    scores=scores,
                    reasons=reasons,
                    severity=_severity(scores),
                    status="open",
                    created_at=now,
                )
            )
            try:
                await session.commit()
            except IntegrityError:
                # Concurrent run already recorded this content version.
                await session.rollback()
