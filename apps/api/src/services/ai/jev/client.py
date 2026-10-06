"""Provider-neutral System One client (TypeSafe Jev or Cloudflare Clef).

Single choke point for every AI-judgment call.  Providers: ``typesafe`` (Jev via
``typesafe-sdk``) and ``cloudflare`` (Workers AI Clef over REST).  Both are
normalized into the same ``JevResult``.  The rest of the codebase never imports
``typesafe_sdk`` directly (except the question types, lazily, inside the jev
package).  Every public function degrades gracefully: if Jev is disabled, the
org is not opted in, the SDK is missing, the key is unset, or the call fails or
times out, the caller gets ``None`` / ``False`` and falls back to its existing
behaviour.

Privacy: nothing in this module logs user content or the API key.  Failures are
logged as exception type + (truncated) message only.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from config.config import get_learnhouse_config

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 3.0

CLOUDFLARE_API_BASE = "https://api.cloudflare.com/client/v4"
CLOUDFLARE_DEFAULT_MODEL = "clef-flash"
_CF_MODEL_PREFIX = "@cf/cloudflare/"
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
# Clef accepts 1-64 questions and truncates long state; cap what we send.
MAX_QUESTIONS = 64
STATE_MAX_CHARS = 60_000

# Rerank payload limits (bounds cost and what leaves the platform).
RERANK_MAX_CHUNKS = 10
RERANK_MAX_CHUNK_CHARS = 1000

# Rerank rubric: 4 levels -> score range 0..3.
_RERANK_CRITERIA = [
    "Not relevant: different topic entirely.",
    "Tangentially related: same domain but does not answer the question.",
    "Partially relevant: some useful info but not a direct answer.",
    "Highly relevant: directly answers or substantially addresses the question.",
]


# ---------------------------------------------------------------------------
# Config / feature gate
# ---------------------------------------------------------------------------

def _get_jev_config():
    """Return the active JevConfig, or None when Jev is disabled/unconfigured."""
    cfg = get_learnhouse_config().jev_config
    if cfg is None or not cfg.enabled or not cfg.api_key:
        return None
    if getattr(cfg, "provider", "typesafe") == "cloudflare" and not getattr(
        cfg, "cloudflare_account_id", ""
    ):
        return None
    return cfg


def jev_enabled(org_id: int | None = None) -> bool:
    """True when Jev is enabled, a key is present, and *org_id* is opted in.

    ``allowed_org_ids`` is an explicit opt-in list: empty means disabled for
    everyone, and ``org_id=None`` is never allowed.
    """
    cfg = _get_jev_config()
    if cfg is None:
        return False
    allowed = getattr(cfg, "allowed_org_ids", None) or []
    return org_id is not None and org_id in allowed


def _timeout_of(cfg) -> float:
    value = getattr(cfg, "timeout", None)
    try:
        value = float(value) if value is not None else DEFAULT_TIMEOUT
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT
    return value if value > 0 else DEFAULT_TIMEOUT


# ---------------------------------------------------------------------------
# Result wrapper (provider-neutral)
# ---------------------------------------------------------------------------

def _to_plain(answer: Any) -> dict[str, Any] | None:
    """Convert one answer (SDK object or dict) into a plain dict."""
    if isinstance(answer, Mapping):
        return dict(answer)
    dump = getattr(answer, "model_dump", None)
    if callable(dump):
        try:
            out = dump()
            return dict(out) if isinstance(out, Mapping) else None
        except Exception:  # noqa: BLE001
            return None
    return None


def _normalize_answers(response: Any) -> dict[str, dict[str, Any]]:
    """Plain ``{id: answer_dict}`` from an SDK ``SystemOneResponse``, a full
    response body (``{"answers": ...}``) or a bare answers mapping."""
    if isinstance(response, Mapping):
        raw = response.get("answers") if isinstance(response.get("answers"), Mapping) else response
    else:
        raw = getattr(response, "answers", None)
    if not isinstance(raw, Mapping):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for qid, answer in raw.items():
        plain = _to_plain(answer)
        if plain is not None:
            out[str(qid)] = plain
    return out


def _count_levels(answer: Mapping[str, Any]) -> int:
    for key in ("legend", "probabilities"):
        value = answer.get(key)
        if value:
            try:
                return len(value)
            except TypeError:
                return 0
    return 0


def _kind(answer: Mapping[str, Any]) -> str | None:
    kind = answer.get("type")
    if isinstance(kind, str):
        return kind
    for key in ("noul", "choice", "score"):
        if key in answer:
            return key
    return None


class JevResult:
    """Uniform accessors over System One answers from any provider.

    Normalized to plain dicts at construction, so TypeSafe SDK objects and raw
    Cloudflare Clef JSON yield identical results.  ``noul`` answers carry no
    confidence; ``choice`` and ``score`` answers do.  ``score`` is
    ``0..levels-1`` (may be fractional) with ``legend`` giving one entry per
    level.
    """

    def __init__(self, response: Any) -> None:
        self._answers = _normalize_answers(response)

    def _get(self, kind: str, qid: str) -> dict[str, Any] | None:
        answer = self._answers.get(qid)
        if answer is None or _kind(answer) != kind:
            return None
        return answer

    def noul(self, qid: str) -> float | None:
        answer = self._get("noul", qid)
        if answer is None:
            return None
        try:
            return float(answer["noul"])
        except (KeyError, TypeError, ValueError):
            return None

    def choice(self, qid: str) -> tuple[str, float] | None:
        answer = self._get("choice", qid)
        if answer is None:
            return None
        try:
            return str(answer["choice"]), float(answer["confidence"])
        except (KeyError, TypeError, ValueError):
            return None

    def score_with_confidence(self, qid: str) -> tuple[float, float] | None:
        """``(normalized_score, confidence)`` or None if missing/degenerate."""
        answer = self._get("score", qid)
        if answer is None:
            return None
        try:
            raw = float(answer["score"])
            confidence = float(answer["confidence"])
        except (KeyError, TypeError, ValueError):
            return None
        levels = _count_levels(answer)
        if levels < 2:
            return None
        norm = min(1.0, max(0.0, raw / (levels - 1)))
        return norm, confidence

    def score_norm(self, qid: str) -> float | None:
        """Score normalized to 0..1 (``score / (levels - 1)``)."""
        pair = self.score_with_confidence(qid)
        return pair[0] if pair else None


# ---------------------------------------------------------------------------
# Shared async clients
# ---------------------------------------------------------------------------

_client: Any = None
_client_key: tuple | None = None
_client_loop: asyncio.AbstractEventLoop | None = None
_cf_client: Any = None
_cf_key: tuple | None = None
_cf_loop: asyncio.AbstractEventLoop | None = None
# Test hook: transport for the Cloudflare httpx client (httpx.MockTransport).
_cf_transport: Any = None
_init_lock: asyncio.Lock | None = None
_init_lock_loop: asyncio.AbstractEventLoop | None = None
_sdk_missing_logged = False


def _get_init_lock() -> asyncio.Lock:
    """Return an init lock bound to the running loop (recreated on loop change)."""
    global _init_lock, _init_lock_loop
    loop = asyncio.get_running_loop()
    if _init_lock is None or _init_lock_loop is not loop:
        _init_lock = asyncio.Lock()
        _init_lock_loop = loop
    return _init_lock


def _log_failure(what: str, exc: BaseException) -> None:
    # Type + truncated message only: never user content, never the key.
    logger.warning("Jev %s failed (%s: %.200s)", what, type(exc).__name__, str(exc))


async def _get_client(cfg):
    """Lazily create the shared ``AsyncTypeSafeClient`` (lock-guarded)."""
    global _client, _client_key, _client_loop, _sdk_missing_logged

    timeout = _timeout_of(cfg)
    key = (cfg.api_key, timeout)
    loop = asyncio.get_running_loop()

    if _client is not None and _client_key == key and _client_loop is loop:
        return _client

    async with _get_init_lock():
        if _client is not None and _client_key == key and _client_loop is loop:
            return _client
        try:
            from typesafe_sdk import AsyncTypeSafeClient, RetryPolicy
        except ImportError:
            if not _sdk_missing_logged:
                _sdk_missing_logged = True
                logger.warning("typesafe-sdk not installed; Jev disabled")
            return None

        old = _client
        _client = AsyncTypeSafeClient(
            api_key=cfg.api_key,
            timeout=timeout,
            retry=RetryPolicy(max_retries=1, timeout=timeout),
        )
        _client_key = key
        _client_loop = loop
        if old is not None and old is not _client:
            # Replaced because key/timeout changed (same loop): close politely.
            try:
                await old.aclose()
            except Exception as exc:  # noqa: BLE001
                _log_failure("old client close", exc)
        return _client


async def _get_cf_client(cfg):
    """Lazily create the shared Cloudflare ``httpx.AsyncClient`` (lock-guarded)."""
    global _cf_client, _cf_key, _cf_loop

    key = (cfg.api_key, cfg.cloudflare_account_id)
    loop = asyncio.get_running_loop()
    if _cf_client is not None and _cf_key == key and _cf_loop is loop:
        return _cf_client

    async with _get_init_lock():
        if _cf_client is not None and _cf_key == key and _cf_loop is loop:
            return _cf_client
        old = _cf_client
        _cf_client = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {cfg.api_key}"},
            timeout=httpx.Timeout(_timeout_of(cfg)),
            transport=_cf_transport,
        )
        _cf_key = key
        _cf_loop = loop
        if old is not None and old is not _cf_client:
            try:
                await old.aclose()
            except Exception as exc:  # noqa: BLE001
                _log_failure("old cloudflare client close", exc)
        return _cf_client


async def aclose_jev_client() -> None:
    """Close and drop the shared clients (call from app shutdown)."""
    global _client, _client_key, _client_loop, _cf_client, _cf_key, _cf_loop
    client, _client, _client_key, _client_loop = _client, None, None, None
    cf, _cf_client, _cf_key, _cf_loop = _cf_client, None, None, None
    for c, what in ((client, "client close"), (cf, "cloudflare client close")):
        if c is not None:
            try:
                await c.aclose()
            except Exception as exc:  # noqa: BLE001
                _log_failure(what, exc)


# ---------------------------------------------------------------------------
# Model resolution + Cloudflare transport
# ---------------------------------------------------------------------------

def _resolve_model(cfg, capability: str | None) -> str | None:
    """Per-capability override > cfg.model > provider default."""
    models = getattr(cfg, "models", None) or {}
    override = models.get(capability) if capability else None
    if override:
        return str(override)
    model = getattr(cfg, "model", None)
    if model:
        return str(model)
    if getattr(cfg, "provider", "typesafe") == "cloudflare":
        return CLOUDFLARE_DEFAULT_MODEL
    return None


def _question_to_wire(question: Any) -> Any:
    if isinstance(question, Mapping):
        return dict(question)
    dump = getattr(question, "model_dump", None)
    if callable(dump):
        return dump(mode="json")
    raise TypeError("unsupported question type")


def _truncate_state(state: Any) -> Any:
    """Bound the state size sent to Cloudflare (strings only are shortened)."""
    try:
        size = len(json.dumps(state, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        return state
    if size <= STATE_MAX_CHARS:
        return state
    if isinstance(state, str):
        return state[:STATE_MAX_CHARS]
    if isinstance(state, Mapping):
        per = max(100, STATE_MAX_CHARS // max(1, len(state)))
        return {k: (v[:per] if isinstance(v, str) else v) for k, v in state.items()}
    return state


def _unwrap_cf(body: Any) -> dict | None:
    """Accept the REST envelope or a bare result; None on failure/garbage."""
    if not isinstance(body, dict):
        return None
    if "success" in body and body.get("success") is False:
        return None
    if body.get("errors"):
        return None
    inner = body.get("result") if "result" in body else body
    if not isinstance(inner, dict) or not isinstance(inner.get("answers"), dict):
        return None
    return inner


async def _cloudflare_call(cfg, model: str, state: Any, questions: Mapping[str, Any],
                           timeout: float) -> dict | None:
    account = cfg.cloudflare_account_id
    bare = model.removeprefix(_CF_MODEL_PREFIX)
    if not _SAFE_ID.match(account) or not _SAFE_ID.match(bare):
        logger.warning("Jev cloudflare config invalid (account id or model format)")
        return None
    if len(questions) > MAX_QUESTIONS:
        logger.warning("Jev request has %d questions (max %d); skipped", len(questions), MAX_QUESTIONS)
        return None

    client = await _get_cf_client(cfg)
    url = f"{CLOUDFLARE_API_BASE}/accounts/{account}/ai/run/{_CF_MODEL_PREFIX}{bare}"
    payload = {
        "model": bare,
        "state": _truncate_state(state),
        "questions": {str(k): _question_to_wire(v) for k, v in questions.items()},
    }
    deadline = time.monotonic() + timeout

    for attempt in range(2):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            logger.warning("Jev cloudflare call timed out")
            return None
        try:
            resp = await client.post(url, json=payload, timeout=remaining)
        except httpx.TimeoutException:
            logger.warning("Jev cloudflare call failed (TimeoutException)")
            return None
        except httpx.HTTPError as exc:
            logger.warning("Jev cloudflare call failed (%s)", type(exc).__name__)
            return None

        status = resp.status_code
        if status == 429 or status >= 500:
            if attempt == 0:
                delay = min(random.uniform(0.2, 0.5), max(0.0, deadline - time.monotonic()))
                logger.info("Jev cloudflare retry (status=%d)", status)
                await asyncio.sleep(delay)
                continue
            logger.warning("Jev cloudflare call failed (HTTP status=%d)", status)
            return None
        if status >= 400:
            logger.warning("Jev cloudflare call failed (HTTP status=%d)", status)
            return None
        try:
            body = resp.json()
        except ValueError:
            logger.warning("Jev cloudflare call failed (malformed JSON, status=%d)", status)
            return None
        inner = _unwrap_cf(body)
        if inner is None:
            logger.warning("Jev cloudflare call failed (unsuccessful or malformed response, status=%d)", status)
        return inner
    return None


async def run_system_one(
    state: dict,
    questions: Mapping[str, Any],
    *,
    capability: str | None = None,
    timeout: float | None = None,
) -> JevResult | None:
    """Run one batched System One request via the configured provider.

    Returns ``None`` on ANY failure, timeout, or when Jev is disabled; only
    ``asyncio.CancelledError`` propagates.  Org opt-in is the caller's job
    (``jev_enabled(org_id)``).  *capability* selects an optional per-capability
    model override (rerank|guardrails|moderation|intent|quiz).
    """
    cfg = _get_jev_config()
    if cfg is None or not questions:
        return None

    effective_timeout = float(timeout) if timeout and timeout > 0 else _timeout_of(cfg)
    model = _resolve_model(cfg, capability)

    try:
        if getattr(cfg, "provider", "typesafe") == "cloudflare":
            body = await asyncio.wait_for(
                _cloudflare_call(cfg, model or CLOUDFLARE_DEFAULT_MODEL, state, questions,
                                 effective_timeout),
                timeout=effective_timeout,
            )
            return JevResult(body) if body is not None else None

        client = await _get_client(cfg)
        if client is None:
            return None
        kwargs: dict[str, Any] = {"state": state, "questions": questions,
                                  "timeout": effective_timeout}
        if model:
            kwargs["model"] = model
        response = await asyncio.wait_for(
            client.system_one(**kwargs), timeout=effective_timeout
        )
        return JevResult(response)
    except asyncio.CancelledError:
        raise
    except TimeoutError:
        logger.warning("Jev call timed out after %.1fs", effective_timeout)
        return None
    except Exception as exc:  # noqa: BLE001
        _log_failure("call", exc)
        return None


# ---------------------------------------------------------------------------
# Rerank
# ---------------------------------------------------------------------------

@dataclass
class RerankResult:
    """One chunk's normalized relevance (kept for diagnostics/tests)."""

    index: int
    score: float
    confidence: float


