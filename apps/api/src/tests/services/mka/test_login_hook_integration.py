"""MKA fork: hook A2 in issue_session_or_challenge (fail-open, Google-only)."""

from datetime import datetime
from unittest.mock import patch

import pytest

from src.db.users import User
from src.services.auth.session import issue_session_or_challenge
from src.services.mka import attributes as svc


async def _user(db, email="tabligh.albany@mkausa.org"):
    u = User(id=5, username="u5", first_name="F", last_name="L", email=email, password="x",
             user_uuid="user_5", signup_method="google",
             creation_date=str(datetime.now()), update_date=str(datetime.now()))
    db.add(u)
    await db.commit()
    return u


@pytest.mark.asyncio
async def test_google_login_derives_attributes_and_mints_session(db):
    u = await _user(db)
    with patch("src.services.auth.session.is_mfa_active", return_value=False):
        result = await issue_session_or_challenge(db, u, amr="google")
    assert result.access_token and not result.mfa_required
    row = await svc.get_row(db, 5)
    assert row is not None and row.eff_department == "tabligh"


@pytest.mark.asyncio
async def test_login_still_succeeds_when_derivation_explodes(db):
    u = await _user(db)
    with patch("src.services.auth.session.is_mfa_active", return_value=False), \
         patch.object(svc, "parse_identity", side_effect=RuntimeError("boom")):
        result = await issue_session_or_challenge(db, u, amr="google")
    assert result.access_token
    assert await svc.get_row(db, 5) is None


@pytest.mark.asyncio
async def test_mfa_challenge_path_still_derives(db):
    u = await _user(db)
    with patch("src.services.auth.session.is_mfa_active", return_value=True):
        result = await issue_session_or_challenge(db, u, amr="google")
    assert result.mfa_required and result.mfa_token
    assert await svc.get_row(db, 5) is not None


@pytest.mark.asyncio
async def test_password_login_does_not_derive(db):
    u = await _user(db, "someone@gmail.com")
    with patch("src.services.auth.session.is_mfa_active", return_value=False):
        await issue_session_or_challenge(db, u, amr="password")
    assert await svc.get_row(db, 5) is None
