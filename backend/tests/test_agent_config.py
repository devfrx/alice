"""Tests for the Agent Loop v2 configuration sub-tree.

These tests verify that:
* defaults match the documented contract (``enabled: false``);
* ``ALICE_AGENT__*`` env-var overrides traverse the nested config correctly;
* numeric fields parse as ``int``/``float``.
"""

from __future__ import annotations

import pytest

from backend.core.config import (
    AgentClassifierConfig,
    AgentConfig,
    AgentCriticConfig,
    AgentPersistenceConfig,
    AgentPlannerConfig,
    AliceConfig,
    load_config,
)


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


def test_agent_config_disabled_by_default() -> None:
    cfg = AgentConfig()
    assert cfg.enabled is False
    assert cfg.voice_mode_bypass is True


def test_agent_config_top_level_defaults() -> None:
    cfg = AgentConfig()
    assert cfg.max_steps == 8
    assert cfg.max_retries_per_step == 2
    assert cfg.max_replans == 2
    assert cfg.step_timeout_seconds == 60
    assert cfg.total_timeout_seconds == 240
    assert cfg.pause_timeout_during_confirmation is True


def test_agent_subconfig_defaults() -> None:
    cfg = AgentConfig()
    assert isinstance(cfg.classifier, AgentClassifierConfig)
    assert cfg.classifier.enabled is True
    assert cfg.classifier.cache_ttl_seconds == 300
    assert cfg.classifier.max_output_tokens == 20
    assert cfg.classifier.temperature == 0.0

    assert isinstance(cfg.planner, AgentPlannerConfig)
    assert cfg.planner.max_output_tokens == 600
    assert cfg.planner.temperature == 0.2
    assert cfg.planner.require_json_object is True

    assert isinstance(cfg.critic, AgentCriticConfig)
    assert cfg.critic.max_output_tokens == 80
    assert cfg.critic.temperature == 0.0
    assert cfg.critic.fail_open is True

    assert isinstance(cfg.persistence, AgentPersistenceConfig)
    assert cfg.persistence.save_runs is True


def test_alice_config_exposes_agent_section() -> None:
    cfg = load_config()
    assert isinstance(cfg.agent, AgentConfig)
    # Agent loop is enabled by default in default.yaml (S6+S7 rollout).
    assert cfg.agent.enabled is True
    # Critic always-run + degeneration detector are also on by default.
    assert cfg.agent.critic.always_run is True
    assert cfg.agent.critic.degeneration_detector_enabled is True


# ---------------------------------------------------------------------------
# Env-var overrides
# ---------------------------------------------------------------------------


def test_env_override_enables_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALICE_AGENT__ENABLED", "true")
    cfg = AliceConfig()
    assert cfg.agent.enabled is True


def test_env_override_numeric_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALICE_AGENT__MAX_STEPS", "12")
    monkeypatch.setenv("ALICE_AGENT__STEP_TIMEOUT_SECONDS", "90")
    cfg = AliceConfig()
    assert cfg.agent.max_steps == 12
    assert isinstance(cfg.agent.max_steps, int)
    assert cfg.agent.step_timeout_seconds == 90


def test_env_override_nested_subconfig(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALICE_AGENT__CLASSIFIER__ENABLED", "false")
    monkeypatch.setenv("ALICE_AGENT__PLANNER__TEMPERATURE", "0.5")
    monkeypatch.setenv("ALICE_AGENT__CRITIC__FAIL_OPEN", "false")
    cfg = AliceConfig()
    assert cfg.agent.classifier.enabled is False
    assert cfg.agent.planner.temperature == pytest.approx(0.5)
    assert cfg.agent.critic.fail_open is False
