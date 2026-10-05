"""Shared helpers for the Jev tests (no tests here).

Builds REAL typesafe-sdk response objects when the SDK is installed so the
mocks cannot drift from the SDK's accessors.  Skips when it is missing.
"""

from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

import pytest

from config.config import JevConfig

pytest.importorskip("typesafe_sdk")

from typesafe_sdk import (
    ChoiceAnswer,
    NoulAnswer,
    ScoreAnswer,
    SystemOneResponse,
    Usage,
)


def noul(p):
    return NoulAnswer(noul=p)


def choice(label, conf, labels=None):
    labels = labels or [label]
    probs = {label: conf}
    for other in labels:
        if other != label:
            probs[other] = (1 - conf) / max(1, len(labels) - 1)
    return ChoiceAnswer(choice=label, confidence=conf, probabilities=probs)


def score(raw, levels, conf=0.9):
    return ScoreAnswer(
        score=raw,
        confidence=conf,
        legend={i: f"level {i}" for i in range(levels)},
        probabilities={i: 1.0 / levels for i in range(levels)},
    )


def response(answers: dict) -> SystemOneResponse:
    return SystemOneResponse(model="jev-test", usage=Usage(), answers=answers)


def cfg(**overrides) -> JevConfig:
    base = {"enabled": True, "api_key": "test-key", "allowed_org_ids": [1]}
    base.update(overrides)
    return JevConfig(**base)


class FakeClient:
    """Stand-in for AsyncTypeSafeClient with an AsyncMock system_one."""

    def __init__(self, result=None, side_effect=None):
        self.system_one = AsyncMock(return_value=result, side_effect=side_effect)
        self.aclose = AsyncMock()


@contextmanager
def jev_env(config=None, client=None):
    """Patch config and the shared client so no network/SDK client is built."""
    from src.services.ai.jev import client as mod

    config = config if config is not None else cfg()
    with patch.object(mod, "get_learnhouse_config") as mock_cfg:
        mock_cfg.return_value.jev_config = config
        if client is not None:
            async def _fake_get_client(_cfg):
                return client
            with patch.object(mod, "_get_client", _fake_get_client):
                yield client
        else:
            yield None
