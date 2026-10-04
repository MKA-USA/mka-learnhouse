"""Tests for jev/quality.py (batched quiz validation)."""

from src.services.ai.jev.quality import validate_quiz_questions
from src.tests.services.test_jev_support import (
    FakeClient,
    cfg,
    choice,
    jev_env,
    noul,
    response,
)

LABELS = ["poor", "fair", "good"]


def _q(text="What is 2+2?"):
    return {"question": text, "answers": [
        {"answer": "4", "correct": True}, {"answer": "5", "correct": False}]}


def _answers(i, clear=0.9, key=0.9, dist="good", aligned=0.9):
    return {
        f"q{i}_clear": noul(clear),
        f"q{i}_key": noul(key),
        f"q{i}_distractors": choice(dist, 0.8, LABELS),
        f"q{i}_aligned": noul(aligned),
    }


class TestValidate:
    async def test_single_batched_call_for_all_questions(self):
        ans = {**_answers(0), **_answers(1, key=0.1), **_answers(2, dist="poor")}
        fake = FakeClient(response(ans))
        with jev_env(client=fake):
            out = await validate_quiz_questions([_q(), _q(), _q()], course_content="content")
        assert fake.system_one.call_count == 1
        qs = fake.system_one.call_args.kwargs["questions"]
        assert set(qs) == {f"q{i}_{c}" for i in range(3) for c in ("clear", "key", "distractors", "aligned")}
        assert [r["passed"] for r in out] == [True, False, False]
        assert "Answer key appears incorrect" in out[1]["issues"]
        assert out[2]["distractor_quality"] == "poor"

    async def test_poor_distractors_fail_passed(self):
        fake = FakeClient(response(_answers(0, dist="poor")))
        with jev_env(client=fake):
            out = await validate_quiz_questions([_q()])
        assert out[0]["passed"] is False

    async def test_missing_answer_gives_none_entry(self):
        ans = {**_answers(0), **{k: v for k, v in _answers(1).items() if not k.endswith("key")}}
        fake = FakeClient(response(ans))
        with jev_env(client=fake):
            out = await validate_quiz_questions([_q(), _q()])
        assert out[0] is not None and out[1] is None

    async def test_noul_boundary(self):
        fake = FakeClient(response(_answers(0, clear=0.5)))
        with jev_env(client=fake):
            out = await validate_quiz_questions([_q()])
        assert out[0]["question_clear"] is False  # strictly > 0.5

    async def test_failure_returns_none(self):
        fake = FakeClient(side_effect=RuntimeError("x"))
        with jev_env(client=fake):
            assert await validate_quiz_questions([_q()]) is None

    async def test_disabled_returns_none(self):
        fake = FakeClient(response(_answers(0)))
        with jev_env(cfg(enabled=False), fake):
            assert await validate_quiz_questions([_q()]) is None
        fake.system_one.assert_not_called()

    async def test_empty_returns_none(self):
        with jev_env():
            assert await validate_quiz_questions([]) is None

    async def test_course_content_truncated(self):
        fake = FakeClient(response(_answers(0)))
        with jev_env(client=fake):
            await validate_quiz_questions([_q()], course_content="c" * 9000)
        assert len(fake.system_one.call_args.kwargs["state"]["course_content"]) == 3000


class TestChunking:
    @staticmethod
    def _result_for(state):
        n = sum(1 for k in state if k.endswith("_question"))
        ans = {}
        for i in range(n):
            ans.update(_answers(i))
        from src.services.ai.jev.client import JevResult

        return JevResult(response(ans))

    async def _run(self, n, fail_calls=()):
        from unittest.mock import patch

        calls = []

        async def fake_run(state, questions, **kw):
            idx = len(calls)
            calls.append(len(questions))
            if idx in fail_calls:
                return None
            return self._result_for(state)

        with patch("src.services.ai.jev.quality.run_system_one", fake_run):
            qs = [_q(f"q{i}") for i in range(n)]
            return await validate_quiz_questions(qs), calls

    async def test_17_questions_two_calls(self):
        out, calls = await self._run(17)
        assert sorted(calls) == [4, 64]
        assert len(out) == 17 and all(r is not None for r in out)

    async def test_32_questions_two_calls(self):
        out, calls = await self._run(32)
        assert calls == [64, 64]
        assert len(out) == 32 and all(r["passed"] for r in out)

    async def test_64_questions_four_calls(self):
        out, calls = await self._run(64)
        assert len(calls) == 4 and all(c <= 64 for c in calls)
        assert len(out) == 64 and all(r is not None for r in out)

    async def test_beyond_cap_is_none_aligned(self):
        out, calls = await self._run(70)
        assert len(out) == 70 and len(calls) == 4
        assert all(r is None for r in out[64:]) and all(r is not None for r in out[:64])

    async def test_chunk_failure_only_nones_that_chunk(self):
        # concurrency 2 => call index order follows chunk order for the first two
        out, calls = await self._run(32, fail_calls=(1,))
        assert len(out) == 32
        assert all(r is not None for r in out[:16])
        assert all(r is None for r in out[16:])

    async def test_all_chunks_fail_returns_none(self):
        out, _ = await self._run(32, fail_calls=(0, 1))
        assert out is None
