"""MKA fork: restrict Google SSO to an allowlist of email domains.

Controlled by env var ``MKA_GOOGLE_ALLOWED_DOMAINS`` (comma-separated).
Unset/empty means no restriction (upstream behaviour). Read at call time.
"""

import logging
import os
from typing import Optional

from fastapi import HTTPException

logger = logging.getLogger(__name__)

ENV_VAR = "MKA_GOOGLE_ALLOWED_DOMAINS"
_DENIED_DETAIL = "This Google account is not permitted to sign in"


def _allowed_domains() -> set[str]:
    raw = os.environ.get(ENV_VAR, "")
    return {d.strip().lower() for d in raw.split(",") if d.strip()}


def _deny(domain: str) -> None:
    logger.warning("Google SSO rejected: domain not allowed (%r)", domain)
    raise HTTPException(status_code=403, detail=_DENIED_DETAIL)


def enforce_allowed_google_domain(
    email: str, hosted_domain: Optional[str] = None
) -> None:
    allowed = _allowed_domains()
    if not allowed:
        return

    if not email or "@" not in email:
        _deny("<malformed>")
    domain = email.strip().rsplit("@", 1)[1].strip().lower()
    if not domain or domain not in allowed:
        _deny(domain)

    if hosted_domain and str(hosted_domain).strip():
        hd = str(hosted_domain).strip().lower()
        if hd not in allowed:
            _deny(hd)
