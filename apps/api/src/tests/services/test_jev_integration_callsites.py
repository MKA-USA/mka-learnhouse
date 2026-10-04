"""Call-site glue: opt-in gating, mode precedence, fire-and-forget tracking."""

import asyncio
from types import SimpleNamespace

import pytest

import src.services.ai.jev.client as client_mod
import src.services.ai.jev_integration as integ
from config.config import JevConfig


def _use_cfg(monkeypatch, **overrides):
    base = dict(enabled=True, api_key="k", allowed_org_ids=[1], intent_routing_enabled=True)
    base.update(overrides)
    cfg = JevConfig(**base)
    fake = lambda: SimpleNamespace(jev_config=cfg)
    monkeypatch.setattr(client_mod, "get_learnhouse_config", fake)
    monkeypatch.setattr(integ, "get_learnhouse_config", fake)


@pytest.mark.asyncio
async def test_audit_scheduled_and_tracked(monkeypatch):
    _use_cfg(monkeypatch)
    ran = asyncio.Event()

    async def fake_audit(*a, **k):
        ran.set()

    import src.services.ai.jev.guardrails as g
    monkeypatch.setattr(g, "audit_response", fake_audit)
    integ.schedule_guardrail_audit("r", user_question="q", org_id=1)
    assert len(integ._background_tasks) == 1  # strong ref held
    await asyncio.wait_for(ran.wait(), 1)
    await asyncio.sleep(0)
    assert not integ._background_tasks  # discarded on completion


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides,org",
    [
        ({"guardrails_enabled": False}, 1),
        ({"allowed_org_ids": []}, 1),
        ({}, 2),
        ({}, None),
    ],
)
async def test_audit_not_scheduled_when_gated(monkeypatch, overrides, org):
    _use_cfg(monkeypatch, **overrides)
    integ.schedule_guardrail_audit("r", user_question="q", org_id=org)
    assert not integ._background_tasks


@pytest.mark.asyncio
async def test_audit_not_scheduled_when_config_none(monkeypatch):
    fake = lambda: SimpleNamespace(jev_config=None)
    monkeypatch.setattr(client_mod, "get_learnhouse_config", fake)
    monkeypatch.setattr(integ, "get_learnhouse_config", fake)
    integ.schedule_guardrail_audit("r", user_question="q", org_id=1)
    assert not integ._background_tasks


@pytest.mark.asyncio
async def test_routing_respects_explicit_mode(monkeypatch):
    _use_cfg(monkeypatch)
    called = False

    async def fake_classify(*a, **k):
        nonlocal called
        called = True

    import src.services.ai.jev.router as r
    monkeypatch.setattr(r, "classify_question", fake_classify)
    assert await integ.should_route_to_general("q", org_id=1, mode="general") is False
    assert called is False


@pytest.mark.asyncio
async def test_routing_uses_is_confident_general_knowledge(monkeypatch):
    _use_cfg(monkeypatch)
    import src.services.ai.jev.router as r

    async def fake_classify(*a, **k):
        return r.QuestionIntent(intent="general_knowledge", intent_confidence=0.9, needs_rag=0.1)

    monkeypatch.setattr(r, "classify_question", fake_classify)
    assert await integ.should_route_to_general("q", org_id=1, mode=None) is True

    async def low_conf(*a, **k):
        return r.QuestionIntent(intent="general_knowledge", intent_confidence=0.5, needs_rag=0.1)

    monkeypatch.setattr(r, "classify_question", low_conf)
    assert await integ.should_route_to_general("q", org_id=1, mode="course_only") is False


@pytest.mark.asyncio
async def test_explicit_course_only_never_routed(monkeypatch):
    """An explicit client choice (even the server default value) is never overridden."""
    _use_cfg(monkeypatch)
    import src.services.ai.jev.router as r

    called = False

    async def confident_general(*a, **k):
        nonlocal called
        called = True
        return r.QuestionIntent(intent="general_knowledge", intent_confidence=0.99, needs_rag=0.0)

    monkeypatch.setattr(r, "classify_question", confident_general)
    assert await integ.should_route_to_general("q", org_id=1, mode="course_only") is False
    assert called is False
    assert await integ.should_route_to_general("q", org_id=1, mode=None) is True


def test_intent_routing_default_off_in_config():
    assert JevConfig(enabled=True, api_key="k").intent_routing_enabled is False


def test_rag_request_mode_defaults_to_none():
    from src.routers.ai.rag import RAGChatRequest

    assert RAGChatRequest(message="hi").mode is None
    assert RAGChatRequest(message="hi", mode="course_only").mode == "course_only"


@pytest.mark.asyncio
async def test_routing_disabled_flag_and_failure(monkeypatch):
    _use_cfg(monkeypatch, intent_routing_enabled=False)
    assert await integ.should_route_to_general("q", org_id=1, mode=None) is False

    _use_cfg(monkeypatch)
    import src.services.ai.jev.router as r

    async def boom(*a, **k):
        raise RuntimeError("x")

    monkeypatch.setattr(r, "classify_question", boom)
    assert await integ.should_route_to_general("q", org_id=1, mode=None) is False


@pytest.mark.asyncio
async def test_quiz_validation_gated_and_never_raises(monkeypatch):
    import src.services.ai.jev.quality as q
    calls = []

    async def fake_validate(questions, **k):
        calls.append(len(questions))
        return [{"passed": False}, None]

    monkeypatch.setattr(q, "validate_quiz_questions", fake_validate)

    _use_cfg(monkeypatch)  # quiz_validation_enabled defaults False
    await integ.validate_generated_quiz([{}, {}], org_id=1)
    assert calls == []

    _use_cfg(monkeypatch, quiz_validation_enabled=True)
    await integ.validate_generated_quiz([{}, {}], org_id=1)
    assert calls == [2]  # ONE batched call

    async def boom(*a, **k):
        raise RuntimeError("x")

    monkeypatch.setattr(q, "validate_quiz_questions", boom)
    await integ.validate_generated_quiz([{}], org_id=1)  # must not raise