def _chunk_text(chunk: Any) -> str:
    if isinstance(chunk, str):
        return chunk
    return str(getattr(chunk, "chunk_text", chunk))


async def jev_rerank_chunks(query: str, chunks: list, top_k: int) -> list | None:
    """Rerank *chunks* by relevance to *query*; return the best *top_k*.

    *chunks* may be strings or objects with a ``chunk_text`` attribute; the
    returned list contains the original objects, best first.  Only the first
    ``RERANK_MAX_CHUNKS`` are scored (each truncated to
    ``RERANK_MAX_CHUNK_CHARS``); any extras follow in vector order.

    Returns ``None`` (caller keeps vector order) if Jev is unavailable, the
    call fails, or ANY chunk's answer is missing.  Callers must check
    ``jev_enabled(org_id)`` first.
    """
    if not chunks or top_k <= 0:
        return None

    candidates = list(chunks[:RERANK_MAX_CHUNKS])
    extras = list(chunks[RERANK_MAX_CHUNKS:])

    try:
        from typesafe_sdk import Score
    except Exception:  # noqa: BLE001 - SDK missing/broken: fail open
        return None

    state: dict = {"user_question": query[:500]}
    questions: dict = {}
    for i, chunk in enumerate(candidates):
        state[f"chunk_{i}"] = _chunk_text(chunk)[:RERANK_MAX_CHUNK_CHARS]
        questions[f"rel_{i}"] = Score(
            instructions=f"How relevant is `chunk_{i}` to the student's question `user_question`?",
            criteria=_RERANK_CRITERIA,
        )

    result = await run_system_one(state, questions, capability="rerank")
    if result is None:
        return None

    scored: list[tuple[float, float, int]] = []
    for i in range(len(candidates)):
        pair = result.score_with_confidence(f"rel_{i}")
        if pair is None:
            logger.warning("Jev rerank missing an answer; keeping vector order")
            return None
        scored.append((pair[0], pair[1], i))

    scored.sort(key=lambda t: (-t[0], -t[1], t[2]))
    ordered = [candidates[i] for _, _, i in scored] + extras
    return ordered[:top_k]
