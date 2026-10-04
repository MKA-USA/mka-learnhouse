"""Tests for jev/client.py: gate, run_system_one, singleton, rerank, contract."""

import asyncio
from unittest.mock import patch

import pytest

from src.services.ai.jev import client as mod
from src.services.ai.jev.client import (
    JevResult,
    aclose_jev_client,
    jev_enabled,
    jev_rerank_chunks,
    run_system_one,
)
from src.tests.services.test_jev_support import (
    FakeClient,
    cfg,
    choice,
    jev_env,
    noul,
    response,
    score,
)


@pytest.fixture(autouse=True)
async def _reset_client():
    await aclose_jev_client()
    yield
    await aclose_jev_client()


class TestJevEnabled:
    def test_disabled_flag(self):
        with jev_env(cfg(enabled=False)):
            assert jev_enabled(1) is False

    def test_no_config(self):
        with jev_env(None) as _:
            pass
        with patch.object(mod, "get_learnhouse_config") as m:
            m.return_value.jev_config = None
            assert jev_enabled(1) is False

    def test_missing_key(self):
        with jev_env(cfg(api_key="")):
            assert jev_enabled(1) is False

    def test_org_not_allowed(self):
        with jev_env(cfg(allowed_org_ids=[1])):
            assert jev_enabled(2) is False
            assert jev_enabled(None) is False

    def test_empty_allowlist_disables_everyone(self):
        with jev_env(cfg(allowed_org_ids=[])):
            assert jev_enabled(1) is False

    def test_allowed(self):
        with jev_env(cfg(allowed_org_ids=[1, 5])):
            assert jev_enabled(5) is True


class TestJevResult:
    def test_accessors_with_real_sdk_types(self):
        r = JevResult(response({
            "n": noul(0.3),
            "c": choice("a", 0.8, ["a", "b"]),
            "s": score(1.5, 4),
        }))
        assert r.noul("n") == 0.3
        assert r.choice("c") == ("a", 0.8)
        assert r.score_norm("s") == pytest.approx(0.5)

    @pytest.mark.parametrize("raw,expected", [(0, 0.0), (1.5, 0.5), (3, 1.0)])
    def test_score_normalization_boundaries(self, raw, expected):
        r = JevResult(response({"s": score(raw, 4)}))
        assert r.score_norm("s") == pytest.approx(expected)

    def test_missing_ids_and_wrong_types_return_none(self):
        r = JevResult(response({"n": noul(0.3)}))
        assert r.noul("zzz") is None
        assert r.choice("n") is None
        assert r.score_norm("n") is None
        assert r.noul("n") == 0.3

    def test_score_confidence(self):
        r = JevResult(response({"s": score(3, 4, conf=0.4)}))
        assert r.score_with_confidence("s") == (1.0, 0.4)


class TestRunSystemOne:
    async def test_disabled_returns_none_without_client(self):
        fake = FakeClient(response({"n": noul(0.1)}))
        with jev_env(cfg(enabled=False), fake):
            assert await run_system_one({"a": "b"}, {"n": object()}) is None
        fake.system_one.assert_not_called()

    async def test_success(self):
        fake = FakeClient(response({"n": noul(0.1)}))
        with jev_env(client=fake):
            r = await run_system_one({"a": "b"}, {"n": object()})
        assert r is not None and r.noul("n") == 0.1
        kwargs = fake.system_one.call_args.kwargs
        assert kwargs["state"] == {"a": "b"}
        assert kwargs["timeout"] == 3.0

    async def test_exception_returns_none(self):
        fake = FakeClient(side_effect=RuntimeError("boom"))
        with jev_env(client=fake):
            assert await run_system_one({}, {"n": object()}) is None

    async def test_timeout_returns_none(self):
        async def slow(**_):
            await asyncio.sleep(5)

        fake = FakeClient()
        fake.system_one.side_effect = slow
        with jev_env(client=fake):
            assert await run_system_one({}, {"n": object()}, timeout=0.05) is None

    async def test_cancelled_propagates(self):
        fake = FakeClient(side_effect=asyncio.CancelledError())
        with jev_env(client=fake), pytest.raises(asyncio.CancelledError):
            await run_system_one({}, {"n": object()})

    async def test_logs_never_contain_content_or_key(self, caplog):
        fake = FakeClient(side_effect=RuntimeError("generic failure"))
        with jev_env(cfg(api_key="sk-secret-123"), fake):
            with caplog.at_level("DEBUG"):
                await run_system_one({"q": "my private question"}, {"n": object()})
        text = caplog.text
        assert "my private question" not in text
        assert "sk-secret-123" not in text


