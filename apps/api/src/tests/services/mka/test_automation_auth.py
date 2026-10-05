"""MKA fork: webhook signature verification + cron-secret dependency (spec 2026-10-05 section 5)."""

import hashlib
import hmac
import logging

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from src.services.mka import automation_auth as auth

SECRET = "s3cr3t-webhook-value"
BODY = b'{"event":"assignment_submitted","delivery_id":"dlv_0123456789abcdef","timestamp":"2026-10-05T12:00:00Z"}'


def sign(body=BODY, secret=SECRET):
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


# --- verify_webhook_signature -----------------------------------------------------------------------------


def test_a_valid_signature_is_accepted():
    assert auth.verify_webhook_signature(BODY, sign(), SECRET) is True


def test_matches_the_upstream_scheme_exactly():
    """X-Webhook-Signature: sha256=<hex HMAC-SHA256(secret, raw body bytes)> (integration map section 1)."""
    assert sign() == "sha256=" + hmac.new(SECRET.encode(), BODY, hashlib.sha256).hexdigest()
    assert auth.compute_signature(BODY, SECRET) == sign()


def test_a_tampered_body_is_rejected():
    assert auth.verify_webhook_signature(BODY + b" ", sign(), SECRET) is False
    assert auth.verify_webhook_signature(BODY.replace(b"2026", b"2027"), sign(), SECRET) is False
    assert auth.verify_webhook_signature(b"", sign(), SECRET) is False


def test_the_wrong_secret_is_rejected():
    assert auth.verify_webhook_signature(BODY, sign(secret="other"), SECRET) is False
    assert auth.verify_webhook_signature(BODY, sign(), "other") is False


def test_whitespace_reserialised_json_is_rejected_because_only_raw_bytes_count():
    import json

    reserialised = json.dumps(json.loads(BODY)).encode()
    assert reserialised != BODY
    assert auth.verify_webhook_signature(reserialised, sign(), SECRET) is False


@pytest.mark.parametrize("header", [None, "", " ", "sha256=", "sha256", "sha256=abc", "sha256=" + "0" * 63, "sha256=" + "0" * 65,
                                    "sha1=" + "0" * 40, "SHA256=" + "0" * 64, "sha256:" + "0" * 64, "md5=" + "0" * 32,
                                    "0" * 64, "sha256=sha256=" + "0" * 64])
def test_missing_short_or_malformed_headers_are_rejected(header):
    assert auth.verify_webhook_signature(BODY, header, SECRET) is False


def test_uppercase_hex_and_prefix_tricks_are_rejected():
    good = sign()
    assert auth.verify_webhook_signature(BODY, good.upper(), SECRET) is False            # prefix + hex upper-cased
    assert auth.verify_webhook_signature(BODY, "sha256=" + good[7:].upper(), SECRET) is False
    assert auth.verify_webhook_signature(BODY, good[:-1] + good[-1].swapcase() if good[-1].isalpha() else good.upper(), SECRET) is False


def test_surrounding_whitespace_or_control_characters_are_rejected():
    good = sign()
    for bad in (" " + good, good + " ", good + "\n", good + "\x00", "\t" + good, good + "\r\n"):
        assert auth.verify_webhook_signature(BODY, bad, SECRET) is False


def test_non_ascii_header_does_not_raise_and_is_rejected():
    for bad in ("sha256=" + "é" * 64, "sha256=١" * 3, "sha256=" + "\U0001f600" * 16):
        assert auth.verify_webhook_signature(BODY, bad, SECRET) is False


def test_a_unicode_secret_and_body_work():
    secret = "sécret-密码"
    body = '{"name":"Zoë"}'.encode()
    assert auth.verify_webhook_signature(body, sign(body, secret), secret) is True
    assert auth.verify_webhook_signature(body, sign(body, secret), "secret-密码") is False


@pytest.mark.parametrize("secret", ["", None, b"", "   "[:0]])
def test_an_empty_or_missing_secret_always_rejects_even_a_signature_made_with_it(secret):
    forged = "sha256=" + hmac.new(b"", BODY, hashlib.sha256).hexdigest()
    assert auth.verify_webhook_signature(BODY, forged, secret) is False
    assert auth.verify_webhook_signature(BODY, sign(), secret) is False


def test_non_bytes_body_or_header_types_are_rejected_not_raised():
    assert auth.verify_webhook_signature(None, sign(), SECRET) is False
    assert auth.verify_webhook_signature("text", sign(), SECRET) is False
    assert auth.verify_webhook_signature(BODY, 12345, SECRET) is False
    assert auth.verify_webhook_signature(BODY, [sign()], SECRET) is False


def test_the_secret_may_be_bytes():
    assert auth.verify_webhook_signature(BODY, sign(), SECRET.encode()) is True


def test_comparison_is_constant_time(monkeypatch):
    calls = []
    real = hmac.compare_digest

    def spy(a, b):
        calls.append((type(a), type(b)))
        return real(a, b)

    monkeypatch.setattr(auth.hmac, "compare_digest", spy)
    assert auth.verify_webhook_signature(BODY, sign(), SECRET) is True
    assert auth.verify_webhook_signature(BODY, sign(secret="x"), SECRET) is False
    assert calls == [(bytes, bytes), (bytes, bytes)]  # hmac.compare_digest on bytes for BOTH outcomes, never ==


def test_a_forced_compare_digest_false_rejects(monkeypatch):
    monkeypatch.setattr(auth.hmac, "compare_digest", lambda a, b: False)
    assert auth.verify_webhook_signature(BODY, sign(), SECRET) is False


