"""MKA fork: configurable, fail-open signup rate limit (G3)."""

from unittest.mock import patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from src.services.security import mka_signup_guard as guard

PATCH_CHECK = "src.services.security.mka_signup_guard.check_rate_limit"


def _request(client_host="8.8.8.8", headers=None):
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/users/",
        "headers": [
            (key.lower().encode(), value.encode())
            for key, value in (headers or {}).items()
        ],
        "query_string": b"",
        "client": (client_host, 12345),
    }
    return Request(scope)


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    monkeypatch.delenv("MKA_SIGNUP_RATE_LIMIT_PER_HOUR", raising=False)


@pytest.mark.parametrize(
    "raw,expected",
    [(None, 60), ("", 60), ("12", 12), ("0", 0), ("abc", 60), ("-3", 60), (" 7 ", 7)],
)
def test_limit_from_env(monkeypatch, raw, expected):
    if raw is not None:
        monkeypatch.setenv("MKA_SIGNUP_RATE_LIMIT_PER_HOUR", raw)
    assert guard.signup_rate_limit_per_hour() == expected


def test_allowed_uses_real_client_ip_and_default_limit():
    req = _request("127.0.0.1", {"X-Forwarded-For": "8.8.4.4, 10.0.0.2"})
    with patch(PATCH_CHECK, return_value=(True, 1, 3600)) as check:
        guard.enforce_mka_signup_rate_limit(req)
    check.assert_called_once_with(
        key="signup:8.8.4.4", max_attempts=60, window_seconds=3600
    )


def test_spoofed_forwarded_header_ignored_from_public_peer():
    req = _request("8.8.8.8", {"X-Forwarded-For": "1.2.3.4"})
    with patch(PATCH_CHECK, return_value=(True, 1, 3600)) as check:
        guard.enforce_mka_signup_rate_limit(req)
    assert check.call_args.kwargs["key"] == "signup:8.8.8.8"


def test_env_limit_is_used(monkeypatch):
    monkeypatch.setenv("MKA_SIGNUP_RATE_LIMIT_PER_HOUR", "5")
    with patch(PATCH_CHECK, return_value=(True, 1, 3600)) as check:
        guard.enforce_mka_signup_rate_limit(_request())
    assert check.call_args.kwargs["max_attempts"] == 5


def test_zero_disables_without_touching_redis(monkeypatch):
    monkeypatch.setenv("MKA_SIGNUP_RATE_LIMIT_PER_HOUR", "0")
    with patch(PATCH_CHECK) as check:
        guard.enforce_mka_signup_rate_limit(_request())
    check.assert_not_called()


def test_exceeded_returns_429_with_message_and_retry_after():
    with patch(PATCH_CHECK, return_value=(False, 60, 1500)):
        with pytest.raises(HTTPException) as exc:
            guard.enforce_mka_signup_rate_limit(_request())
    assert exc.value.status_code == 429
    assert isinstance(exc.value.detail, str)
    assert "Too many sign-up attempts" in exc.value.detail
    assert "25 minutes" in exc.value.detail
    assert exc.value.headers == {"Retry-After": "1500"}


def test_exceeded_singular_minute():
    with patch(PATCH_CHECK, return_value=(False, 60, 30)):
        with pytest.raises(HTTPException) as exc:
            guard.enforce_mka_signup_rate_limit(_request())
    assert "about 1 minute." in exc.value.detail


def test_redis_not_configured_fails_open():
    # get_redis_connection raises HTTPException(500) when Redis is not configured
    with patch(PATCH_CHECK, side_effect=HTTPException(status_code=500, detail="x")):
        guard.enforce_mka_signup_rate_limit(_request())


def test_redis_error_fails_open():
    with patch(PATCH_CHECK, side_effect=ConnectionError("redis down")):
        guard.enforce_mka_signup_rate_limit(_request())


@pytest.mark.parametrize(
    "peer,headers",
    [
        ("127.0.0.1", {}),  # loopback, nothing forwarded
        ("10.0.0.5", {}),  # private proxy hop, nothing forwarded
        ("127.0.0.1", {"X-Forwarded-For": "172.18.0.3"}),  # forwarded private hop
        ("127.0.0.1", {"X-Forwarded-For": "0.0.0.0"}),  # unspecified
        ("127.0.0.1", {"X-Forwarded-For": "::1"}),
        ("127.0.0.1", {"X-Forwarded-For": "203.0.113.9"}),  # documentation range, not global
    ],
)
def test_non_global_client_ip_skips_limiter(peer, headers):
    # A shared bucket must never be created from an IP that cannot tell members apart.
    with patch(PATCH_CHECK) as check:
        guard.enforce_mka_signup_rate_limit(_request(peer, headers))
    check.assert_not_called()


def test_unknown_client_skips_limiter():
    scope = {"type": "http", "method": "POST", "path": "/", "headers": [], "query_string": b""}
    with patch(PATCH_CHECK) as check:
        guard.enforce_mka_signup_rate_limit(Request(scope))
    check.assert_not_called()
