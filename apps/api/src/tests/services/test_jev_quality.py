"""Tests for Jev quiz quality validation (jev/quality.py)."""

import sys
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

from config.config import JevConfig


@dataclass
class _FakeNoulAnswer:
    noul: float


@dataclass
class _FakeChoiceAnswer:
    choice: str
    confidence: float


@dataclass
class _FakeResponse:
    answers: dict


class TestValidateQuizQuestion:
    async def test_returns_none_when_disabled(self):
        from src.services.ai.jev.quality import validate_quiz_question

        with patch("src.services.ai.jev.quality.get_learnhouse_config") as mock_cfg:
            mock_cfg.return_value.jev_config = None
            result = await validate_quiz_question("What is 2+2?", [{"answer": "4", "correct": True}])
            assert result is None

    async def test_passes_good_question(self):
        from src.services.ai.jev.quality import validate_quiz_question

        jev = JevConfig(enabled=True, api_key="k")

        fake_answers = {
            "question_clear": _FakeNoulAnswer(noul=0.95),
            "answer_key_correct": _FakeNoulAnswer(noul=0.9),
            "distractor_quality": _FakeChoiceAnswer(choice="good", confidence=0.8),
            "content_aligned": _FakeNoulAnswer(noul=0.85),
        }
        fake_response = _FakeResponse(answers=fake_answers)

        mock_client = MagicMock()
        mock_client.system_one.return_value = fake_response

        mock_ts_module = MagicMock()
        mock_ts_module.Noul = MagicMock
        mock_ts_module.Score = MagicMock
        mock_ts_module.Choice = MagicMock
        mock_ts_module.TypeSafeClient = MagicMock

        with (
            patch("src.services.ai.jev.quality.get_learnhouse_config") as mock_cfg,
            patch("src.services.ai.jev.quality._build_client", return_value=mock_client),
            patch.dict(sys.modules, {"typesafe_sdk": mock_ts_module}),
        ):
            mock_cfg.return_value.jev_config = jev
            result = await validate_quiz_question(
                "What is the capital of France?",
                [{"answer": "Paris", "correct": True}, {"answer": "London", "correct": False}],
            )

        assert result is not None
        assert result["passed"] is True
        assert result["question_clear"] is True
        assert result["answer_key_correct"] is True
        assert result["distractor_quality"] == "good"
        assert len(result["issues"]) == 0

    async def test_flags_unclear_question(self):
        from src.services.ai.jev.quality import validate_quiz_question

        jev = JevConfig(enabled=True, api_key="k")

        fake_answers = {
            "question_clear": _FakeNoulAnswer(noul=0.2),
            "answer_key_correct": _FakeNoulAnswer(noul=0.9),
            "distractor_quality": _FakeChoiceAnswer(choice="fair", confidence=0.7),
            "content_aligned": _FakeNoulAnswer(noul=0.8),
        }
        fake_response = _FakeResponse(answers=fake_answers)

        mock_client = MagicMock()
        mock_client.system_one.return_value = fake_response

        mock_ts_module = MagicMock()
        mock_ts_module.Noul = MagicMock
        mock_ts_module.Score = MagicMock
        mock_ts_module.Choice = MagicMock
        mock_ts_module.TypeSafeClient = MagicMock

        with (
            patch("src.services.ai.jev.quality.get_learnhouse_config") as mock_cfg,
            patch("src.services.ai.jev.quality._build_client", return_value=mock_client),
            patch.dict(sys.modules, {"typesafe_sdk": mock_ts_module}),
        ):
            mock_cfg.return_value.jev_config = jev
            result = await validate_quiz_question(
                "What is it?",
                [{"answer": "A thing", "correct": True}],
            )

        assert result is not None
        assert result["passed"] is False
        assert "Question is ambiguous or unclear" in result["issues"]

    async def test_flags_incorrect_answer_key(self):
        from src.services.ai.jev.quality import validate_quiz_question

        jev = JevConfig(enabled=True, api_key="k")

        fake_answers = {
            "question_clear": _FakeNoulAnswer(noul=0.9),
            "answer_key_correct": _FakeNoulAnswer(noul=0.1),
            "distractor_quality": _FakeChoiceAnswer(choice="good", confidence=0.8),
            "content_aligned": _FakeNoulAnswer(noul=0.8),
        }
        fake_response = _FakeResponse(answers=fake_answers)

        mock_client = MagicMock()
        mock_client.system_one.return_value = fake_response

        mock_ts_module = MagicMock()
        mock_ts_module.Noul = MagicMock
        mock_ts_module.Score = MagicMock
        mock_ts_module.Choice = MagicMock
        mock_ts_module.TypeSafeClient = MagicMock

        with (
            patch("src.services.ai.jev.quality.get_learnhouse_config") as mock_cfg,
            patch("src.services.ai.jev.quality._build_client", return_value=mock_client),
            patch.dict(sys.modules, {"typesafe_sdk": mock_ts_module}),
        ):
            mock_cfg.return_value.jev_config = jev
            result = await validate_quiz_question(
                "What is 2+2?",
                [{"answer": "5", "correct": True}],
            )

        assert result is not None
        assert result["passed"] is False
        assert "Answer key appears incorrect" in result["issues"]

    async def test_flags_poor_distractors(self):
        from src.services.ai.jev.quality import validate_quiz_question

        jev = JevConfig(enabled=True, api_key="k")

        fake_answers = {
            "question_clear": _FakeNoulAnswer(noul=0.9),
            "answer_key_correct": _FakeNoulAnswer(noul=0.9),
            "distractor_quality": _FakeChoiceAnswer(choice="poor", confidence=0.85),
            "content_aligned": _FakeNoulAnswer(noul=0.8),
        }
        fake_response = _FakeResponse(answers=fake_answers)

        mock_client = MagicMock()
        mock_client.system_one.return_value = fake_response

        mock_ts_module = MagicMock()
        mock_ts_module.Noul = MagicMock
        mock_ts_module.Score = MagicMock
        mock_ts_module.Choice = MagicMock
        mock_ts_module.TypeSafeClient = MagicMock

        with (
            patch("src.services.ai.jev.quality.get_learnhouse_config") as mock_cfg,
            patch("src.services.ai.jev.quality._build_client", return_value=mock_client),
            patch.dict(sys.modules, {"typesafe_sdk": mock_ts_module}),
        ):
            mock_cfg.return_value.jev_config = jev
            result = await validate_quiz_question(
                "What is 2+2?",
                [{"answer": "4", "correct": True}, {"answer": "Banana", "correct": False}],
            )

        assert result is not None
        assert result["passed"] is True  # Still passes, just a warning
        assert "Distractors are too obviously wrong" in result["issues"]

    async def test_returns_none_on_timeout(self):
        from src.services.ai.jev.quality import validate_quiz_question

        jev = JevConfig(enabled=True, api_key="k")

        def _slow_call():
            import time
            time.sleep(5)

        mock_client = MagicMock()
        mock_client.system_one.side_effect = _slow_call

        with (
            patch("src.services.ai.jev.quality.get_learnhouse_config") as mock_cfg,
            patch("src.services.ai.jev.quality._build_client", return_value=mock_client),
        ):
            mock_cfg.return_value.jev_config = jev
            result = await validate_quiz_question("test", [], timeout_seconds=0.05)
            assert result is None
