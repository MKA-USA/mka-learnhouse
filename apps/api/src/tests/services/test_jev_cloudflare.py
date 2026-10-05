"""Provider-neutral Jev: Cloudflare Clef transport, model resolution, parity."""

import asyncio
import json
import logging
from contextlib import contextmanager
from unittest.mock import patch

import httpx
import pytest

from src.services.ai.jev import client as mod
from src.services.ai.jev.client import JevResult, aclose_jev_client, run_system_one
from src.tests.services.test_jev_support import cfg, choice, noul, response, score

SECRET = "cf-secret-token-XYZ"
STATE_TEXT = "private student essay text"
BODY_TEXT = "upstream-body-leak"
ACCT = "acct123"

ANSWERS = {
    "n": {"type": "noul", "noul": 0.3},
    "c": {"type": "choice", "choice": "a", "probabilities": {"a": 0.8, "b": 0.2}, "confidence": 0.8},
    "s": {"type": "score", "score": 1.5, "legend": {"0": "l0", "1": "l1", "2": "l2", "3": "l3"},
          "probabilities": {"0": 0.25, "1": 0.25, "2": 0.25, "3": 0.25}, "confidence": 0.9},
}
INNER = {"model": "clef-flash", "answers": ANSWERS, "usage": {"input_tokens": 5, "output_tokens": 2}}
QUESTIONS = {"n": {"type": "noul", "instructions": "x?"}}


@pytest.fixture(autouse=True)
async def _reset():
    await aclose_jev_client()
    yield
    await aclose_jev_client()


def ccfg(**kw):
    base = {"provider": "cloudflare", "api_key": SECRET, "cloudflare_account_id": ACCT}
    base.update(kw)
    return cfg(**base)


@contextmanager
def cf_env(handler, config=None):
    seen = []

    def wrapped(request: httpx.Request):
        seen.append(request)
        return handler(request)

    with patch.object(mod, "get_learnhouse_config") as m, \
            patch.object(mod, "_cf_transport", httpx.MockTransport(wrapped)):
        m.return_value.jev_config = config or ccfg()
        yield seen


def ok(body=None):
    return lambda r: httpx.Response(200, json=body if body is not None else INNER)


class TestRequestShape:
    async def test_url_headers_body(self):
        with cf_env(ok()) as seen:
            r = await run_system_one({"t": STATE_TEXT}, QUESTIONS, capability="rerank")
        assert r is not None and r.noul("n") == 0.3
        req = seen[0]
        assert req.method == "POST"
        assert str(req.url) == (
            f"https://api.cloudflare.com/client/v4/accounts/{ACCT}/ai/run/@cf/cloudflare/clef-flash"
        )
        assert req.headers["authorization"] == f"Bearer {SECRET}"
        assert json.loads(req.content) == {
            "model": "clef-flash",
            "state": {"t": STATE_TEXT},
            "questions": QUESTIONS,
        }

    async def test_sdk_question_objects_serialized(self):
        from typesafe_sdk import Score

        q = {"s": Score(instructions="how?", criteria=["a", "b"])}
        with cf_env(ok()) as seen:
            await run_system_one({"t": "x"}, q)
        assert json.loads(seen[0].content)["questions"]["s"] == {
            "type": "score", "instructions": "how?", "criteria": ["a", "b"]
        }

    async def test_unsafe_account_or_model_rejected(self):
        with cf_env(ok(), ccfg(cloudflare_account_id="a/../b")) as seen:
            assert await run_system_one({}, QUESTIONS) is None
        assert not seen

    async def test_model_prefix_stripped(self):
        with cf_env(ok(), ccfg(model="@cf/cloudflare/clef")) as seen:
            await run_system_one({}, QUESTIONS)
        assert str(seen[0].url).endswith("/ai/run/@cf/cloudflare/clef")
        assert json.loads(seen[0].content)["model"] == "clef"


class TestModelResolution:
    def test_precedence(self):
        c = ccfg(model="clef", models={"rerank": "clef-flash"})
        assert mod._resolve_model(c, "rerank") == "clef-flash"
        assert mod._resolve_model(c, "quiz") == "clef"
        assert mod._resolve_model(c, None) == "clef"

    def test_defaults(self):
        assert mod._resolve_model(ccfg(), "quiz") == "clef-flash"
        assert mod._resolve_model(cfg(), "quiz") is None

    async def test_override_used_in_request(self):
        with cf_env(ok(), ccfg(models={"guardrails": "clef"})) as seen:
            await run_system_one({}, QUESTIONS, capability="guardrails")
            await run_system_one({}, QUESTIONS, capability="rerank")
        assert [json.loads(r.content)["model"] for r in seen] == ["clef", "clef-flash"]

    async def test_typesafe_passes_model_only_when_set(self):
        from src.tests.services.test_jev_support import FakeClient, jev_env

        fake = FakeClient(response({"n": noul(0.1)}))
        with jev_env(cfg(models={"quiz": "jev-x"}), fake):
            await run_system_one({}, {"n": object()}, capability="quiz")
            await run_system_one({}, {"n": object()}, capability="rerank")
        calls = fake.system_one.call_args_list
        assert calls[0].kwargs["model"] == "jev-x"
        assert "model" not in calls[1].kwargs


class TestEnvelope:
    async def test_wrapped_and_bare(self):
        wrapped = {"result": INNER, "success": True, "errors": [], "messages": []}
        for body in (wrapped, INNER):
            with cf_env(ok(body)):
                r = await run_system_one({}, QUESTIONS)
            assert r is not None and r.noul("n") == 0.3
            await aclose_jev_client()

    @pytest.mark.parametrize("body", [
        {"result": INNER, "success": False, "errors": []},
        {"result": INNER, "success": True, "errors": [{"code": 1, "message": BODY_TEXT}]},
        {"success": True, "result": {"no": "answers"}},
        ["list"],
    ])
    async def test_failures_return_none(self, body):
        with cf_env(ok(body)):
            assert await run_system_one({}, QUESTIONS) is None


