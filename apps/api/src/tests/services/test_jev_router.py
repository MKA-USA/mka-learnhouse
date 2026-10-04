"""Tests for jev/router.py."""

import pytest

from src.services.ai.jev.router import (
    QuestionIntent,
    classify_question,
    is_confident_general_knowledge,
)
from src.tests.services.test_jev_support import (
    FakeClient,
    choice,
    jev_env,
    noul,
    response,
)

INTENTS = ["content_lookup", "concept_explanation", "practical_help",
           "general_knowledge", "meta_question", "clarification"]


def _resp(label="general_knowledge", conf=0.9, needs=0.1):
    return response({"intent": choice(label, conf, INTENTS), "needs_rag": noul(needs)})


class TestShouldSkipRag:
    def test_none_never_skips(self):
        assert is_confident_general_knowledge(None) is False

    @pytest.mark.parametrize("conf,expected", [(0.69, False), (0.7, True), (0.95, True)])
    def test_confidence_boundary(self, conf, expected):
        assert is_confident_general_knowledge(QuestionIntent("general_knowledge", conf, 0.0)) is expected

    @pytest.mark.parametrize("needs,expected", [(0.19, True), (0.2, False), (0.9, False)])
    def test_needs_rag_boundary(self, needs, expected):
        assert is_confident_general_knowledge(QuestionIntent("general_knowledge", 0.9, needs)) is expected

    def test_other_intents_never_skip(self):
        for i in INTENTS:
            if i != "general_knowledge":
                assert is_confident_general_knowledge(QuestionIntent(i, 0.99, 0.0)) is False


class TestClassify:
    async def test_basic(self):
        fake = FakeClient(_resp())
        with jev_env(client=fake):
            r = await classify_question("what is 2+2", course_name="Math")
        assert r == QuestionIntent("general_knowledge", 0.9, 0.1)
        state = fake.system_one.call_args.kwargs["state"]
        assert state["course_name"] == "Math"
        assert "recent_conversation" not in state

    async def test_history_included_last_four_truncated(self):
        fake = FakeClient(_resp("clarification", 0.8, 0.9))
        hist = [{"role": "user", "content": f"msg{i} " + "z" * 1000} for i in range(6)]
        with jev_env(client=fake):
            await classify_question("explain more", history=hist)
        text = fake.system_one.call_args.kwargs["state"]["recent_conversation"]
        assert "msg0" not in text and "msg1" not in text
        assert all(f"msg{i}" in text for i in (2, 3, 4, 5))
        assert all(len(line) <= 300 + 10 for line in text.splitlines())

    async def test_history_objects(self):
        class T:
            role = "assistant"
            content = "hello there"

        fake = FakeClient(_resp())
        with jev_env(client=fake):
            await classify_question("q", history=[T()])
        assert "assistant: hello there" in fake.system_one.call_args.kwargs["state"]["recent_conversation"]

    async def test_missing_answer_returns_none(self):
        fake = FakeClient(response({"intent": choice("content_lookup", 0.9, INTENTS)}))
        with jev_env(client=fake):
            assert await classify_question("q") is None

    async def test_failure_returns_none(self):
        fake = FakeClient(side_effect=RuntimeError("x"))
        with jev_env(client=fake):
            assert await classify_question("q") is None
