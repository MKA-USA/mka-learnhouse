import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi import HTTPException

from src.services.auth import mka_google_only as m
from src.services.auth.mka_google_only import (
    block_email_change,
    block_non_google_auth,
    is_google_only_email,
    require_workspace_hd,
)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv(m.ENV_VAR, "mkausa.org")


@pytest.mark.parametrize("email", [
    "a@mkausa.org", "A@MKAUSA.ORG", "  a@mkausa.org  ", "a@MkaUsa.Org",
])
def test_matches(email):
    assert is_google_only_email(email) is True


@pytest.mark.parametrize("email", [
    "a@evilmkausa.org", "a@mkausa.org.evil.com", "a@sub.mkausa.org",
    "a@xmkausa.org", "a@mkausa.org.", "a@mkausa.com", "a@gmail.com",
    "mkausa.org", "", None, "@mkausa.org", "a@", "a@b@mkausa.org",
    "a@mkausa.org@evil.com",
])
def test_lookalikes_and_malformed_are_not_matched(email):
    assert is_google_only_email(email) is False


def test_multiple_domains_whitespace(monkeypatch):
    monkeypatch.setenv(m.ENV_VAR, " mkausa.org , Other.COM ,, ")
    assert is_google_only_email("x@other.com")
    assert is_google_only_email("x@mkausa.org")
    assert not is_google_only_email("x@third.com")


@pytest.mark.parametrize("val", [None, "", "  ", ","])
def test_unset_or_empty_is_noop(monkeypatch, val):
    if val is None:
        monkeypatch.delenv(m.ENV_VAR, raising=False)
    else:
        monkeypatch.setenv(m.ENV_VAR, val)
    assert is_google_only_email("a@mkausa.org") is False
    block_non_google_auth("a@mkausa.org")
    require_workspace_hd("a@mkausa.org", None)
    block_email_change("a@mkausa.org", "b@mkausa.org")


def test_block_raises_403_without_leaking_config(monkeypatch):
    monkeypatch.setenv(m.ENV_VAR, "secret-internal.example")
    with pytest.raises(HTTPException) as e:
        block_non_google_auth("a@secret-internal.example")
    assert e.value.status_code == 403
    assert "secret-internal" not in e.value.detail
    assert "Google" in e.value.detail


def test_block_allows_other_domains():
    block_non_google_auth("a@gmail.com")
    block_non_google_auth(None)


@pytest.mark.parametrize("hd", [None, "", "  ", "gmail.com", "mkausa.org.evil.com", "sub.mkausa.org"])
def test_hd_missing_or_mismatched_rejected(hd):
    with pytest.raises(HTTPException) as e:
        require_workspace_hd("a@mkausa.org", hd)
    assert e.value.status_code == 403
    assert "mkausa" not in e.value.detail.lower()


@pytest.mark.parametrize("hd", ["mkausa.org", "MKAUSA.ORG", " mkausa.org "])
def test_hd_ok(hd):
    require_workspace_hd("A@mkausa.org", hd)


def test_hd_not_required_for_public_google_users():
    require_workspace_hd("learner@gmail.com", None)
    require_workspace_hd("learner@gmail.com", "someco.com")


def test_email_change_in_and_out_blocked():
    with pytest.raises(HTTPException):
        block_email_change("a@gmail.com", "a@mkausa.org")
    with pytest.raises(HTTPException):
        block_email_change("a@mkausa.org", "a@gmail.com")
    block_email_change("a@gmail.com", "b@gmail.com")
    block_email_change("a@mkausa.org", "A@MKAUSA.ORG")  # unchanged


@pytest.mark.asyncio
async def test_session_chokepoint_blocks_non_google_allows_google():
    from src.services.auth import session as s

    user = MagicMock(id=1, email="a@mkausa.org")
    with patch.object(s, "is_mfa_active", AsyncMock(return_value=False)):
        with pytest.raises(HTTPException) as e:
            await s.issue_session_or_challenge(MagicMock(), user, amr="password")
        assert e.value.status_code == 403
        with pytest.raises(HTTPException):
            await s.issue_session_or_challenge(MagicMock(), user)  # amr None (admin magic link)
        with pytest.raises(HTTPException):
            await s.issue_session_or_challenge(MagicMock(), user, amr="magic_login")
        ok = await s.issue_session_or_challenge(MagicMock(), user, amr="google")
        assert ok.access_token and ok.refresh_token
        other = MagicMock(id=2, email="learner@gmail.com")
        ok2 = await s.issue_session_or_challenge(MagicMock(), other, amr="password")
        assert ok2.access_token


@pytest.mark.asyncio
async def test_password_reset_request_is_generic_and_issues_nothing():
    from src.services.users import password_reset as pr

    msg = "If an account with that email exists, a reset code has been sent"
    db = MagicMock()
    db.execute = AsyncMock(side_effect=AssertionError("must not hit DB"))
    with patch.object(pr, "_get_redis_connection", side_effect=AssertionError("no redis")):
        assert await pr.send_reset_password_code(MagicMock(), db, MagicMock(), 1, "a@mkausa.org") == msg
        assert await pr.send_reset_password_code_platform(MagicMock(), db, MagicMock(), "a@mkausa.org") == msg


@pytest.mark.asyncio
async def test_password_reset_completion_blocked():
    from src.services.users import password_reset as pr

    with pytest.raises(HTTPException) as e:
        await pr.change_password_with_reset_code(
            MagicMock(), MagicMock(), MagicMock(), "NewPassw0rd!42", 1, "a@mkausa.org", "CODE")
    assert e.value.status_code == 403
    with pytest.raises(HTTPException) as e:
        await pr.change_password_with_reset_code_platform(
            MagicMock(), MagicMock(), MagicMock(), "NewPassw0rd!42", "a@mkausa.org", "CODE")
    assert e.value.status_code == 403
