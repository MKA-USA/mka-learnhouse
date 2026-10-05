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


# --- IP trust model: right-most globally routable XFF entry -----------------


@pytest.mark.parametrize(
    "peer,xff,expected",
    [
        # nginx APPENDS ($proxy_add_x_forwarded_for): attacker entries sit on the LEFT
        ("127.0.0.1", "1.2.3.4, 8.8.4.4, 172.18.0.2", "8.8.4.4"),
        ("127.0.0.1", "9.9.9.9, 5.6.7.8, 8.8.4.4, 172.18.0.2", "8.8.4.4"),
        ("10.0.1.7", "8.8.4.4, 172.18.0.2", "8.8.4.4"),
        ("127.0.0.1", "8.8.4.4", "8.8.4.4"),
        ("127.0.0.1", "garbage, 8.8.4.4, 10.0.0.1", "8.8.4.4"),
        ("127.0.0.1", "fe80::1%eth0, 8.8.4.4, fe80::2%eth0", "8.8.4.4"),  # link-local hops
        ("127.0.0.1", "2001:4860:4860::8888%eth0", "2001:4860:4860::8888"),  # zone stripped
        ("127.0.0.1", "::ffff:8.8.4.4", "8.8.4.4"),  # IPv4-mapped unwrapped
        ("127.0.0.1", "8.8.4.4 , 172.18.0.2 ", "8.8.4.4"),
        # public direct peer: headers are never trusted
        ("8.8.8.8", "1.2.3.4, 9.9.9.9", "8.8.8.8"),
    ],
)
def test_mka_client_ip_takes_rightmost_global_entry(peer, xff, expected):
    assert guard.mka_client_ip(_request(peer, {"X-Forwarded-For": xff})) == expected


@pytest.mark.parametrize(
    "xff",
    [
        "",
        "10.0.0.1, 172.18.0.2",
        "garbage",
        "unknown",
        " , ",
        "9.9.9.9, 100.64.1.1",  # proxy-appended client is not global: never walk further left
        "8.8.4.4, garbage, 10.0.0.1",  # unparseable client entry: stop
        "8.8.4.4, 224.0.0.1",
        "x" * 10000,
        ",".join(["8.8.4.4"] * 2000),
        "\u00ff\u00fe, 10.0.0.1",
    ],
)
def test_mka_client_ip_without_global_entry_is_not_distinguishable(xff):
    ip = guard.mka_client_ip(_request("127.0.0.1", {"X-Forwarded-For": xff}))
    assert not guard._is_distinguishable_client_ip(ip)


def test_rotating_spoofed_first_entry_keeps_one_bucket():
    keys = []
    for spoof in ["1.1.1.1", "2.2.2.2", "3.3.3.3"]:
        req = _request("127.0.0.1", {"X-Forwarded-For": f"{spoof}, 8.8.4.4, 172.18.0.2"})
        with patch(PATCH_CHECK, return_value=(True, 1, 3600)) as check:
            guard.enforce_mka_signup_rate_limit(req)
        keys.append(check.call_args.kwargs["key"])
    assert keys == ["signup:8.8.4.4"] * 3


@pytest.mark.parametrize("ip", ["", "unknown", None])
def test_empty_or_unknown_ip_never_creates_a_key(ip):
    with patch.object(guard, "mka_client_ip", return_value=ip), patch(PATCH_CHECK) as check:
        guard.enforce_mka_signup_rate_limit(_request())
    check.assert_not_called()


def test_multiple_xff_header_lines_are_joined():
    scope = {
        "type": "http", "method": "POST", "path": "/", "query_string": b"",
        "client": ("127.0.0.1", 1),
        "headers": [(b"x-forwarded-for", b"1.1.1.1"), (b"x-forwarded-for", b"8.8.4.4, 10.0.0.2")],
    }
    assert guard.mka_client_ip(Request(scope)) == "8.8.4.4"


def test_public_direct_peer_is_canonicalized():
    assert guard.mka_client_ip(_request("::ffff:8.8.8.8")) == "8.8.8.8"


@pytest.mark.parametrize(
    "a,b,same",
    [
        ("::ffff:1.2.3.4", "1.2.3.4", True),
        ("2001:db8:1:2::1", "2001:db8:1:2:ffff::9", True),  # same /64
        ("2a00:1450:4001:81a::1", "2a00:1450:4001:81a:abcd::2", True),
        ("2a00:1450:4001:81a::1", "2a00:1450:4001:81b::1", False),  # different /64
        ("8.8.8.8", "8.8.4.4", False),
    ],
)
def test_bucket_keys(a, b, same):
    assert (guard.mka_rate_limit_bucket(a) == guard.mka_rate_limit_bucket(b)) is same


def test_ipv6_client_keyed_on_slash_64():
    req1 = _request("127.0.0.1", {"X-Forwarded-For": "2a00:1450:4001:81a::1, 10.0.0.2"})
    req2 = _request("127.0.0.1", {"X-Forwarded-For": "2a00:1450:4001:81a::dead:beef, 10.0.0.2"})
    keys = []
    for req in (req1, req2):
        with patch(PATCH_CHECK, return_value=(True, 1, 3600)) as check:
            guard.enforce_mka_signup_rate_limit(req)
        keys.append(check.call_args.kwargs["key"])
    assert keys[0] == keys[1] == "signup:2a00:1450:4001:81a::/64"


def test_mapped_and_plain_ipv4_share_a_key():
    keys = []
    for xff in ("::ffff:8.8.4.4, 10.0.0.2", "8.8.4.4, 10.0.0.2"):
        with patch(PATCH_CHECK, return_value=(True, 1, 3600)) as check:
            guard.enforce_mka_signup_rate_limit(_request("127.0.0.1", {"X-Forwarded-For": xff}))
        keys.append(check.call_args.kwargs["key"])
    assert keys == ["signup:8.8.4.4", "signup:8.8.4.4"]