class TestClientSingleton:
    async def test_explicit_api_key_and_retry_policy(self):
        pytest.importorskip("typesafe_sdk")
        import typesafe_sdk

        captured = {}

        class _Stub:
            def __init__(self, **kw):
                captured.update(kw)

            async def aclose(self):
                pass

        with jev_env(cfg(api_key="explicit-key", timeout=2.5)):
            with patch.object(typesafe_sdk, "AsyncTypeSafeClient", _Stub):
                client = await mod._get_client(cfg(api_key="explicit-key", timeout=2.5))
        assert isinstance(client, _Stub)
        assert captured["api_key"] == "explicit-key"
        assert captured["timeout"] == 2.5
        assert captured["retry"].max_retries <= 1
        assert captured["retry"].timeout == 2.5

    async def test_reuse_and_concurrent_init_creates_one(self):
        import typesafe_sdk

        created = []

        class _Stub:
            def __init__(self, **kw):
                created.append(self)

            async def aclose(self):
                pass

        c = cfg()
        with patch.object(typesafe_sdk, "AsyncTypeSafeClient", _Stub):
            clients = await asyncio.gather(*[mod._get_client(c) for _ in range(10)])
            again = await mod._get_client(c)
        assert len(created) == 1
        assert all(x is created[0] for x in clients) and again is created[0]

    async def test_aclose_closes_and_resets(self):
        import typesafe_sdk

        created = []

        class _Stub:
            def __init__(self, **kw):
                self.closed = False
                created.append(self)

            async def aclose(self):
                self.closed = True

        c = cfg()
        with patch.object(typesafe_sdk, "AsyncTypeSafeClient", _Stub):
            first = await mod._get_client(c)
            await aclose_jev_client()
            assert first.closed is True
            second = await mod._get_client(c)
        assert second is not first
        await aclose_jev_client()
        await aclose_jev_client()  # idempotent


def _chunks(n):
    return [f"chunk text {i}" for i in range(n)]


class TestRerank:
    async def test_orders_by_norm_score_then_confidence(self):
        ans = {
            "rel_0": score(0, 4),
            "rel_1": score(3, 4, conf=0.5),
            "rel_2": score(3, 4, conf=0.9),
            "rel_3": score(1.5, 4),
        }
        fake = FakeClient(response(ans))
        with jev_env(client=fake):
            out = await jev_rerank_chunks("q", _chunks(4), top_k=3)
        assert out == ["chunk text 2", "chunk text 1", "chunk text 3"]

    async def test_accepts_objects_with_chunk_text(self):
        class Row:
            def __init__(self, t):
                self.chunk_text = t

        rows = [Row("a"), Row("b")]
        fake = FakeClient(response({"rel_0": score(0, 4), "rel_1": score(3, 4)}))
        with jev_env(client=fake):
            out = await jev_rerank_chunks("q", rows, top_k=2)
        assert out == [rows[1], rows[0]]

    async def test_missing_answer_returns_none(self):
        fake = FakeClient(response({"rel_0": score(3, 4)}))
        with jev_env(client=fake):
            assert await jev_rerank_chunks("q", _chunks(2), top_k=2) is None

    async def test_none_result_returns_none(self):
        fake = FakeClient(side_effect=RuntimeError("x"))
        with jev_env(client=fake):
            assert await jev_rerank_chunks("q", _chunks(2), top_k=2) is None

    async def test_empty_chunks_none(self):
        with jev_env():
            assert await jev_rerank_chunks("q", [], top_k=2) is None

    async def test_payload_truncated_and_capped(self):
        n = 13
        ans = {f"rel_{i}": score(i % 4, 4) for i in range(10)}
        fake = FakeClient(response(ans))
        long = ["x" * 5000 for _ in range(n)]
        with jev_env(client=fake):
            out = await jev_rerank_chunks("q" * 900, long, top_k=12)
        state = fake.system_one.call_args.kwargs["state"]
        qs = fake.system_one.call_args.kwargs["questions"]
        assert len([k for k in state if k.startswith("chunk_")]) == 10
        assert len(qs) == 10
        assert all(len(state[f"chunk_{i}"]) == 1000 for i in range(10))
        assert len(state["user_question"]) <= 500
        assert len(out) == 12  # 10 scored + extras in vector order, trimmed to top_k


class TestSdkContract:
    def test_real_sdk_accessors_exist(self):
        sdk = pytest.importorskip("typesafe_sdk")
        for name in ("AsyncTypeSafeClient", "RetryPolicy", "Score", "Choice", "Noul"):
            assert hasattr(sdk, name)
        fields = sdk.SystemOneResponse.model_fields
        assert "answers" in fields
        for prop in ("nouls", "choices", "scores"):
            assert hasattr(sdk.SystemOneResponse, prop)
        assert "noul" in sdk.NoulAnswer.model_fields
        assert {"choice", "confidence"} <= set(sdk.ChoiceAnswer.model_fields)
        assert {"score", "confidence", "legend"} <= set(sdk.ScoreAnswer.model_fields)
        assert hasattr(sdk.AsyncTypeSafeClient, "aclose")
        import inspect
        assert "api_key" in inspect.signature(sdk.AsyncTypeSafeClient.__init__).parameters
        assert "timeout" in inspect.signature(sdk.AsyncTypeSafeClient.system_one).parameters


@pytest.mark.asyncio
async def test_rerank_returns_none_when_sdk_import_fails():
    """A missing/broken SDK must fail open (None), not raise out of rerank."""
    import sys

    with patch.dict(sys.modules, {"typesafe_sdk": None}):
        assert await jev_rerank_chunks("q", ["a", "b"], 1) is None