class TestErrors:
    @pytest.mark.parametrize("status", [401, 403, 400, 404])
    async def test_4xx_no_retry(self, status):
        with cf_env(lambda r: httpx.Response(status, text=BODY_TEXT)) as seen:
            assert await run_system_one({}, QUESTIONS) is None
        assert len(seen) == 1

    @pytest.mark.parametrize("status", [429, 500, 503])
    async def test_retry_once_then_none(self, status):
        with cf_env(lambda r: httpx.Response(status, text=BODY_TEXT)) as seen:
            assert await run_system_one({}, QUESTIONS, timeout=3) is None
        assert len(seen) == 2

    async def test_retry_then_success(self):
        n = {"i": 0}

        def handler(r):
            n["i"] += 1
            return httpx.Response(503) if n["i"] == 1 else httpx.Response(200, json=INNER)

        with cf_env(handler) as seen:
            r = await run_system_one({}, QUESTIONS, timeout=3)
        assert r is not None and len(seen) == 2

    async def test_timeout_returns_none(self):
        async def slow(request):
            await asyncio.sleep(5)
            return httpx.Response(200, json=INNER)

        with cf_env(slow):
            assert await run_system_one({}, QUESTIONS, timeout=0.1) is None

    async def test_transport_error_returns_none(self):
        def boom(request):
            raise httpx.ConnectError("nope")

        with cf_env(boom):
            assert await run_system_one({}, QUESTIONS) is None

    async def test_malformed_json(self):
        with cf_env(lambda r: httpx.Response(200, text="not json")):
            assert await run_system_one({}, QUESTIONS) is None

    async def test_65_questions_guard(self):
        qs = {f"q{i}": {"type": "noul"} for i in range(65)}
        with cf_env(ok()) as seen:
            assert await run_system_one({}, qs) is None
        assert not seen
        qs64 = {f"q{i}": {"type": "noul"} for i in range(64)}
        with cf_env(ok()) as seen:
            assert await run_system_one({}, qs64) is not None

    async def test_logs_leak_nothing(self, caplog):
        handlers = [
            lambda r: httpx.Response(401, text=BODY_TEXT),
            lambda r: httpx.Response(503, text=BODY_TEXT),
            lambda r: httpx.Response(200, text=BODY_TEXT),
            lambda r: httpx.Response(200, json={"success": False, "errors": [BODY_TEXT]}),
        ]
        with caplog.at_level(logging.DEBUG):
            for h in handlers:
                with cf_env(h):
                    await run_system_one({"t": STATE_TEXT}, QUESTIONS, timeout=2)
                await aclose_jev_client()
        assert caplog.records
        for bad in (SECRET, STATE_TEXT, BODY_TEXT):
            assert bad not in caplog.text
        assert "status=401" in caplog.text


class TestStateTruncation:
    async def test_long_state_capped(self):
        with cf_env(ok()) as seen:
            await run_system_one({"a": "x" * 200_000, "b": "y" * 200_000}, QUESTIONS)
        sent = json.loads(seen[0].content)["state"]
        assert len(sent["a"]) + len(sent["b"]) <= mod.STATE_MAX_CHARS


class TestSharedClient:
    async def test_reuse_recreate_close(self):
        with cf_env(ok()):
            await run_system_one({}, QUESTIONS)
            first = mod._cf_client
            await run_system_one({}, QUESTIONS)
            assert mod._cf_client is first
        with patch.object(mod, "get_learnhouse_config") as m, \
                patch.object(mod, "_cf_transport", httpx.MockTransport(lambda r: httpx.Response(200, json=INNER))):
            m.return_value.jev_config = ccfg(api_key="other-key")
            await run_system_one({}, QUESTIONS)
            second = mod._cf_client
        assert second is not first and first.is_closed
        await aclose_jev_client()
        assert second.is_closed and mod._cf_client is None

    async def test_concurrent_init_one_client(self):
        with cf_env(ok()):
            await asyncio.gather(*[run_system_one({}, QUESTIONS) for _ in range(8)])
            created = mod._cf_client
            await run_system_one({}, QUESTIONS)
            assert mod._cf_client is created


class TestGate:
    def test_cloudflare_without_account_disabled(self):
        with patch.object(mod, "get_learnhouse_config") as m:
            m.return_value.jev_config = ccfg(cloudflare_account_id="")
            assert mod.jev_enabled(1) is False


class TestParity:
    def test_sdk_objects_and_raw_dict_identical(self):
        sdk = JevResult(response({
            "n": noul(0.3),
            "c": choice("a", 0.8, ["a", "b"]),
            "s": score(1.5, 4),
        }))
        raw = JevResult(INNER)
        bare = JevResult(ANSWERS)
        for r in (raw, bare):
            assert r.noul("n") == sdk.noul("n")
            assert r.choice("c") == sdk.choice("c")
            assert r.score_norm("s") == pytest.approx(sdk.score_norm("s"))
            assert r.score_with_confidence("s") == pytest.approx(sdk.score_with_confidence("s"))

    def test_noul_has_no_confidence_and_wrong_types_none(self):
        r = JevResult(INNER)
        assert r.choice("n") is None
        assert r.score_norm("n") is None
        assert r.noul("c") is None
        assert r.noul("zzz") is None
        assert JevResult(None).noul("n") is None
