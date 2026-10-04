"""Tests for Jev content moderation (jev/moderation.py)."""

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


class TestModerateContent:
    async def test_returns_none_when_disabled(self):
        from src.services.ai.jev.moderation import moderate_content

        with patch("src.services.ai.jev.moderation.get_learnhouse_config") as mock_cfg:
            mock_cfg.return_value.jev_config = None
            result = await moderate_content("Some content")
            assert result is None

    async def test_passes_clean_content(self):
        from src.services.ai.jev.moderation import moderate_content

        jev = JevConfig(enabled=True, api_key="k")

        fake_answers = {
            "has_pii": _FakeNoulAnswer(noul=0.05),
            "is_toxic": _FakeNoulAnswer(noul=0.02),
            "is_spam": _FakeNoulAnswer(noul=0.01),
        }
        fake_response = _FakeResponse(answers=fake_answers)

        mock_client = MagicMock()
        mock_client.system_one.return_value = fake_response

        mock_ts_module = MagicMock()
        mock_ts_module.Noul = MagicMock
        mock_ts_module.Score = MagicMock
        mock_ts_module.TypeSafeClient = MagicMock

        with (
            patch("src.services.ai.jev.moderation.get_learnhouse_config") as mock_cfg,
            patch("src.services.ai.jev.moderation._build_client", return_value=mock_client),
            patch.dict(sys.modules, {"typesafe_sdk": mock_ts_module}),
        ):
            mock_cfg.return_value.jev_config = jev
            result = await moderate_content("This is a clean educational post about Python.")

        assert result is not None
        assert result["passed"] is True
        assert result["has_pii"] is False
        assert result["is_toxic"] is False
        assert result["is_spam"] is False

    async def test_flags_pii(self):
        from src.services.ai.jev.moderation import moderate_content

        jev = JevConfig(enabled=True, api_key="k")

        fake_answers = {
            "has_pii": _FakeNoulAnswer(noul=0.95),
            "is_toxic": _FakeNoulAnswer(noul=0.02),
            "is_spam": _FakeNoulAnswer(noul=0.01),
        }
        fake_response = _FakeResponse(answers=fake_answers)

        mock_client = MagicMock()
        mock_client.system_one.return_value = fake_response

        mock_ts_module = MagicMock()
        mock_ts_module.Noul = MagicMock
        mock_ts_module.Score = MagicMock
        mock_ts_module.TypeSafeClient = MagicMock

        with (
            patch("src.services.ai.jev.moderation.get_learnhouse_config") as mock_cfg,
            patch("src.services.ai.jev.moderation._build_client", return_value=mock_client),
            patch.dict(sys.modules, {"typesafe_sdk": mock_ts_module}),
        ):
            mock_cfg.return_value.jev_config = jev
            result = await moderate_content("Contact me at john@example.com or 555-1234")

        assert result is not None
        assert result["passed"] is False
        assert result["has_pii"] is True
        assert "personally identifiable information" in result["reasons"][0]

    async def test_flags_toxic_content(self):
        from src.services.ai.jev.moderation import moderate_content

        jev = JevConfig(enabled=True, api_key="k")

        fake_answers = {
            "has_pii": _FakeNoulAnswer(noul=0.05),
            "is_toxic": _FakeNoulAnswer(noul=0.9),
            "is_spam": _FakeNoulAnswer(noul=0.01),
        }
        fake_response = _FakeResponse(answers=fake_answers)

        mock_client = MagicMock()
        mock_client.system_one.return_value = fake_response

        mock_ts_module = MagicMock()
        mock_ts_module.Noul = MagicMock
        mock_ts_module.Score = MagicMock
        mock_ts_module.TypeSafeClient = MagicMock

        with (
            patch("src.services.ai.jev.moderation.get_learnhouse_config") as mock_cfg,
            patch("src.services.ai.jev.moderation._build_client", return_value=mock_client),
            patch.dict(sys.modules, {"typesafe_sdk": mock_ts_module}),
        ):
            mock_cfg.return_value.jev_config = jev
            result = await moderate_content("Some toxic content here")

        assert result is not None
        assert result["passed"] is False
        assert result["is_toxic"] is True

    async def test_checks_academic_integrity_for_assignments(self):
        from src.services.ai.jev.moderation import moderate_content

        jev = JevConfig(enabled=True, api_key="k")

        fake_answers = {
            "has_pii": _FakeNoulAnswer(noul=0.05),
            "is_toxic": _FakeNoulAnswer(noul=0.02),
            "is_spam": _FakeNoulAnswer(noul=0.01),
            "academic_integrity": _FakeScoreAnswer(score=0.85, confidence=0.7),
        }
        fake_response = _FakeResponse(answers=fake_answers)

        mock_client = MagicMock()
        mock_client.system_one.return_value = fake_response

        mock_ts_module = MagicMock()
        mock_ts_module.Noul = MagicMock
        mock_ts_module.Score = MagicMock
        mock_ts_module.TypeSafeClient = MagicMock

        with (
            patch("src.services.ai.jev.moderation.get_learnhouse_config") as mock_cfg,
            patch("src.services.ai.jev.moderation._build_client", return_value=mock_client),
            patch.dict(sys.modules, {"typesafe_sdk": mock_ts_module}),
        ):
            mock_cfg.return_value.jev_config = jev
            result = await moderate_content(
                "This assignment is about machine learning...",
                context="assignment_submission",
            )

        assert result is not None
        assert result["passed"] is False
        assert result["academic_integrity"] == "high"
        assert "academic integrity" in result["reasons"][0]

    async def test_returns_none_on_timeout(self):
        from src.services.ai.jev.moderation import moderate_content

        jev = JevConfig(enabled=True, api_key="k")

        def _slow_call():
            import time
            time.sleep(5)

        mock_client = MagicMock()
        mock_client.system_one.side_effect = _slow_call

        with (
            patch("src.services.ai.jev.moderation.get_learnhouse_config") as mock_cfg,
            patch("src.services.ai.jev.moderation._build_client", return_value=mock_client),
        ):
            mock_cfg.return_value.jev_config = jev
            result = await moderate_content("test", timeout_seconds=0.05)
            assert result is None
