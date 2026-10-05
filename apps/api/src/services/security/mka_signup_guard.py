"""MKA fork: anti-abuse guard for the anonymous create-user routes.

Hooked as a FastAPI dependency (one line per route) into the three upstream
create-user routes in ``src/routers/users.py``:
``POST /users/``, ``POST /users/{org_id}``, ``POST /users/{org_id}/invite/{code}``.
It is NOT hooked into ``create_user`` itself (OAuth also calls that).

Rules (see docs/superpowers/specs/2026-10-05-mka-signup-hardening-eval.md):
- SaaS mode: inert. SaaS behaves exactly like upstream.
- Authenticated callers (session or API token, e.g. the e2e client and admin
  tooling) are exempt: they cannot carry a browser challenge and are accountable.
- Anonymous callers: per-IP signup rate limit (``MKA_SIGNUP_RATE_LIMIT_PER_HOUR``,
  default 30, ``0`` disables, fails OPEN without Redis), then Cloudflare
  Turnstile when BOTH keys are configured (see ``mka_turnstile``).
"""

import logging
import os

from fastapi import HTTPException, Request

from src.services.security.rate_limiting import check_rate_limit, get_client_ip

logger = logging.getLogger(__name__)

SIGNUP_LIMIT_ENV = "MKA_SIGNUP_RATE_LIMIT_PER_HOUR"
DEFAULT_SIGNUP_LIMIT_PER_HOUR = 30
SIGNUP_WINDOW_SECONDS = 60 * 60


def signup_rate_limit_per_hour() -> int:
    """Configured attempts per IP per hour. ``0`` disables; invalid -> default."""
    raw = (os.environ.get(SIGNUP_LIMIT_ENV) or "").strip()
    if not raw:
        return DEFAULT_SIGNUP_LIMIT_PER_HOUR
    try:
        value = int(raw)
    except ValueError:
        logger.warning("%s=%r is not an integer; using %d", SIGNUP_LIMIT_ENV, raw, DEFAULT_SIGNUP_LIMIT_PER_HOUR)
        return DEFAULT_SIGNUP_LIMIT_PER_HOUR
    if value < 0:
        logger.warning("%s=%r is negative; using %d", SIGNUP_LIMIT_ENV, raw, DEFAULT_SIGNUP_LIMIT_PER_HOUR)
        return DEFAULT_SIGNUP_LIMIT_PER_HOUR
    return value


def enforce_mka_signup_rate_limit(request: Request) -> None:
    """Raise 429 when this client IP exceeded the signup limit.

    Keys on upstream ``get_client_ip`` (same as the login limiter: forwarded
    headers are trusted only from a loopback/private peer). Fails OPEN when
    Redis is missing or erroring: an outage must not block member signups.
    """
    limit = signup_rate_limit_per_hour()
    if limit == 0:
        return
    ip = get_client_ip(request)
    try:
        is_allowed, _count, retry_after = check_rate_limit(
            key=f"signup:{ip}", max_attempts=limit, window_seconds=SIGNUP_WINDOW_SECONDS
        )
    except Exception:
        logger.warning("Signup rate limit unavailable (failing open)", exc_info=True)
        return
    if is_allowed:
        return
    minutes = max(1, retry_after // 60)
    raise HTTPException(
        status_code=429,
        detail=(
            "Too many sign-up attempts from your network. "
            f"Please try again in about {minutes} minute{'s' if minutes != 1 else ''}."
        ),
        headers={"Retry-After": str(retry_after)},
    )
