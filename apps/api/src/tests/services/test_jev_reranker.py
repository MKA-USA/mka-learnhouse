"""Tests for Jev RAG reranking integration.

Covers:
- _resolve_rag_limits returns correct retrieve/final k values
- jev_rerank_chunks resorts chunks by Jev score
- Fallback on Jev error returns None
- Feature flag disabled skips Jev entirely
"""

import pytest
from unittest.mock import patch, MagicMock
from dataclasses import dataclass

from config.config import JevConfig


# ---------------------------------------------------------------------------
# _resolve_rag_limits
# ---------------------------------------------------------------------------

class TestResolveRagLimits:
    def test_no_jev_config_returns_same_values(self):
        from src.services.ai.rag.query_service import _resolve_rag_limits

        with patch("src.services.ai.rag.query_service.get_learnhouse_config") as mock_cfg:
            mock_cfg.return_value.jev_config = None
            retrieve, final = _resolve_rag_limits(5)
            assert retrieve == 5
            assert final == 5

    def test_jev_disabled_returns_same_values(self):
        from src.services.ai.rag.query_service import _resolve_rag_limits

        jev = JevConfig(enabled=False, rerank_enabled=True, rerank_candidates=10)
        with patch("src.services.ai.rag.query_service.get_learnhouse_config") as mock_cfg:
            mock_cfg.return_value.jev_config = jev
            retrieve, final = _resolve_rag_limits(5)
            assert retrieve == 5
            assert final == 5

    def test_jev_enabled_expands_retrieve(self):
        from src.services.ai.rag.query_service import _resolve_rag_limits

        jev = JevConfig(
            enabled=True,
            api_key="test-key",
            rerank_enabled=True,
            rerank_candidates=10,
            rerank_top_k=5,
        )
        with patch("src.services.ai.rag.query_service.get_learnhouse_config") as mock_cfg:
            mock_cfg.return_value.jev_config = jev
            retrieve, final = _resolve_rag_limits(5)
            assert retrieve == 10
            assert final == 5

    def test_jev_rerank_disabled_returns_same_values(self):
        from src.services.ai.rag.query_service import _resolve_rag_limits

        jev = JevConfig(
            enabled=True,
            api_key="test-key",
            rerank_enabled=False,
            rerank_candidates=10,
        )
        with patch("src.services.ai.rag.query_service.get_learnhouse_config") as mock_cfg:
            mock_cfg.return_value.jev_config = jev
            retrieve, final = _resolve_rag_limits(5)
            assert retrieve == 5
            assert final == 5


# ---------------------------------------------------------------------------
# jev_rerank_chunks
# ---------------------------------------------------------------------------

@dataclass
class _FakeScoreAnswer:
    score: float
    confidence: float


@dataclass
class _FakeResponse:
    answers: dict


