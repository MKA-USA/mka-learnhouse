"""MKA fork: "Google-only" email domains.

Google SSO stays open to any Google account. But an address whose domain is in
``MKA_GOOGLE_ONLY_DOMAINS`` (comma-separated, case-insensitive, e.g.
``mkausa.org``) may authenticate ONLY through Google, so that suspending the
user in Google Workspace removes their access. Every non-Google path
(password, reset, magic link, signup, email change) is blocked for them, and
the Google path requires the Workspace-managed ``hd`` claim to equal the
domain (a consumer Google account using an @mkausa.org address has no ``hd``).

Unset/empty env var = no enforcement (upstream behaviour). Read at call time.
"""

import contextvars
import logging
import os
from typing import Optional

from fastapi import HTTPException

logger = logging.getLogger(__name__)

ENV_VAR = "MKA_GOOGLE_ONLY_DOMAINS"
_BLOCK_DETAIL = "Accounts with an mkausa.org email must sign in with Google"
_HD_DETAIL = "This Google account is not a managed Workspace account for this email domain"


def _google_only_domains() -> set[str]:
    raw = os.environ.get(ENV_VAR, "")
    return {d.strip().lower() for d in raw.split(",") if d.strip()}


def _domain_of(email: Optional[str]) -> Optional[str]:
    """Exact lower-cased domain of ``email``, or None if malformed."""
    if not email or not isinstance(email, str):
        return None
    email = email.strip()
    if email.count("@") != 1:
        return None
    local, domain = email.split("@")
    domain = domain.strip().lower()
    if not local.strip() or not domain:
        return None
    return domain


def is_google_only_email(email: Optional[str]) -> bool:
    """True only when the email's domain exactly matches a configured domain."""
    domain = _domain_of(email)
    return domain is not None and domain in _google_only_domains()


def block_non_google_auth(email: Optional[str]) -> None:
    """Raise 403 if ``email`` is Google-only. Call on every non-Google path."""
    if is_google_only_email(email):
        logger.warning("Non-Google auth blocked for Google-only domain (%r)", _domain_of(email))
        raise HTTPException(status_code=403, detail=_BLOCK_DETAIL)


def block_email_change(old_email: Optional[str], new_email: Optional[str]) -> None:
    """Block a self-service email change into OR out of a Google-only domain.

    Into: would create a password-capable account on a Workspace address.
    Out of: a suspended Workspace user could otherwise escape to a password
    account by renaming their email.
    """
    if (old_email or "").strip().lower() == (new_email or "").strip().lower():
        return
    block_non_google_auth(new_email)
    block_non_google_auth(old_email)


# Request-scoped record of the ``hd`` claim of the Google login in progress, so the
# attribute login hook (services/mka/attributes.py) can tell whether Workspace ownership
# of the email domain was PROVEN by this login. Set for EVERY Google login (configured
# Google-only domain or not); each request runs in its own context, so it never leaks.
_VERIFIED_HD: contextvars.ContextVar[Optional[tuple[str, str]]] = contextvars.ContextVar(
    "mka_verified_hd", default=None
)


def take_verified_hd(email: Optional[str]) -> Optional[str]:
    """The ``hd`` seen for ``email`` in this request's Google login, or None."""
    rec = _VERIFIED_HD.get()
    if rec is None or not email:
        return None
    return rec[1] if rec[0] == str(email).strip().lower() else None


def require_workspace_hd(email: Optional[str], hosted_domain: Optional[str]) -> None:
    """Google path: for Google-only emails, ``hd`` must equal the email domain."""
    if email:
        _VERIFIED_HD.set((str(email).strip().lower(), str(hosted_domain).strip().lower() if hosted_domain else ""))
    if not is_google_only_email(email):
        return
    domain = _domain_of(email)
    hd = str(hosted_domain).strip().lower() if hosted_domain else ""
    if hd != domain:
        logger.warning("Google sign-in rejected: missing/mismatched hd for domain %r", domain)
        raise HTTPException(status_code=403, detail=_HD_DETAIL)
