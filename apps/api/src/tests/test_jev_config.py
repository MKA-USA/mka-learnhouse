"""Jev config parsing: defaults, env/YAML precedence, bad input tolerance."""

import pytest

import config.config as cfg_mod
from config.config import _parse_jev_float, _parse_jev_org_ids

JEV_ENV = [
    "LEARNHOUSE_JEV_ENABLED",
    "LEARNHOUSE_JEV_API_KEY",
    "LEARNHOUSE_JEV_TIMEOUT",
    "LEARNHOUSE_JEV_ALLOWED_ORG_IDS",
    "LEARNHOUSE_JEV_QUIZ_VALIDATION",
    "LEARNHOUSE_JEV_GUARDRAILS",
    "LEARNHOUSE_JEV_INTENT_ROUTING",
]


@pytest.fixture
def load(monkeypatch):
    """Return a loader that applies a jev_config YAML block + env overrides."""
    for name in JEV_ENV:
        monkeypatch.delenv(name, raising=False)
    # Don't let a developer's local .env leak into the test.
    monkeypatch.setattr(cfg_mod, "load_dotenv", lambda *a, **k: None)

    def _load(yaml_block=None, env=None):
        real = cfg_mod._load_yaml_config

        def fake(path):
            data = dict(real(path) or {})
            if yaml_block is not None:
                data["jev_config"] = yaml_block
            return data

        monkeypatch.setattr(cfg_mod, "_load_yaml_config", fake)
        for k, v in (env or {}).items():
            monkeypatch.setenv(k, v)
        return cfg_mod.get_learnhouse_config().jev_config

    return _load


def test_float_parser():
    assert _parse_jev_float(None, None, 3.0) == 3.0
    assert _parse_jev_float("", 2.5, 3.0) == 2.5
    assert _parse_jev_float("1.5", 9, 3.0) == 1.5
    assert _parse_jev_float("abc", None, 3.0) == 3.0
    assert _parse_jev_float("-1", None, 3.0) == 3.0
    assert _parse_jev_float("0", None, 3.0) == 3.0


def test_org_ids_parser():
    assert _parse_jev_org_ids(None, None) == []
    assert _parse_jev_org_ids("1, 2,3", None) == [1, 2, 3]
    assert _parse_jev_org_ids("1,x,,4", None) == [1, 4]
    assert _parse_jev_org_ids(None, [5, "6", "bad"]) == [5, 6]
    assert _parse_jev_org_ids("7", [5]) == [7]  # env wins
    assert _parse_jev_org_ids("", [5]) == [5]


def test_disabled_by_default(load):
    assert load() is None


def test_enabled_without_key_is_none(load):
    assert load(env={"LEARNHOUSE_JEV_ENABLED": "true"}) is None


def test_key_without_enabled_is_none(load):
    assert load(env={"LEARNHOUSE_JEV_API_KEY": "k"}) is None


def test_defaults_when_enabled(load):
    c = load(env={"LEARNHOUSE_JEV_ENABLED": "true", "LEARNHOUSE_JEV_API_KEY": "k"})
    assert c is not None
    assert c.timeout == 3.0
    assert c.allowed_org_ids == []
    assert c.quiz_validation_enabled is False
    assert c.guardrails_enabled is True
    assert c.intent_routing_enabled is False


def test_env_overrides_yaml(load):
    c = load(
        yaml_block={
            "enabled": True,
            "api_key": "yaml-key",
            "timeout": 9,
            "allowed_org_ids": [1],
            "guardrails_enabled": True,
        },
        env={
            "LEARNHOUSE_JEV_API_KEY": "env-key",
            "LEARNHOUSE_JEV_TIMEOUT": "1.5",
            "LEARNHOUSE_JEV_ALLOWED_ORG_IDS": "2,3",
            "LEARNHOUSE_JEV_GUARDRAILS": "false",
            "LEARNHOUSE_JEV_QUIZ_VALIDATION": "true",
        },
    )
    assert c.api_key == "env-key"
    assert c.timeout == 1.5
    assert c.allowed_org_ids == [2, 3]
    assert c.guardrails_enabled is False
    assert c.quiz_validation_enabled is True


def test_yaml_only(load):
    c = load(yaml_block={"enabled": True, "api_key": "k", "allowed_org_ids": [4]})
    assert c.allowed_org_ids == [4]


def test_bad_values_do_not_crash(load):
    c = load(
        env={
            "LEARNHOUSE_JEV_ENABLED": "true",
            "LEARNHOUSE_JEV_API_KEY": "k",
            "LEARNHOUSE_JEV_TIMEOUT": "fast",
            "LEARNHOUSE_JEV_ALLOWED_ORG_IDS": "a,b",
        }
    )
    assert c.timeout == 3.0
    assert c.allowed_org_ids == []


# ---- provider-neutral settings -------------------------------------------

PROVIDER_ENV = [
    "LEARNHOUSE_JEV_PROVIDER", "LEARNHOUSE_JEV_MODEL", "LEARNHOUSE_JEV_CLOUDFLARE_ACCOUNT_ID",
    "LEARNHOUSE_JEV_MODEL_RERANK", "LEARNHOUSE_JEV_MODEL_GUARDRAILS", "LEARNHOUSE_JEV_MODEL_MODERATION",
    "LEARNHOUSE_JEV_MODEL_INTENT", "LEARNHOUSE_JEV_MODEL_QUIZ",
]


@pytest.fixture
def pload(load, monkeypatch):
    for name in PROVIDER_ENV:
        monkeypatch.delenv(name, raising=False)
    return load


def test_provider_defaults(pload):
    c = pload({"enabled": True, "api_key": "k"})
    assert (c.provider, c.model, c.cloudflare_account_id, c.models) == ("typesafe", None, "", {})


def test_invalid_provider_falls_back(pload, caplog):
    c = pload({"enabled": True, "api_key": "k", "provider": "bogus"})
    assert c is not None and c.provider == "typesafe"
    assert "Invalid Jev provider" in caplog.text


def test_cloudflare_missing_account_disables(pload, caplog):
    assert pload({"enabled": True, "api_key": "k", "provider": "cloudflare"}) is None
    assert "ACCOUNT_ID" in caplog.text


def test_cloudflare_missing_key_disables(pload):
    assert pload({"enabled": True, "provider": "cloudflare", "cloudflare_account_id": "a"}) is None


def test_cloudflare_from_yaml(pload):
    c = pload({
        "enabled": True, "api_key": "k", "provider": "Cloudflare", "model": "clef",
        "cloudflare_account_id": "acc", "models": {"rerank": "clef-flash", "bogus": "x"},
    })
    assert (c.provider, c.model, c.cloudflare_account_id) == ("cloudflare", "clef", "acc")
    assert c.models == {"rerank": "clef-flash"}


def test_provider_env_overrides_yaml(pload):
    c = pload(
        {"enabled": True, "api_key": "k", "provider": "typesafe", "models": {"quiz": "a"}},
        env={
            "LEARNHOUSE_JEV_PROVIDER": "cloudflare",
            "LEARNHOUSE_JEV_CLOUDFLARE_ACCOUNT_ID": "envacc",
            "LEARNHOUSE_JEV_MODEL": "clef-flash",
            "LEARNHOUSE_JEV_MODEL_QUIZ": "clef",
            "LEARNHOUSE_JEV_MODEL_INTENT": "clef-flash",
        },
    )
    assert c.provider == "cloudflare" and c.cloudflare_account_id == "envacc"
    assert c.model == "clef-flash"
    assert c.models == {"quiz": "clef", "intent": "clef-flash"}
