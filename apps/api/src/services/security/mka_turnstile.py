"""MKA fork: server-side Cloudflare Turnstile verification for the API.

Mirrors the web rules in ``apps/web/lib/mka-turnstile.ts`` / ``lib/turnstile.ts``:
- Enforced only when BOTH ``TURNSTILE_SECRET_KEY`` and
  ``NEXT_PUBLIC_TURNSTILE_SITE_KEY`` are non-empty (read at call time). With
  only one set the widget and the secret disagree and enforcing would lock out
  every signup.
- A missing or invalid token is REJECTED.
- Cloudflare/network errors and unreadable replies FAIL OPEN (logged): a
  Cloudflare outage must not take member signups down; the signup rate limit
  still bounds abuse meanwhile.

A token is single-use (a second siteverify returns ``timeout-or-duplicate``),
so outside SaaS mode the Next signup route forwards the token in the
``X-Turnstile-Token`` header and does NOT verify it itself; this module is the
only verifier.
"""

import logging
import os
from dataclasses import dataclass, field
from typing import List, Optional

import httpx

logger = logging.getLogger(__name__)

SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
TOKEN_HEADER = "X-Turnstile-Token"
SECRET_ENV = "TURNSTILE_SECRET_KEY"
SITE_KEY_ENV = "NEXT_PUBLIC_TURNSTILE_SITE_KEY"
TIMEOUT_SECONDS = 5.0
# Cloudflare documents a 2048-character maximum token length.
MAX_TOKEN_LENGTH = 2048


@dataclass
class TurnstileResult:
    ok: bool
    reason: Optional[str] = None  # missing_token | verification_failed | error
    error_codes: List[str] = field(default_factory=list)


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def is_turnstile_enforced() -> bool:
    """True only when both the secret and the public site key are configured."""
    return bool(_env(SECRET_ENV)) and bool(_env(SITE_KEY_ENV))


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=TIMEOUT_SECONDS)


async def verify_turnstile_token(
    token: Optional[str], remote_ip: Optional[str]
) -> TurnstileResult:
    """Verify ``token`` with Cloudflare. Callers check ``is_turnstile_enforced`` first."""
    if not token:
        return TurnstileResult(ok=False, reason="missing_token")
    if len(token) > MAX_TOKEN_LENGTH:
        return TurnstileResult(ok=False, reason="verification_failed")

    data = {"secret": _env(SECRET_ENV), "response": token}
    if remote_ip and remote_ip != "unknown":
        data["remoteip"] = remote_ip

    try:
        async with _client() as client:
            res = await client.post(SITEVERIFY_URL, data=data)
        payload = res.json()
        success = bool(payload.get("success"))
        codes = list(payload.get("error-codes") or [])
    except Exception:
        logger.warning("Turnstile siteverify failed (failing open)", exc_info=True)
        return TurnstileResult(ok=True, reason="error")

    if success:
        return TurnstileResult(ok=True)
    logger.info("Turnstile verification rejected: %s", codes)
    return TurnstileResult(ok=False, reason="verification_failed", error_codes=codes)