class TestJevRerankChunks:
    async def test_returns_none_when_disabled(self):
        from src.services.ai.jev.client import jev_rerank_chunks

        with patch("src.services.ai.jev.client._get_jev_config", return_value=None):
            result = await jev_rerank_chunks("q", ["a", "b"])
            assert result is None

    async def test_returns_none_on_empty_chunks(self):
        from src.services.ai.jev.client import jev_rerank_chunks

        jev = JevConfig(enabled=True, api_key="k", rerank_enabled=True)
        with patch("src.services.ai.jev.client._get_jev_config", return_value=jev):
            result = await jev_rerank_chunks("q", [])
            assert result is None

    async def test_reranks_by_score_descending(self):
        import sys
        from src.services.ai.jev.client import jev_rerank_chunks

        jev = JevConfig(enabled=True, api_key="k", rerank_enabled=True)

        fake_answers = {
            "rel_0": _FakeScoreAnswer(score=0.2, confidence=0.8),
            "rel_1": _FakeScoreAnswer(score=0.9, confidence=0.9),
            "rel_2": _FakeScoreAnswer(score=0.5, confidence=0.7),
        }
        fake_response = _FakeResponse(answers=fake_answers)

        mock_client = MagicMock()
        mock_client.system_one.return_value = fake_response

        mock_score_cls = MagicMock()
        mock_ts_module = MagicMock()
        mock_ts_module.Score = mock_score_cls
        mock_ts_module.TypeSafeClient = MagicMock

        with (
            patch("src.services.ai.jev.client._get_jev_config", return_value=jev),
            patch("src.services.ai.jev.client._build_client", return_value=mock_client),
            patch.dict(sys.modules, {"typesafe_sdk": mock_ts_module}),
        ):
            result = await jev_rerank_chunks("test question", ["chunk_a", "chunk_b", "chunk_c"])

        assert result is not None
        assert len(result) == 3
        assert result[0].index == 1  # highest score (0.9)
        assert result[0].score == 0.9
        assert result[1].index == 2  # second (0.5)
        assert result[2].index == 0  # lowest (0.2)

    async def test_returns_none_on_exception(self):
        from src.services.ai.jev.client import jev_rerank_chunks

        jev = JevConfig(enabled=True, api_key="k", rerank_enabled=True)

        mock_client = MagicMock()
        mock_client.system_one.side_effect = RuntimeError("API down")

        with (
            patch("src.services.ai.jev.client._get_jev_config", return_value=jev),
            patch("src.services.ai.jev.client._build_client", return_value=mock_client),
        ):
            result = await jev_rerank_chunks("q", ["a", "b"])
            assert result is None

    async def test_returns_none_on_timeout(self):
        from src.services.ai.jev.client import jev_rerank_chunks

        jev = JevConfig(enabled=True, api_key="k", rerank_enabled=True, timeout_seconds=0.05)

        def _slow_call():
            import time
            time.sleep(5)

        mock_client = MagicMock()
        mock_client.system_one.side_effect = _slow_call

        with (
            patch("src.services.ai.jev.client._get_jev_config", return_value=jev),
            patch("src.services.ai.jev.client._build_client", return_value=mock_client),
        ):
            result = await jev_rerank_chunks("q", ["a", "b"], timeout_seconds=0.05)
            assert result is None


# ---------------------------------------------------------------------------
# _jev_rerank (query_service integration)
# ---------------------------------------------------------------------------

class TestJevRerankIntegration:
    async def test_fallback_to_vector_ordering_on_none(self):
        from src.services.ai.rag.query_service import _jev_rerank

        @dataclass
        class _Row:
            chunk_text: str
            activity_uuid: str
            source_type: str
            block_uuid: str

        rows = [
            _Row("chunk_a", "a1", "text", "b1"),
            _Row("chunk_b", "a2", "text", "b2"),
            _Row("chunk_c", "a3", "text", "b3"),
        ]

        jev = JevConfig(enabled=True, api_key="k")
        with (
            patch("src.services.ai.rag.query_service.get_learnhouse_config") as mock_cfg,
            patch("src.services.ai.jev.client.jev_rerank_chunks", return_value=None),
        ):
            mock_cfg.return_value.jev_config = jev
            result = await _jev_rerank("question", rows, final_k=2)

        assert len(result) == 2
        assert result[0].chunk_text == "chunk_a"
        assert result[1].chunk_text == "chunk_b"

    async def test_reorders_by_jev_scores(self):
        from src.services.ai.rag.query_service import _jev_rerank
        from src.services.ai.jev.client import RerankResult

        @dataclass
        class _Row:
            chunk_text: str
            activity_uuid: str
            source_type: str
            block_uuid: str

        rows = [
            _Row("low_relevance", "a1", "text", "b1"),
            _Row("high_relevance", "a2", "text", "b2"),
            _Row("mid_relevance", "a3", "text", "b3"),
        ]

        jev_results = [
            RerankResult(index=1, score=0.9, confidence=0.9),
            RerankResult(index=2, score=0.5, confidence=0.7),
            RerankResult(index=0, score=0.2, confidence=0.8),
        ]

        jev = JevConfig(enabled=True, api_key="k")
        with (
            patch("src.services.ai.rag.query_service.get_learnhouse_config") as mock_cfg,
            patch("src.services.ai.jev.client.jev_rerank_chunks", return_value=jev_results),
        ):
            mock_cfg.return_value.jev_config = jev
            result = await _jev_rerank("question", rows, final_k=2)

        assert len(result) == 2
        assert result[0].chunk_text == "high_relevance"
        assert result[1].chunk_text == "mid_relevance"
