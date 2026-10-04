import pytest
from fastapi import HTTPException

from src.services.auth.mka_domain_guard import (
    ENV_VAR,
    enforce_allowed_google_domain as guard,
)


def test_unset_allows_anything(monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)
    guard("a@gmail.com", "other.com")


def test_empty_allows_anything(monkeypatch):
    monkeypatch.setenv(ENV_VAR, " , ")
    guard("a@gmail.com")


def test_allowed_passes_case_insensitive(monkeypatch):
    monkeypatch.setenv(ENV_VAR, " MKAUSA.org ")
    guard("User@MkaUsa.ORG", "mkausa.org")
    guard("user@mkausa.org", None)
    guard("user@mkausa.org", "")


@pytest.mark.parametrize(
    "email",
    [
        "a@gmail.com",
        "a@evilmkausa.org",
        "a@mkausa.org.evil.com",
        "user@sub.mkausa.org",
        "",
        "nodomain",
        "a@",
    ],
)
def test_rejected(monkeypatch, email):
    monkeypatch.setenv(ENV_VAR, "mkausa.org")
    with pytest.raises(HTTPException) as exc:
        guard(email)
    assert exc.value.status_code == 403
    assert "mkausa" not in exc.value.detail


def test_hd_mismatch_rejected(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "mkausa.org")
    with pytest.raises(HTTPException) as exc:
        guard("a@mkausa.org", "other.com")
    assert exc.value.status_code == 403


def test_multiple_domains(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "mkausa.org, Example.com")
    guard("a@example.com", "example.com")
    guard("a@mkausa.org")
    with pytest.raises(HTTPException):
        guard("a@third.com")
