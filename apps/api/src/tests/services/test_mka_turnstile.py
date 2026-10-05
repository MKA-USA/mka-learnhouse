"""MKA fork: backend Turnstile verification + anonymous signup guard (G1)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from src.core.events.database import get_db_session
from src.db.users import AnonymousUser, APITokenUser, PublicUser, SuperadminAPITokenUser
from src.security.auth import JWT_COOKIE_NAME
from src.services.security import mka_signup_guard as guard
from src.services.security import mka_turnstile as ts


def _request(client_host="127.0.0.1", headers=None, path_params=None):
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
        "path_params": path_params or {},
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


def _ok(r):
    return httpx.Response(200, json={"success": True})


def _bad(r):
    return httpx.Response(200, json={"success": False, "error-codes": ["invalid-input-response"]})


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
    calls = _mock_cloudflare(monkeypatch, _ok)
    result = await ts.verify_turnstile_token(None, "203.0.113.9")
    assert (result.ok, result.reason) == (False, "missing_token")
    assert calls == []


async def test_valid_token_posts_secret_token_and_ip(monkeypatch, keys):
    calls = _mock_cloudflare(monkeypatch, _ok)
    result = await ts.verify_turnstile_token("tok", "203.0.113.9")
    assert result.ok is True and result.reason is None
    assert len(calls) == 1
    assert str(calls[0].url) == ts.SITEVERIFY_URL
    body = dict(httpx.QueryParams(calls[0].content.decode()))
    assert body == {"secret": "sec", "response": "tok", "remoteip": "203.0.113.9"}


async def test_unknown_ip_not_sent(monkeypatch, keys):
    calls = _mock_cloudflare(monkeypatch, _ok)
    await ts.verify_turnstile_token("tok", "unknown")
    assert "remoteip" not in dict(httpx.QueryParams(calls[0].content.decode()))


@pytest.mark.parametrize(
    "codes", [["timeout-or-duplicate"], ["invalid-input-response"], ["invalid-input-secret"], []]
)
async def test_invalid_token_rejected(monkeypatch, keys, codes):
    _mock_cloudflare(
        monkeypatch, lambda r: httpx.Response(200, json={"success": False, "error-codes": codes})
    )
    result = await ts.verify_turnstile_token("tok", None)
    assert (result.ok, result.reason) == (False, "verification_failed")
    assert result.error_codes == codes


async def test_cloudflare_internal_error_fails_open(monkeypatch, keys):
    _mock_cloudflare(
        monkeypatch,
        lambda r: httpx.Response(200, json={"success": False, "error-codes": ["internal-error"]}),
    )
    result = await ts.verify_turnstile_token("tok", None)
    assert (result.ok, result.reason) == (True, "error")


@pytest.mark.parametrize("status", [500, 502, 503])
async def test_cloudflare_5xx_fails_open_even_with_json(monkeypatch, keys, status):
    _mock_cloudflare(monkeypatch, lambda r: httpx.Response(status, json={"success": False}))
    result = await ts.verify_turnstile_token("tok", None)
    assert (result.ok, result.reason) == (True, "error")


async def test_oversized_token_rejected_without_network(monkeypatch, keys):
    calls = _mock_cloudflare(monkeypatch, _ok)
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
    _mock_cloudflare(monkeypatch, lambda r: httpx.Response(200, text="<html>oops</html>"))
    result = await ts.verify_turnstile_token("tok", None)
    assert (result.ok, result.reason) == (True, "error")


# --- guard: who is exempt (F2) ------------------------------------------------


def _public_user(uid=1, superadmin=False):
    return PublicUser(
        id=uid, user_uuid=f"u{uid}", username=f"user{uid}", first_name="", last_name="",
        email=f"u{uid}@b.c", avatar_image="", bio="", is_superadmin=superadmin,
    )


@pytest.fixture
def not_saas():
    with patch.object(guard, "_is_saas", return_value=False):
        yield


@pytest.fixture
def roles():
    """Patch the DB-backed role lookups the exemption uses."""
    state = {"superadmin": set(), "org_roles": {}}

    async def superadmin(uid, db):
        return uid in state["superadmin"]

    async def user_org(uid, org_id, db):
        role = state["org_roles"].get((uid, org_id))
        return None if role is None else SimpleNamespace(role_id=role)

    with patch.object(guard, "is_user_superadmin", side_effect=superadmin), patch.object(
        guard, "get_user_org", side_effect=user_org
    ):
        yield state


async def _guard(request, user):
    await guard.mka_signup_guard(request, db_session=object(), current_user=user)


@pytest.mark.parametrize(
    "user",
    [
        APITokenUser(id=0, org_id=7, token_name="t", created_by_user_id=1),
        SuperadminAPITokenUser(),
    ],
)
async def test_api_token_callers_exempt(monkeypatch, keys, not_saas, roles, user):
    calls = _mock_cloudflare(monkeypatch, _bad)
    with patch.object(guard, "enforce_mka_signup_rate_limit") as limiter:
        await _guard(_request(path_params={"org_id": "7"}), user)
    limiter.assert_not_called()
    assert calls == []


@pytest.mark.parametrize("path_params", [{}, {"org_id": "7"}, {"org_id": "7", "invite_code": "X"}])
async def test_superadmin_session_exempt_everywhere(monkeypatch, keys, not_saas, roles, path_params):
    roles["superadmin"].add(1)
    calls = _mock_cloudflare(monkeypatch, _bad)
    with patch.object(guard, "enforce_mka_signup_rate_limit") as limiter:
        await _guard(_request(path_params=path_params), _public_user(1))
    limiter.assert_not_called()
    assert calls == []


async def test_org_admin_exempt_for_that_org(monkeypatch, keys, not_saas, roles):
    roles["org_roles"][(1, 7)] = 1  # ADMIN
    calls = _mock_cloudflare(monkeypatch, _bad)
    with patch.object(guard, "enforce_mka_signup_rate_limit") as limiter:
        await _guard(_request(path_params={"org_id": "7"}), _public_user(1))
    limiter.assert_not_called()
    assert calls == []


@pytest.mark.parametrize(
    "org_roles,path_params",
    [
        ({}, {"org_id": "7"}),  # plain session, not a member
        ({(1, 7): 3}, {"org_id": "7"}),  # member role
        ({(1, 7): 2}, {"org_id": "7"}),  # maintainer is not enough
        ({(1, 8): 1}, {"org_id": "7"}),  # admin of ANOTHER org
        ({(1, 7): 1}, {}),  # org admin on POST /users/ (no org): superadmin only
        ({(1, 7): 1}, {"org_id": "not-an-int"}),
    ],
)
async def test_non_admin_sessions_are_guarded(monkeypatch, keys, not_saas, roles, org_roles, path_params):
    roles["org_roles"].update(org_roles)
    _mock_cloudflare(monkeypatch, _ok)
    with patch.object(guard, "enforce_mka_signup_rate_limit"):
        with pytest.raises(HTTPException) as exc:
            await _guard(_request(path_params=path_params), _public_user(1))
    assert exc.value.status_code == 403
    assert exc.value.detail == "Please complete the verification challenge."


async def test_claimed_superadmin_flag_without_db_confirmation_is_guarded(monkeypatch, keys, not_saas, roles):
    # Exemption relies on the DB lookup, not on a field of the user object.
    _mock_cloudflare(monkeypatch, _ok)
    with patch.object(guard, "enforce_mka_signup_rate_limit"):
        with pytest.raises(HTTPException):
            await _guard(_request(), _public_user(1, superadmin=True))


# --- guard: order and outcomes (F1b) ---------------------------------------------


async def test_saas_mode_is_inert(monkeypatch, keys, roles):
    calls = _mock_cloudflare(monkeypatch, _bad)
    with patch.object(guard, "_is_saas", return_value=True), patch.object(
        guard, "enforce_mka_signup_rate_limit"
    ) as limiter:
        await _guard(_request(), AnonymousUser())
    limiter.assert_not_called()
    assert calls == []


async def test_anonymous_without_keys_only_rate_limited(monkeypatch, not_saas):
    calls = _mock_cloudflare(monkeypatch, _bad)
    with patch.object(guard, "enforce_mka_signup_rate_limit") as limiter:
        await _guard(_request(), AnonymousUser())
    limiter.assert_called_once()
    assert calls == []


async def test_missing_token_403_does_not_consume_bucket(monkeypatch, keys, not_saas):
    _mock_cloudflare(monkeypatch, _ok)
    with patch.object(guard, "enforce_mka_signup_rate_limit") as limiter:
        with pytest.raises(HTTPException) as exc:
            await _guard(_request(), AnonymousUser())
    assert exc.value.status_code == 403
    assert exc.value.detail == "Please complete the verification challenge."
    limiter.assert_not_called()


async def test_invalid_token_403_does_not_consume_bucket(monkeypatch, keys, not_saas):
    _mock_cloudflare(monkeypatch, _bad)
    with patch.object(guard, "enforce_mka_signup_rate_limit") as limiter:
        with pytest.raises(HTTPException) as exc:
            await _guard(_request(headers={"X-Turnstile-Token": "bad"}), AnonymousUser())
    assert exc.value.status_code == 403
    assert exc.value.detail == "Verification failed. Please try again."
    limiter.assert_not_called()


async def test_valid_token_then_limiter(monkeypatch, keys, not_saas):
    calls = _mock_cloudflare(monkeypatch, _ok)
    order = []
    with patch.object(
        guard, "enforce_mka_signup_rate_limit", side_effect=lambda r: order.append("limit")
    ):
        await _guard(
            _request("127.0.0.1", {"X-Turnstile-Token": "good", "X-Forwarded-For": "8.8.4.4"}),
            AnonymousUser(),
        )
    body = dict(httpx.QueryParams(calls[0].content.decode()))
    assert body["response"] == "good" and body["remoteip"] == "8.8.4.4"
    assert order == ["limit"]


async def test_valid_token_over_limit_gets_429(monkeypatch, keys, not_saas):
    _mock_cloudflare(monkeypatch, _ok)
    with patch.object(
        guard, "enforce_mka_signup_rate_limit",
        side_effect=HTTPException(status_code=429, detail="slow down"),
    ):
        with pytest.raises(HTTPException) as exc:
            await _guard(_request(headers={"X-Turnstile-Token": "good"}), AnonymousUser())
    assert exc.value.status_code == 429


async def test_cloudflare_outage_lets_signup_through_and_counts(monkeypatch, keys, not_saas):
    def boom(request):
        raise httpx.ConnectError("down")

    _mock_cloudflare(monkeypatch, boom)
    with patch.object(guard, "enforce_mka_signup_rate_limit") as limiter:
        await _guard(_request(headers={"X-Turnstile-Token": "t"}), AnonymousUser())
    limiter.assert_called_once()


# --- HTTP stack (F4): garbage credentials still hit the guard ---------------------


@pytest.fixture
def client(monkeypatch, keys):
    from src.routers.users import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/users")

    async def fake_db():
        yield AsyncMock()

    app.dependency_overrides[get_db_session] = fake_db
    monkeypatch.setattr(guard, "_is_saas", lambda: False)
    calls = _mock_cloudflare(monkeypatch, _ok)
    with TestClient(app) as c:
        yield c, calls


BODY = {"email": "a@example.com", "password": "Passw0rd!xyz", "username": "abc"}


@pytest.mark.parametrize(
    "path", ["/api/v1/users/", "/api/v1/users/7", "/api/v1/users/7/invite/CODE"]
)
@pytest.mark.parametrize(
    "creds",
    [
        {"headers": {"Authorization": "Bearer garbage.not.a.jwt"}},
        {"cookies": {JWT_COOKIE_NAME: "garbage"}},
        {},
    ],
)
def test_garbage_credentials_hit_guard_over_http(client, path, creds):
    c, calls = client
    if "cookies" in creds:
        c.cookies.set(JWT_COOKIE_NAME, creds["cookies"][JWT_COOKIE_NAME])
    res = c.post(path, json=BODY, headers=creds.get("headers", {}))
    c.cookies.clear()
    assert res.status_code == 403
    assert res.json()["detail"] == "Please complete the verification challenge."
    assert calls == []


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
