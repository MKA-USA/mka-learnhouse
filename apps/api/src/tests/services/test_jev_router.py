"""Tests for Jev query intent classification (jev/router.py)."""

import sys
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from config.config import JevConfig


@dataclass
class _FakeChoiceAnswer:
    choice: str
    confidence: float


@dataclass
class _FakeNoulAnswer:
    noul: float


@dataclass
class _FakeResponse:
    answers: dict


class TestClassifyQuestion:
    async def test_returns_none_when_disabled(self):
        from src.services.ai.jev.router import classify_question

        with patch("src.services.ai.jev.router.get_learnhouse_config") as mock_cfg:
            mock_cfg.return_value.jev_config = None
            result = await classify_question("What is photosynthesis?")
            assert result is None

    async def test_returns_none_when_jev_not_enabled(self):
        from src.services.ai.jev.router import classify_question

        jev = JevConfig(enabled=False)
        with patch("src.services.ai.jev.router.get_learnhouse_config") as mock_cfg:
            mock_cfg.return_value.jev_config = jev
            result = await classify_question("What is photosynthesis?")
            assert result is None

    async def test_classifies_general_knowledge(self):
        from src.services.ai.jev.router import classify_question

        jev = JevConfig(enabled=True, api_key="k")

        fake_answers = {
            "intent": _FakeChoiceAnswer(choice="general_knowledge", confidence=0.9),
            "needs_rag": _FakeNoulAnswer(noul=0.1),
            "is_followup": _FakeNoulAnswer(noul=0.05),
        }
        fake_response = _FakeResponse(answers=fake_answers)

        mock_client = MagicMock()
        mock_client.system_one.return_value = fake_response

        mock_ts_module = MagicMock()
        mock_ts_module.Choice = MagicMock
        mock_ts_module.Noul = MagicMock
        mock_ts_module.TypeSafeClient = MagicMock

        with (
            patch("src.services.ai.jev.router.get_learnhouse_config") as mock_cfg,
            patch("src.services.ai.jev.router._build_client", return_value=mock_client),
            patch.dict(sys.modules, {"typesafe_sdk": mock_ts_module}),
        ):
            mock_cfg.return_value.jev_config = jev
            result = await classify_question("What is the capital of France?")

        assert result is not None
        assert result.intent == "general_knowledge"
        assert result.needs_rag is False
        assert result.is_followup is False

    async def test_classifies_content_lookup(self):
        from src.services.ai.jev.router import classify_question

        jev = JevConfig(enabled=True, api_key="k")

        fake_answers = {
            "intent": _FakeChoiceAnswer(choice="content_lookup", confidence=0.85),
            "needs_rag": _FakeNoulAnswer(noul=0.9),
            "is_followup": _FakeNoulAnswer(noul=0.1),
        }
        fake_response = _FakeResponse(answers=fake_answers)

        mock_client = MagicMock()
        mock_client.system_one.return_value = fake_response

        mock_ts_module = MagicMock()
        mock_ts_module.Choice = MagicMock
        mock_ts_module.Noul = MagicMock
        mock_ts_module.TypeSafeClient = MagicMock

        with (
            patch("src.services.ai.jev.router.get_learnhouse_config") as mock_cfg,
            patch("src.services.ai.jev.router._build_client", return_value=mock_client),
            patch.dict(sys.modules, {"typesafe_sdk": mock_ts_module}),
        ):
            mock_cfg.return_value.jev_config = jev
            result = await classify_question(
                "Where is the section on photosynthesis?",
                course_name="Biology 101",
            )

        assert result is not None
        assert result.intent == "content_lookup"
        assert result.needs_rag is True
        assert result.is_followup is False

    async def test_classifies_followup(self):
        from src.services.ai.jev.router import classify_question

        jev = JevConfig(enabled=True, api_key="k")

        fake_answers = {
            "intent": _FakeChoiceAnswer(choice="clarification", confidence=0.8),
            "needs_rag": _FakeNoulAnswer(noul=0.3),
            "is_followup": _FakeNoulAnswer(noul=0.95),
        }
        fake_response = _FakeResponse(answers=fake_answers)

        mock_client = MagicMock()
        mock_client.system_one.return_value = fake_response

        mock_ts_module = MagicMock()
        mock_ts_module.Choice = MagicMock
        mock_ts_module.Noul = MagicMock
        mock_ts_module.TypeSafeClient = MagicMock

        with (
            patch("src.services.ai.jev.router.get_learnhouse_config") as mock_cfg,
            patch("src.services.ai.jev.router._build_client", return_value=mock_client),
            patch.dict(sys.modules, {"typesafe_sdk": mock_ts_module}),
        ):
            mock_cfg.return_value.jev_config = jev
            result = await classify_question("Can you explain that more simply?")

        assert result is not None
        assert result.intent == "clarification"
        assert result.is_followup is True

    async def test_returns_none_on_timeout(self):
        from src.services.ai.jev.router import classify_question

        jev = JevConfig(enabled=True, api_key="k")

        def _slow_call():
            import time
            time.sleep(5)

        mock_client = MagicMock()
        mock_client.system_one.side_effect = _slow_call

        with (
            patch("src.services.ai.jev.router.get_learnhouse_config") as mock_cfg,
            patch("src.services.ai.jev.router._build_client", return_value=mock_client),
        ):
            mock_cfg.return_value.jev_config = jev
            result = await classify_question("test", timeout_seconds=0.05)
            assert result is None

    async def test_returns_none_on_exception(self):
        from src.services.ai.jev.router import classify_question

        jev = JevConfig(enabled=True, api_key="k")

        mock_client = MagicMock()
        mock_client.system_one.side_effect = RuntimeError("API down")

        with (
            patch("src.services.ai.jev.router.get_learnhouse_config") as mock_cfg,
            patch("src.services.ai.jev.router._build_client", return_value=mock_client),
        ):
            mock_cfg.return_value.jev_config = jev
            result = await classify_question("test")
            assert result is None

    async def test_defaults_to_concept_explanation_on_missing_answer(self):
        from src.services.ai.jev.router import classify_question

        jev = JevConfig(enabled=True, api_key="k")

        fake_response = _FakeResponse(answers={})
        mock_client = MagicMock()
        mock_client.system_one.return_value = fake_response

        mock_ts_module = MagicMock()
        mock_ts_module.Choice = MagicMock
        mock_ts_module.Noul = MagicMock
        mock_ts_module.TypeSafeClient = MagicMock

        with (
            patch("src.services.ai.jev.router.get_learnhouse_config") as mock_cfg,
            patch("src.services.ai.jev.router._build_client", return_value=mock_client),
            patch.dict(sys.modules, {"typesafe_sdk": mock_ts_module}),
        ):
            mock_cfg.return_value.jev_config = jev
            result = await classify_question("test")

        assert result is not None
        assert result.intent == "concept_explanation"
        assert result.needs_rag is True
        assert result.is_followup is False
