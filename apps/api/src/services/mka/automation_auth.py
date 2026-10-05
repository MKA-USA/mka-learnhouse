"""MKA fork: authentication helpers for the automation endpoints (spec 2026-10-05 sections 2B, 2C, 5).

* :func:`verify_webhook_signature`: LearnHouse webhooks sign the RAW body: ``X-Webhook-Signature:
  sha256=<lower-case hex HMAC-SHA256(secret, body bytes)>`` (integration map section 1). Verify BEFORE parsing JSON.
  Strict on purpose: exact lower-case ``sha256=`` prefix, exactly 64 lower-case hex digits, no whitespace.
* :func:`require_cron_secret`: FastAPI dependency for the scheduler endpoints: ``X-MKA-Cron-Secret`` compared
  (constant-time) with ``MKA_AUTOMATION_CRON_SECRET``. Not an org API token. An unconfigured secret never
  authorises (503), a wrong or missing one is 401; the secret/guess is never logged or echoed.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
from typing import Optional, Union

from fastapi import Header, HTTPException

from src.services.mka import automation_config as cfg

logger = logging.getLogger(__name__)

_SIGNATURE_RE = re.compile(r"^sha256=[0-9a-f]{64}$")  # fullmatch semantics: ^...$ plus no trailing newline below


def _secret_bytes(secret: Union[str, bytes, None]) -> bytes:
    if secret is None:
        return b""
    return secret if isinstance(secret, bytes) else secret.encode("utf-8")


def compute_signature(raw_body: bytes, secret: Union[str, bytes]) -> str:
    """The header value LearnHouse would send (used by tests and the local e2e)."""
    return "sha256=" + hmac.new(_secret_bytes(secret), raw_body, hashlib.sha256).hexdigest()


def verify_webhook_signature(raw_body: bytes, header: Optional[str], secret: Union[str, bytes, None]) -> bool:
    """True only for an exact, well-formed signature of ``raw_body`` made with a non-empty ``secret``."""
    key = _secret_bytes(secret)
    if not key:  # unconfigured / empty secret must never validate anything (even a signature made with b"")
        return False
    if not isinstance(raw_body, (bytes, bytearray)) or not isinstance(header, str):
        return False
    # `$` also matches before a trailing newline: refuse that explicitly, and anything non-ASCII.
    if not header.isascii() or "\n" in header or not _SIGNATURE_RE.match(header):
        return False
    expected = compute_signature(bytes(raw_body), key)
    return hmac.compare_digest(expected.encode("ascii"), header.encode("ascii"))


async def require_cron_secret(
    x_mka_cron_secret: Optional[str] = Header(default=None, alias="X-MKA-Cron-Secret"),
) -> None:
    """Dependency for scheduler-only endpoints. Raises 503 (unconfigured) or 401 (missing/wrong)."""
    configured = cfg.cron_secret()
    if not configured:
        logger.error("automation cron endpoint called but MKA_AUTOMATION_CRON_SECRET is not set")
        raise HTTPException(status_code=503, detail="Automation is not configured")
    # Hash both sides first so the compared values always have equal length (no length side channel).
    provided = hashlib.sha256((x_mka_cron_secret or "").encode("utf-8", "replace")).digest()
    wanted = hashlib.sha256(configured.encode("utf-8")).digest()
    if not x_mka_cron_secret or not hmac.compare_digest(provided, wanted):
        logger.warning("automation cron endpoint: bad or missing secret")
        raise HTTPException(status_code=401, detail="Invalid credentials")
