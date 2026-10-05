"""MKA fork: backend Turnstile verification + anonymous signup guard (G1)."""

from unittest.mock import patch

import httpx
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from src.db.users import AnonymousUser, APITokenUser, PublicUser
from src.services.security import mka_signup_guard as guard
from src.services.security import mka_turnstile as ts


def _request(client_host="127.0.0.1", headers=None):
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


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "sec")
    monkeypatch.setenv("NEXT_PUBLIC_TURNSTILE_SITE_KEY", "site")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("TURNSTILE_SECRET_KEY", raising=False)
    monkeypatch.delenv("NEXT_PUBLIC_TURNSTILE_SITE_KEY", raising=False)
    monkeypatch.delenv("MKA_SIGNUP_RATE_LIMIT_PER_HOUR", raising=False)


def _mock_cloudflare(monkeypatch, handler):
    calls = []

    def wrapped(request: httpx.Request):
        calls.append(request)
        return handler(request)

    transport = httpx.MockTransport(wrapped)
    monkeypatch.setattr(
        ts, "_client", lambda: httpx.AsyncClient(transport=transport, timeout=ts.TIMEOUT_SECONDS)
    )
    return calls


# --- enforcement rule ------------------------------------------------------


@pytest.mark.parametrize(
    "secret,site,expected",
    [
        ("sec", "site", True),
        ("sec", None, False),
        (None, "site", False),
        ("", "site", False),
        ("sec", "  ", False),
        (None, None, False),
    ],
)
def test_enforced_only_when_both_keys_set(monkeypatch, secret, site, expected):
    if secret is not None:
        monkeypatch.setenv("TURNSTILE_SECRET_KEY", secret)
    if site is not None:
        monkeypatch.setenv("NEXT_PUBLIC_TURNSTILE_SITE_KEY", site)
    assert ts.is_turnstile_enforced() is expected


# --- verifier ----------------------------------------------------------------


async def test_missing_token_rejected_without_network(monkeypatch, keys):
    calls = _mock_cloudflare(monkeypatch, lambda r: httpx.Response(200, json={"success": True}))
    result = await ts.verify_turnstile_token(None, "203.0.113.9")
    assert (result.ok, result.reason) == (False, "missing_token")
    assert calls == []


async def test_valid_token_posts_secret_token_and_ip(monkeypatch, keys):
    calls = _mock_cloudflare(monkeypatch, lambda r: httpx.Response(200, json={"success": True}))
    result = await ts.verify_turnstile_token("tok", "203.0.113.9")
    assert result.ok is True and result.reason is None
    assert len(calls) == 1
    assert str(calls[0].url) == ts.SITEVERIFY_URL
    body = dict(httpx.QueryParams(calls[0].content.decode()))
    assert body == {"secret": "sec", "response": "tok", "remoteip": "203.0.113.9"}


async def test_unknown_ip_not_sent(monkeypatch, keys):
    calls = _mock_cloudflare(monkeypatch, lambda r: httpx.Response(200, json={"success": True}))
    await ts.verify_turnstile_token("tok", "unknown")
    assert "remoteip" not in dict(httpx.QueryParams(calls[0].content.decode()))


async def test_invalid_token_rejected(monkeypatch, keys):
    _mock_cloudflare(
        monkeypatch,
        lambda r: httpx.Response(200, json={"success": False, "error-codes": ["timeout-or-duplicate"]}),
    )
    result = await ts.verify_turnstile_token("tok", None)
    assert (result.ok, result.reason) == (False, "verification_failed")
    assert result.error_codes == ["timeout-or-duplicate"]


async def test_oversized_token_rejected_without_network(monkeypatch, keys):
    calls = _mock_cloudflare(monkeypatch, lambda r: httpx.Response(200, json={"success": True}))
    result = await ts.verify_turnstile_token("x" * 5000, None)
    assert (result.ok, result.reason) == (False, "verification_failed")
    assert calls == []


async def test_network_error_fails_open(monkeypatch, keys):
    def boom(request):
        raise httpx.ConnectTimeout("slow")

    _mock_cloudflare(monkeypatch, boom)
    result = await ts.verify_turnstile_token("tok", None)
    assert (result.ok, result.reason) == (True, "error")


async def test_non_json_reply_fails_open(monkeypatch, keys):
    _mock_cloudflare(monkeypatch, lambda r: httpx.Response(502, text="<html>bad gateway</html>"))
    result = await ts.verify_turnstile_token("tok", None)
    assert (result.ok, result.reason) == (True, "error")


# --- guard dependency ----------------------------------------------------------


def _public_user():
    return PublicUser(
        id=1, user_uuid="u1", username="admin", first_name="", last_name="",
        email="a@b.c", avatar_image="", bio="",
    )


