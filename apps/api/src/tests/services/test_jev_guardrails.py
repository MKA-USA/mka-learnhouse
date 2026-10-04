"""Tests for jev/guardrails.py."""

import logging

import pytest

from src.services.ai.jev.guardrails import (
    audit_response,
    check_response_guardrails,
)
from src.tests.services.test_jev_support import (
    FakeClient,
    cfg,
    jev_env,
    noul,
    response,
    score,
)


def _resp(pii=0.1, bad=0.1, halluc=None, levels=3):
    ans = {"has_pii": noul(pii), "is_inappropriate": noul(bad)}
    if halluc is not None:
        ans["hallucination_risk"] = halluc
    return response(ans)


class TestCheck:
    async def test_passes_clean(self):
        fake = FakeClient(_resp(halluc=score(0, 3)))
        with jev_env(client=fake):
            r = await check_response_guardrails("hi", source_context="ctx")
        assert r.passed is True and r.scores["hallucination_risk"] == 0.0

    async def test_pii_flagged(self):
        fake = FakeClient(_resp(pii=0.9, halluc=noul(0.1)))
        with jev_env(client=fake):
            r = await check_response_guardrails("hi")
        assert r.passed is False and "PII" in r.reason

    async def test_inappropriate_flagged(self):
        fake = FakeClient(_resp(bad=0.6, halluc=noul(0.1)))
        with jev_env(client=fake):
            r = await check_response_guardrails("hi")
        assert not r.passed and "Inappropriate" in r.reason

    @pytest.mark.parametrize("raw,flagged", [
        (0.0, False), (1.0, False),   # norm 0.0 / 0.5
        (1.32, False),                # norm 0.66
        (1.34, True),                 # norm 0.67
        (2.0, True),
    ])
    async def test_hallucination_score_boundary(self, raw, flagged):
        fake = FakeClient(_resp(halluc=score(raw, 3)))
        with jev_env(client=fake):
            r = await check_response_guardrails("hi", source_context="ctx")
        assert (not r.passed) is flagged

    async def test_noul_hallucination_without_context(self):
        fake = FakeClient(_resp(halluc=noul(0.51)))
        with jev_env(client=fake):
            r = await check_response_guardrails("hi")
        assert not r.passed and "hallucination" in r.reason

    async def test_fail_open_none(self):
        fake = FakeClient(side_effect=RuntimeError("x"))
        with jev_env(client=fake):
            assert await check_response_guardrails("hi") is None

    async def test_missing_answers_fail_open(self):
        fake = FakeClient(response({}))
        with jev_env(client=fake):
            r = await check_response_guardrails("hi")
        assert r.passed is True

    async def test_disabled_none(self):
        fake = FakeClient(_resp())
        with jev_env(cfg(enabled=False), fake):
            assert await check_response_guardrails("hi") is None
        fake.system_one.assert_not_called()

    async def test_payload_truncated(self):
        fake = FakeClient(_resp(halluc=noul(0.1)))
        with jev_env(client=fake):
            await check_response_guardrails("a" * 5000, user_question="q" * 900, source_context="c" * 5000)
        s = fake.system_one.call_args.kwargs["state"]
        assert len(s["llm_response"]) == 2000
        assert len(s["user_question"]) == 500
        assert len(s["source_context"]) == 2000


class TestAudit:
    async def test_never_raises(self):
        fake = FakeClient(side_effect=RuntimeError("x"))
        with jev_env(client=fake):
            assert await audit_response("hello") is None

    async def test_swallows_unexpected_errors(self, monkeypatch):
        from src.services.ai.jev import guardrails

        async def boom(*a, **k):
            raise ValueError("bad")

        monkeypatch.setattr(guardrails, "check_response_guardrails", boom)
        assert await audit_response("hello") is None

    async def test_logs_flag_without_content(self, caplog):
        fake = FakeClient(_resp(pii=0.9, halluc=noul(0.1)))
        with jev_env(client=fake), caplog.at_level(logging.DEBUG):
            await audit_response("secret student text", user_question="private q")
        assert "flagged" in caplog.text
        assert "secret student text" not in caplog.text
        assert "private q" not in caplog.text

    async def test_org_not_allowed_skips(self):
        fake = FakeClient(_resp())
        with jev_env(cfg(allowed_org_ids=[1]), fake):
            await audit_response("hello", org_id=2)
        fake.system_one.assert_not_called()

    async def test_empty_text_skips(self):
        fake = FakeClient(_resp())
        with jev_env(client=fake):
            await audit_response("  ")
        fake.system_one.assert_not_called()
