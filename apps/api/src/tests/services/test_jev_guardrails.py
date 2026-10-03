"""Tests for Jev output guardrails (jev/guardrails.py)."""

import sys
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

from config.config import JevConfig


@dataclass
class _FakeNoulAnswer:
    noul: float


@dataclass
class _FakeScoreAnswer:
    score: float
    confidence: float


@dataclass
class _FakeResponse:
    answers: dict


class TestCheckResponseGuardrails:
    async def test_returns_none_when_disabled(self):
        from src.services.ai.jev.guardrails import check_response_guardrails

        with patch("src.services.ai.jev.guardrails.get_learnhouse_config") as mock_cfg:
            mock_cfg.return_value.jev_config = None
            result = await check_response_guardrails("Some response text")
            assert result is None

    async def test_passes_clean_response(self):
        from src.services.ai.jev.guardrails import check_response_guardrails

        jev = JevConfig(enabled=True, api_key="k")

        fake_answers = {
            "has_pii": _FakeNoulAnswer(noul=0.05),
            "is_inappropriate": _FakeNoulAnswer(noul=0.02),
            "hallucination_risk": _FakeScoreAnswer(score=0.2, confidence=0.8),
        }
        fake_response = _FakeResponse(answers=fake_answers)

        mock_client = MagicMock()
        mock_client.system_one.return_value = fake_response

        mock_ts_module = MagicMock()
        mock_ts_module.Noul = MagicMock
        mock_ts_module.Score = MagicMock
        mock_ts_module.TypeSafeClient = MagicMock

        with (
            patch("src.services.ai.jev.guardrails.get_learnhouse_config") as mock_cfg,
            patch("src.services.ai.jev.guardrails._build_client", return_value=mock_client),
            patch.dict(sys.modules, {"typesafe_sdk": mock_ts_module}),
        ):
            mock_cfg.return_value.jev_config = jev
            result = await check_response_guardrails(
                "React is a JavaScript library for building user interfaces.",
                user_question="What is React?",
                source_context="React is a JS library created by Meta.",
            )

        assert result is not None
        assert result.passed is True
        assert result.scores["has_pii"] < 0.5
        assert result.scores["is_inappropriate"] < 0.5

    async def test_flags_pii(self):
        from src.services.ai.jev.guardrails import check_response_guardrails

        jev = JevConfig(enabled=True, api_key="k")

        fake_answers = {
            "has_pii": _FakeNoulAnswer(noul=0.95),
            "is_inappropriate": _FakeNoulAnswer(noul=0.02),
            "hallucination_risk": _FakeScoreAnswer(score=0.1, confidence=0.9),
        }
        fake_response = _FakeResponse(answers=fake_answers)

        mock_client = MagicMock()
        mock_client.system_one.return_value = fake_response

        mock_ts_module = MagicMock()
        mock_ts_module.Noul = MagicMock
        mock_ts_module.Score = MagicMock
        mock_ts_module.TypeSafeClient = MagicMock

        with (
            patch("src.services.ai.jev.guardrails.get_learnhouse_config") as mock_cfg,
            patch("src.services.ai.jev.guardrails._build_client", return_value=mock_client),
            patch.dict(sys.modules, {"typesafe_sdk": mock_ts_module}),
        ):
            mock_cfg.return_value.jev_config = jev
            result = await check_response_guardrails(
                "Contact me at john@example.com or call 555-1234.",
                user_question="How do I contact support?",
            )

        assert result is not None
        assert result.passed is False
        assert result.reason == "PII detected"

    async def test_flags_inappropriate_content(self):
        from src.services.ai.jev.guardrails import check_response_guardrails

        jev = JevConfig(enabled=True, api_key="k")

        fake_answers = {
            "has_pii": _FakeNoulAnswer(noul=0.05),
            "is_inappropriate": _FakeNoulAnswer(noul=0.9),
            "hallucination_risk": _FakeScoreAnswer(score=0.1, confidence=0.9),
        }
        fake_response = _FakeResponse(answers=fake_answers)

        mock_client = MagicMock()
        mock_client.system_one.return_value = fake_response

        mock_ts_module = MagicMock()
        mock_ts_module.Noul = MagicMock
        mock_ts_module.Score = MagicMock
        mock_ts_module.TypeSafeClient = MagicMock

        with (
            patch("src.services.ai.jev.guardrails.get_learnhouse_config") as mock_cfg,
            patch("src.services.ai.jev.guardrails._build_client", return_value=mock_client),
            patch.dict(sys.modules, {"typesafe_sdk": mock_ts_module}),
        ):
            mock_cfg.return_value.jev_config = jev
            result = await check_response_guardrails("Some inappropriate content here")

        assert result is not None
        assert result.passed is False
        assert result.reason == "Inappropriate content"

    async def test_flags_high_hallucination_risk(self):
        from src.services.ai.jev.guardrails import check_response_guardrails

        jev = JevConfig(enabled=True, api_key="k")

        fake_answers = {
            "has_pii": _FakeNoulAnswer(noul=0.05),
            "is_inappropriate": _FakeNoulAnswer(noul=0.02),
            "hallucination_risk": _FakeScoreAnswer(score=0.85, confidence=0.7),
        }
        fake_response = _FakeResponse(answers=fake_answers)

        mock_client = MagicMock()
        mock_client.system_one.return_value = fake_response

        mock_ts_module = MagicMock()
        mock_ts_module.Noul = MagicMock
        mock_ts_module.Score = MagicMock
        mock_ts_module.TypeSafeClient = MagicMock

        with (
            patch("src.services.ai.jev.guardrails.get_learnhouse_config") as mock_cfg,
            patch("src.services.ai.jev.guardrails._build_client", return_value=mock_client),
            patch.dict(sys.modules, {"typesafe_sdk": mock_ts_module}),
        ):
            mock_cfg.return_value.jev_config = jev
            result = await check_response_guardrails(
                "The answer is 42.",
                user_question="What is the meaning of life?",
                source_context="The context says nothing about 42.",
            )

        assert result is not None
        assert result.passed is False
        assert result.reason == "High hallucination risk"

    async def test_returns_none_on_timeout(self):
        from src.services.ai.jev.guardrails import check_response_guardrails

        jev = JevConfig(enabled=True, api_key="k")

        def _slow_call():
            import time
            time.sleep(5)

        mock_client = MagicMock()
        mock_client.system_one.side_effect = _slow_call

        with (
            patch("src.services.ai.jev.guardrails.get_learnhouse_config") as mock_cfg,
            patch("src.services.ai.jev.guardrails._build_client", return_value=mock_client),
        ):
            mock_cfg.return_value.jev_config = jev
            result = await check_response_guardrails("test", timeout_seconds=0.05)
            assert result is None

    async def test_returns_none_on_exception(self):
        from src.services.ai.jev.guardrails import check_response_guardrails

        jev = JevConfig(enabled=True, api_key="k")

        mock_client = MagicMock()
        mock_client.system_one.side_effect = RuntimeError("API down")

        with (
            patch("src.services.ai.jev.guardrails.get_learnhouse_config") as mock_cfg,
            patch("src.services.ai.jev.guardrails._build_client", return_value=mock_client),
        ):
            mock_cfg.return_value.jev_config = jev
            result = await check_response_guardrails("test")
            assert result is None