def test_the_module_never_compares_secrets_with_equality():
    import inspect

    src = inspect.getsource(auth)
    assert "compare_digest" in src
    for line in src.splitlines():
        code = line.split("#")[0]
        assert "secret ==" not in code and "== secret" not in code and "signature ==" not in code, line


# --- require_cron_secret --------------------------------------------------------------------------------------


@pytest.fixture
def app():
    app = FastAPI()

    @app.post("/cron", dependencies=[Depends(auth.require_cron_secret)])
    async def cron():
        return {"ok": True}

    return app


def client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


async def test_cron_secret_unconfigured_is_never_open(app, monkeypatch):
    monkeypatch.delenv("MKA_AUTOMATION_CRON_SECRET", raising=False)
    async with client(app) as c:
        for headers in ({}, {"X-MKA-Cron-Secret": ""}, {"X-MKA-Cron-Secret": "anything"}):
            r = await c.post("/cron", headers=headers)
            assert r.status_code == 503, headers
            assert r.json() == {"detail": "Automation is not configured"}


async def test_blank_configured_secret_counts_as_unconfigured(app, monkeypatch):
    monkeypatch.setenv("MKA_AUTOMATION_CRON_SECRET", "   ")
    async with client(app) as c:
        assert (await c.post("/cron", headers={"X-MKA-Cron-Secret": "   "})).status_code == 503
        assert (await c.post("/cron", headers={"X-MKA-Cron-Secret": ""})).status_code == 503


async def test_cron_secret_right_wrong_missing(app, monkeypatch):
    monkeypatch.setenv("MKA_AUTOMATION_CRON_SECRET", "cron-secret-value")
    async with client(app) as c:
        ok = await c.post("/cron", headers={"X-MKA-Cron-Secret": "cron-secret-value"})
        assert ok.status_code == 200 and ok.json() == {"ok": True}
        for headers in ({}, {"X-MKA-Cron-Secret": ""}, {"X-MKA-Cron-Secret": "cron-secret-valu"},
                        {"X-MKA-Cron-Secret": "cron-secret-value2"}, {"X-MKA-Cron-Secret": "CRON-SECRET-VALUE"},
                        {"X-MKA-Cron-Secret": " cron-secret-value"}):
            r = await c.post("/cron", headers=headers)
            assert r.status_code == 401, headers
            assert r.json() == {"detail": "Invalid credentials"}


async def test_cron_secret_is_not_an_org_token_or_bearer(app, monkeypatch):
    monkeypatch.setenv("MKA_AUTOMATION_CRON_SECRET", "cron-secret-value")
    async with client(app) as c:
        assert (await c.post("/cron", headers={"Authorization": "Bearer cron-secret-value"})).status_code == 401
        assert (await c.post("/cron", headers={"X-Webhook-Signature": "cron-secret-value"})).status_code == 401
        assert (await c.post("/cron", params={"secret": "cron-secret-value"})).status_code == 401


async def test_cron_secret_rotation_is_read_at_call_time(app, monkeypatch):
    async with client(app) as c:
        monkeypatch.setenv("MKA_AUTOMATION_CRON_SECRET", "one")
        assert (await c.post("/cron", headers={"X-MKA-Cron-Secret": "one"})).status_code == 200
        monkeypatch.setenv("MKA_AUTOMATION_CRON_SECRET", "two")
        assert (await c.post("/cron", headers={"X-MKA-Cron-Secret": "one"})).status_code == 401
        assert (await c.post("/cron", headers={"X-MKA-Cron-Secret": "two"})).status_code == 200


async def test_cron_secret_uses_a_constant_time_compare(app, monkeypatch):
    monkeypatch.setenv("MKA_AUTOMATION_CRON_SECRET", "cron-secret-value")
    calls = []
    real = hmac.compare_digest

    def spy(a, b):
        calls.append((type(a), type(b)))
        return real(a, b)

    monkeypatch.setattr(auth.hmac, "compare_digest", spy)
    async with client(app) as c:
        await c.post("/cron", headers={"X-MKA-Cron-Secret": "cron-secret-value"})
        await c.post("/cron", headers={"X-MKA-Cron-Secret": "x"})
    assert calls == [(bytes, bytes), (bytes, bytes)]


async def test_a_forced_false_compare_rejects_even_the_right_secret(app, monkeypatch):
    monkeypatch.setenv("MKA_AUTOMATION_CRON_SECRET", "cron-secret-value")
    monkeypatch.setattr(auth.hmac, "compare_digest", lambda a, b: False)
    async with client(app) as c:
        assert (await c.post("/cron", headers={"X-MKA-Cron-Secret": "cron-secret-value"})).status_code == 401


async def test_cron_secret_is_never_logged_or_echoed(app, monkeypatch, caplog):
    monkeypatch.setenv("MKA_AUTOMATION_CRON_SECRET", "cron-secret-value")
    caplog.set_level(logging.DEBUG)
    async with client(app) as c:
        r1 = await c.post("/cron", headers={"X-MKA-Cron-Secret": "guess-attempt-123"})
        r2 = await c.post("/cron", headers={"X-MKA-Cron-Secret": "cron-secret-value"})
    ours = "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("src.services.mka"))
    assert "cron-secret-value" not in ours and "guess-attempt-123" not in ours
    assert "cron-secret-value" not in r1.text + r2.text and "guess-attempt-123" not in r1.text


async def test_non_ascii_secret_header_is_rejected_cleanly(app, monkeypatch):
    monkeypatch.setenv("MKA_AUTOMATION_CRON_SECRET", "cron-secret-value")
    async with client(app) as c:
        r = await c.post("/cron", headers={"X-MKA-Cron-Secret": "café".encode("latin-1")})
        assert r.status_code == 401
