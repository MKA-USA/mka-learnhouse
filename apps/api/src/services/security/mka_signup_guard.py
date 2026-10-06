"""MKA fork: anti-abuse guard for the create-user routes.

Hooked as a FastAPI dependency (one line per route) into the three upstream
create-user routes in ``src/routers/users.py``:
``POST /users/``, ``POST /users/{org_id}``, ``POST /users/{org_id}/invite/{code}``.
It is NOT hooked into ``create_user`` itself (OAuth also calls that).

Rules (see docs/superpowers/specs/2026-10-05-mka-signup-hardening-eval.md):
- SaaS mode: inert. SaaS behaves exactly like upstream.
- Exempt (validated callers only): superadmin API tokens and superadmin
  sessions everywhere; on ``/users/{org_id}...`` also an org-scoped API token
  OF THAT ORG and a session of an ADMIN of that org. ``POST /users/`` (no org)
  exempts superadmins only. Every other caller (anonymous, member, maintainer, admin of
  another org) is guarded.
- Guarded callers: Cloudflare Turnstile first (when BOTH keys are configured,
  see ``mka_turnstile``), then the per-IP signup limit
  (``MKA_SIGNUP_RATE_LIMIT_PER_HOUR``, default 60, ``0`` disables). Only
  requests that passed Turnstile consume the bucket, so garbage requests cannot
  lock members out. The limiter fails OPEN without Redis and is skipped when the
  client IP is not globally routable (loopback/private/unknown: such an IP
  cannot tell members apart, so it must never become one shared bucket).
"""

import ipaddress
import logging
import os
from typing import Union

from fastapi import Depends, HTTPException, Request
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.events.database import get_db_session
from src.db.users import AnonymousUser, APITokenUser, PublicUser, SuperadminAPITokenUser
from src.security.auth import get_current_user
from src.security.org_auth import get_user_org
from src.security.rbac.constants import is_admin
from src.security.superadmin import is_user_superadmin
from src.services.security import mka_turnstile
from src.services.security.rate_limiting import check_rate_limit

logger = logging.getLogger(__name__)

SIGNUP_LIMIT_ENV = "MKA_SIGNUP_RATE_LIMIT_PER_HOUR"
DEFAULT_SIGNUP_LIMIT_PER_HOUR = 60
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


MAX_FORWARDED_LENGTH = 4096


def _parse_ip(value):
    """Canonical ``ip_address`` or None: strips ``%zone`` and ``[...]``,
    unwraps IPv4-mapped IPv6. Never raises."""
    if not value:
        return None
    text = str(value).strip().strip("[]").split("%", 1)[0]
    try:
        addr = ipaddress.ip_address(text)
    except ValueError:
        return None
    mapped = getattr(addr, "ipv4_mapped", None)
    return mapped or addr


def _is_distinguishable_client_ip(ip) -> bool:
    """True only for a globally routable address (a real, per-client IP)."""
    addr = _parse_ip(ip)
    return addr is not None and _is_unicast_global(addr)


def _is_unicast_global(addr) -> bool:
    # Python reports some multicast ranges as is_global; a client is unicast.
    return addr.is_global and not addr.is_multicast


def _is_proxy_hop(addr) -> bool:
    """Our own infrastructure: loopback, private and link-local ranges."""
    return addr.is_loopback or addr.is_private or addr.is_link_local


def mka_client_ip(request: Request) -> str:
    """Client IP for the signup guard (fork-only; upstream ``get_client_ip``,
    shared with the login limiter, is left unchanged).

    The container nginx APPENDS to any incoming X-Forwarded-For
    (``$proxy_add_x_forwarded_for``, no ``real_ip`` module) and upstream takes
    the FIRST entry, which a client can choose. Here, when the direct peer is
    a local proxy, all XFF header lines are joined and walked from the RIGHT,
    skipping only proxy hops (loopback/private/link-local). The first entry
    that is not a proxy hop IS the client: if it is unparseable or not globally
    routable the result is ``"unknown"`` (the limiter is skipped) and nothing
    further left (attacker-controlled) is ever considered. Oversized headers
    are truncated to their right-hand end. A public direct peer is used as-is. Never raises.
    """
    direct = request.client.host if request.client else None
    direct_addr = _parse_ip(direct)
    if direct_addr is None:
        return "unknown"
    if not _is_proxy_hop(direct_addr):
        return str(direct_addr)
    forwarded = ", ".join(request.headers.getlist("x-forwarded-for"))
    if len(forwarded) > MAX_FORWARDED_LENGTH:
        # Keep only the RIGHT-hand end: the walk stops at the entry our edge
        # appended, so the cut-off left part is client-controlled and never
        # needed. Drop the partial first entry so a fragment is never parsed.
        # (Giving up instead would let padding dodge the limiter.)
        forwarded = forwarded[-MAX_FORWARDED_LENGTH:]
        forwarded = forwarded.split(",", 1)[1] if "," in forwarded else ""
    for entry in reversed(forwarded.split(",")):
        if not entry.strip():
            continue
        addr = _parse_ip(entry)
        if addr is not None and _is_proxy_hop(addr):
            continue
        if addr is None or not _is_unicast_global(addr):
            return "unknown"
        return str(addr)
    return "unknown"


