"""Tests for Jev chat title generation (jev/title.py)."""

import sys
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

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


class TestGenerateChatTitleJev:
    async def test_returns_none_when_disabled(self):
        from src.services.ai.jev.title import generate_chat_title_jev

        with patch("src.services.ai.jev.title.get_learnhouse_config") as mock_cfg:
            mock_cfg.return_value.jev_config = None
            result = await generate_chat_title_jev("What is React?", "React is a library...")
            assert result is None

    async def test_generates_title_with_entity(self):
        from src.services.ai.jev.title import generate_chat_title_jev

        jev = JevConfig(enabled=True, api_key="k")

        fake_answers = {
            "topic": _FakeChoiceAnswer(choice="concept_explanation", confidence=0.9),
            "has_entity": _FakeNoulAnswer(noul=0.95),
            "entity_name": _FakeChoiceAnswer(choice="react", confidence=0.85),
        }
        fake_response = _FakeResponse(answers=fake_answers)

        mock_client = MagicMock()
        mock_client.system_one.return_value = fake_response

        mock_ts_module = MagicMock()
        mock_ts_module.Choice = MagicMock
        mock_ts_module.Noul = MagicMock
        mock_ts_module.TypeSafeClient = MagicMock

        with (
            patch("src.services.ai.jev.title.get_learnhouse_config") as mock_cfg,
            patch("src.services.ai.jev.title._build_client", return_value=mock_client),
            patch.dict(sys.modules, {"typesafe_sdk": mock_ts_module}),
        ):
            mock_cfg.return_value.jev_config = jev
            result = await generate_chat_title_jev("What is React?", "React is a JS library...")

        assert result == "Understanding React"

    async def test_generates_title_without_entity(self):
        from src.services.ai.jev.title import generate_chat_title_jev

        jev = JevConfig(enabled=True, api_key="k")

        fake_answers = {
            "topic": _FakeChoiceAnswer(choice="practical_help", confidence=0.8),
            "has_entity": _FakeNoulAnswer(noul=0.1),
            "entity_name": _FakeChoiceAnswer(choice="none", confidence=0.9),
        }
        fake_response = _FakeResponse(answers=fake_answers)

        mock_client = MagicMock()
        mock_client.system_one.return_value = fake_response

        mock_ts_module = MagicMock()
        mock_ts_module.Choice = MagicMock
        mock_ts_module.Noul = MagicMock
        mock_ts_module.TypeSafeClient = MagicMock

        with (
            patch("src.services.ai.jev.title.get_learnhouse_config") as mock_cfg,
            patch("src.services.ai.jev.title._build_client", return_value=mock_client),
            patch.dict(sys.modules, {"typesafe_sdk": mock_ts_module}),
        ):
            mock_cfg.return_value.jev_config = jev
            result = await generate_chat_title_jev("Help me!", "Sure, what do you need?")

        assert result == "Practical Help"

    async def test_returns_none_on_timeout(self):
        from src.services.ai.jev.title import generate_chat_title_jev

        jev = JevConfig(enabled=True, api_key="k")

        def _slow_call():
            import time
            time.sleep(5)

        mock_client = MagicMock()
        mock_client.system_one.side_effect = _slow_call

        with (
            patch("src.services.ai.jev.title.get_learnhouse_config") as mock_cfg,
            patch("src.services.ai.jev.title._build_client", return_value=mock_client),
        ):
            mock_cfg.return_value.jev_config = jev
            result = await generate_chat_title_jev("test", "test", timeout_seconds=0.05)
            assert result is None

    async def test_returns_none_on_exception(self):
        from src.services.ai.jev.title import generate_chat_title_jev

        jev = JevConfig(enabled=True, api_key="k")

        mock_client = MagicMock()
        mock_client.system_one.side_effect = RuntimeError("API down")

        with (
            patch("src.services.ai.jev.title.get_learnhouse_config") as mock_cfg,
            patch("src.services.ai.jev.title._build_client", return_value=mock_client),
        ):
            mock_cfg.return_value.jev_config = jev
            result = await generate_chat_title_jev("test", "test")
            assert result is None

    async def test_truncates_long_title(self):
        from src.services.ai.jev.title import generate_chat_title_jev

        jev = JevConfig(enabled=True, api_key="k")

        # Simulate a very long entity name
        fake_answers = {
            "topic": _FakeChoiceAnswer(choice="concept_explanation", confidence=0.9),
            "has_entity": _FakeNoulAnswer(noul=0.95),
            "entity_name": _FakeChoiceAnswer(choice="machine_learning", confidence=0.85),
        }
        fake_response = _FakeResponse(answers=fake_answers)

        mock_client = MagicMock()
        mock_client.system_one.return_value = fake_response

        mock_ts_module = MagicMock()
        mock_ts_module.Choice = MagicMock
        mock_ts_module.Noul = MagicMock
        mock_ts_module.TypeSafeClient = MagicMock

        with (
            patch("src.services.ai.jev.title.get_learnhouse_config") as mock_cfg,
            patch("src.services.ai.jev.title._build_client", return_value=mock_client),
            patch.dict(sys.modules, {"typesafe_sdk": mock_ts_module}),
        ):
            mock_cfg.return_value.jev_config = jev
            result = await generate_chat_title_jev("What is ML?", "ML is...")

        assert len(result) <= 60
        assert result == "Understanding Machine Learning"
