"""Tests for jev/moderation.py."""

import pytest

from src.services.ai.jev.moderation import integrity_level, moderate_content
from src.tests.services.test_jev_support import (
    FakeClient,
    cfg,
    jev_env,
    noul,
    response,
    score,
)


def _resp(pii=0.1, tox=0.1, spam=0.1, integrity=None):
    ans = {"pii": noul(pii), "toxicity": noul(tox), "spam": noul(spam)}
    if integrity is not None:
        ans["academic_integrity"] = integrity
    return response(ans)


class TestModerate:
    async def test_allow_clean(self):
        fake = FakeClient(_resp())
        with jev_env(client=fake):
            r = await moderate_content("hello", kind="forum_post")
        assert r.action == "allow" and r.reasons == [] and r.academic_integrity is None
        assert "academic_integrity" not in fake.system_one.call_args.kwargs["questions"]

    @pytest.mark.parametrize("field,kw", [("pii", "pii"), ("toxicity", "tox"), ("spam", "spam")])
    async def test_flag(self, field, kw):
        fake = FakeClient(_resp(**{kw: 0.9}))
        with jev_env(client=fake):
            r = await moderate_content("x")
        assert r.action == "flag" and getattr(r, field) == 0.9

    async def test_never_blocks(self):
        fake = FakeClient(_resp(pii=1, tox=1, spam=1, integrity=score(2, 3)))
        with jev_env(client=fake):
            r = await moderate_content("x", kind="assignment_submission")
        assert r.action in {"allow", "flag"} and r.action == "flag"

    @pytest.mark.parametrize("raw,level,action", [
        (0.66, "low", "allow"),      # norm 0.33
        (0.68, "medium", "allow"),   # norm 0.34
        (1.32, "medium", "allow"),   # norm 0.66
        (1.34, "high", "flag"),      # norm 0.67
        (0.0, "low", "allow"),
        (2.0, "high", "flag"),
    ])
    async def test_integrity_boundaries(self, raw, level, action):
        fake = FakeClient(_resp(integrity=score(raw, 3)))
        with jev_env(client=fake):
            r = await moderate_content("essay", kind="assignment_submission")
        assert r.integrity_level == level and r.action == action

    def test_integrity_level_exact_thresholds(self):
        assert integrity_level(0.33) == "low"
        assert integrity_level(0.34) == "medium"
        assert integrity_level(0.66) == "medium"
        assert integrity_level(0.67) == "high"
        assert integrity_level(None) == "low"

    async def test_missing_answers_none(self):
        fake = FakeClient(response({"pii": noul(0.1)}))
        with jev_env(client=fake):
            assert await moderate_content("x") is None

    async def test_missing_integrity_for_assignment_none(self):
        fake = FakeClient(_resp())
        with jev_env(client=fake):
            assert await moderate_content("x", kind="assignment_submission") is None

    async def test_disabled_none(self):
        fake = FakeClient(_resp())
        with jev_env(cfg(enabled=False), fake):
            assert await moderate_content("x") is None
        fake.system_one.assert_not_called()

    async def test_org_not_allowed_none(self):
        fake = FakeClient(_resp())
        with jev_env(cfg(allowed_org_ids=[1]), fake):
            assert await moderate_content("x", org_id=2) is None
            assert await moderate_content("x", org_id=1) is not None

    async def test_exception_none(self):
        fake = FakeClient(side_effect=RuntimeError("x"))
        with jev_env(client=fake):
            assert await moderate_content("x") is None

    async def test_timeout_none(self):
        import asyncio

        async def slow(**_):
            await asyncio.sleep(5)

        fake = FakeClient()
        fake.system_one.side_effect = slow
        with jev_env(cfg(timeout=0.05), fake):
            assert await moderate_content("x") is None

    async def test_content_truncated_and_empty_skipped(self):
        fake = FakeClient(_resp())
        with jev_env(client=fake):
            await moderate_content("a" * 9000)
            assert len(fake.system_one.call_args.kwargs["state"]["content"]) == 3000
            assert await moderate_content("   ") is None