def mka_rate_limit_bucket(ip: str) -> str:
    """Bucket for an IP: IPv4 address, or the IPv6 /64 (one client usually owns
    a whole /64 and could otherwise mint a bucket per address)."""
    addr = _parse_ip(ip)
    if addr is None:
        return "unknown"
    if addr.version == 6:
        return str(ipaddress.ip_network(f"{addr}/64", strict=False))
    return str(addr)


def enforce_mka_signup_rate_limit(request: Request) -> None:
    """Raise 429 when this client IP exceeded the signup limit.

    Keys on ``mka_rate_limit_bucket(mka_client_ip(...))``: the client the proxy
    chain saw (a spoofed left-hand XFF entry cannot pick the bucket), IPv4
    address or IPv6 /64.
    Skipped when the resolved IP is empty/unknown/not globally routable, and
    fails OPEN when Redis is missing or erroring: neither situation may block
    member signups.
    """
    limit = signup_rate_limit_per_hour()
    if limit == 0:
        return
    ip = mka_client_ip(request)
    if not _is_distinguishable_client_ip(ip):
        logger.info("Signup rate limit skipped: client IP %r is not globally routable", ip)
        return
    try:
        is_allowed, _count, retry_after = check_rate_limit(
            key=f"signup:{mka_rate_limit_bucket(ip)}", max_attempts=limit, window_seconds=SIGNUP_WINDOW_SECONDS
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


def _is_saas() -> bool:
    from src.core.deployment_mode import get_deployment_mode

    return get_deployment_mode() == "saas"


async def enforce_mka_turnstile(request: Request) -> None:
    """403 when Turnstile is enforced and the forwarded token is missing/invalid.

    Messages match the web signup route so the forms show the same text.
    """
    if not mka_turnstile.is_turnstile_enforced():
        return
    token = request.headers.get(mka_turnstile.TOKEN_HEADER)
    result = await mka_turnstile.verify_turnstile_token(token, mka_client_ip(request))
    if result.ok:
        return
    detail = (
        "Please complete the verification challenge."
        if result.reason == "missing_token"
        else "Verification failed. Please try again."
    )
    raise HTTPException(status_code=403, detail=detail)


async def _is_exempt(request: Request, current_user, db_session: AsyncSession) -> bool:
    """Validated API tokens, superadmins, and ADMINs of the target org only.

    ``current_user`` comes from upstream ``get_current_user``: garbage bearer
    JWTs/cookies yield ``AnonymousUser`` and garbage ``lh_`` tokens 401, so only
    validated identities reach the role checks. Roles are read from the DB, not
    from fields on the user object. The org comes from the PATH only (never a
    query parameter), so ``POST /users/?org_id=...`` cannot borrow an org.
    """
    raw_org_id = request.path_params.get("org_id")
    if isinstance(current_user, SuperadminAPITokenUser):
        return True
    if isinstance(current_user, APITokenUser):
        # Org-scoped token: exempt only on its own org's routes. POST /users/
        # has no org in the path to check the token against.
        return raw_org_id is not None and str(raw_org_id) == str(current_user.org_id)
    if not isinstance(current_user, PublicUser) or not current_user.id:
        return False
    if await is_user_superadmin(current_user.id, db_session):
        return True
    if raw_org_id is None:
        # POST /users/ creates an org-less account: superadmin only. Being an
        # admin of SOME org grants no authority over standalone accounts.
        return False
    try:
        org_id = int(raw_org_id)
    except (TypeError, ValueError):
        return False
    user_org = await get_user_org(current_user.id, org_id, db_session)
    return user_org is not None and is_admin(user_org.role_id)


async def mka_signup_guard(
    request: Request,
    db_session: AsyncSession = Depends(get_db_session),
    current_user: Union[PublicUser, APITokenUser, SuperadminAPITokenUser, AnonymousUser] = Depends(
        get_current_user
    ),
) -> None:
    """FastAPI dependency for the create-user routes (see module doc)."""
    if _is_saas():
        return
    if await _is_exempt(request, current_user, db_session):
        return
    # Turnstile FIRST: only requests that pass it may consume the IP bucket.
    await enforce_mka_turnstile(request)
    enforce_mka_signup_rate_limit(request)