@pytest.fixture
def not_saas():
    with patch.object(guard, "_is_saas", return_value=False):
        yield


async def test_saas_mode_is_inert(monkeypatch, keys):
    calls = _mock_cloudflare(monkeypatch, lambda r: httpx.Response(200, json={"success": False}))
    with patch.object(guard, "_is_saas", return_value=True), patch.object(
        guard, "enforce_mka_signup_rate_limit"
    ) as limiter:
        await guard.mka_signup_guard(_request(), AnonymousUser())
    limiter.assert_not_called()
    assert calls == []


@pytest.mark.parametrize("user_factory", [_public_user, lambda: APITokenUser(id=0, org_id=1, token_name="t", created_by_user_id=1)])
async def test_authenticated_callers_exempt(monkeypatch, keys, not_saas, user_factory):
    calls = _mock_cloudflare(monkeypatch, lambda r: httpx.Response(200, json={"success": False}))
    with patch.object(guard, "enforce_mka_signup_rate_limit") as limiter:
        await guard.mka_signup_guard(_request(), user_factory())
    limiter.assert_not_called()
    assert calls == []


async def test_anonymous_without_keys_only_rate_limited(monkeypatch, not_saas):
    calls = _mock_cloudflare(monkeypatch, lambda r: httpx.Response(200, json={"success": False}))
    with patch.object(guard, "enforce_mka_signup_rate_limit") as limiter:
        await guard.mka_signup_guard(_request(), AnonymousUser())
    limiter.assert_called_once()
    assert calls == []


async def test_anonymous_missing_token_403(monkeypatch, keys, not_saas):
    _mock_cloudflare(monkeypatch, lambda r: httpx.Response(200, json={"success": True}))
    with patch.object(guard, "enforce_mka_signup_rate_limit"):
        with pytest.raises(HTTPException) as exc:
            await guard.mka_signup_guard(_request(), AnonymousUser())
    assert exc.value.status_code == 403
    assert exc.value.detail == "Please complete the verification challenge."


async def test_anonymous_invalid_token_403(monkeypatch, keys, not_saas):
    _mock_cloudflare(monkeypatch, lambda r: httpx.Response(200, json={"success": False}))
    with patch.object(guard, "enforce_mka_signup_rate_limit"):
        with pytest.raises(HTTPException) as exc:
            await guard.mka_signup_guard(
                _request(headers={"X-Turnstile-Token": "bad"}), AnonymousUser()
            )
    assert exc.value.status_code == 403
    assert exc.value.detail == "Verification failed. Please try again."


async def test_anonymous_valid_token_passes_with_forwarded_ip(monkeypatch, keys, not_saas):
    calls = _mock_cloudflare(monkeypatch, lambda r: httpx.Response(200, json={"success": True}))
    with patch.object(guard, "enforce_mka_signup_rate_limit"):
        await guard.mka_signup_guard(
            _request("127.0.0.1", {"X-Turnstile-Token": "good", "X-Forwarded-For": "203.0.113.9"}),
            AnonymousUser(),
        )
    body = dict(httpx.QueryParams(calls[0].content.decode()))
    assert body["response"] == "good" and body["remoteip"] == "203.0.113.9"


async def test_rate_limit_runs_before_turnstile(monkeypatch, keys, not_saas):
    calls = _mock_cloudflare(monkeypatch, lambda r: httpx.Response(200, json={"success": True}))
    with patch.object(
        guard, "enforce_mka_signup_rate_limit",
        side_effect=HTTPException(status_code=429, detail="slow down"),
    ):
        with pytest.raises(HTTPException) as exc:
            await guard.mka_signup_guard(
                _request(headers={"X-Turnstile-Token": "good"}), AnonymousUser()
            )
    assert exc.value.status_code == 429
    assert calls == []


async def test_cloudflare_outage_lets_signup_through(monkeypatch, keys, not_saas):
    def boom(request):
        raise httpx.ConnectError("down")

    _mock_cloudflare(monkeypatch, boom)
    with patch.object(guard, "enforce_mka_signup_rate_limit"):
        await guard.mka_signup_guard(_request(headers={"X-Turnstile-Token": "t"}), AnonymousUser())


# --- route hooks -------------------------------------------------------------


@pytest.mark.parametrize(
    "path", ["/", "/{org_id}", "/{org_id}/invite/{invite_code}"]
)
def test_create_user_routes_carry_guard(path):
    from src.routers.users import router

    route = next(
        r for r in router.routes if getattr(r, "path", None) == path and "POST" in r.methods
    )
    calls = [d.call for d in route.dependant.dependencies]
    assert guard.mka_signup_guard in calls

