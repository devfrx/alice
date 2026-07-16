"""Tests for backend.core.config."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr

from backend.core.config import (
    DEFAULT_MODEL,
    KNOWN_MODELS,
    PROJECT_ROOT,
    AliceConfig,
    LLMConfig,
    load_config,
)


def test_load_config_returns_alice_config(config: AliceConfig) -> None:
    assert isinstance(config, AliceConfig)


def test_all_sections_exist(config: AliceConfig) -> None:
    assert config.server is not None
    assert config.llm is not None
    assert config.stt is not None
    assert config.tts is not None
    assert config.database is not None
    assert config.plugins is not None
    assert config.home_assistant is not None
    assert config.mqtt is not None
    assert config.voice is not None
    assert config.ui is not None


def test_server_port(config: AliceConfig) -> None:
    assert config.server.port == 8000


def test_server_host(config: AliceConfig) -> None:
    assert config.server.host == "127.0.0.1"


def test_llm_provider(config: AliceConfig) -> None:
    assert config.llm.provider == "lmstudio"


def test_llm_base_url(config: AliceConfig) -> None:
    assert isinstance(config.llm.base_url, str)
    assert config.llm.base_url.startswith("http")
    assert len(config.llm.base_url) > 0


def test_llm_model(config: AliceConfig) -> None:
    assert isinstance(config.llm.model, str)
    assert len(config.llm.model) > 0


def test_llm_temperature(config: AliceConfig) -> None:
    assert config.llm.temperature == 0.7


def test_llm_max_tokens(config: AliceConfig) -> None:
    assert isinstance(config.llm.max_tokens, int)
    # -1 means "auto-calculate from context window"; any positive value is explicit.
    assert config.llm.max_tokens == -1 or config.llm.max_tokens > 0


def test_system_prompt_file_is_absolute(config: AliceConfig) -> None:
    """system_prompt_file should be resolved to an absolute path."""
    prompt_path = Path(config.llm.system_prompt_file)
    assert prompt_path.is_absolute()
    assert str(PROJECT_ROOT) in config.llm.system_prompt_file


def test_database_url(config: AliceConfig) -> None:
    assert "sqlite+aiosqlite" in config.database.url


def test_plugins_enabled_list(config: AliceConfig) -> None:
    enabled = config.plugins.enabled
    assert isinstance(enabled, list)
    assert "system_info" in enabled
    assert "pc_automation" in enabled
    assert "memory" in enabled
    assert "mcp_client" in enabled
    assert "agent" in enabled
    assert "terminal" in enabled
    assert len(enabled) == 20


def test_stt_defaults(config: AliceConfig) -> None:
    assert config.stt.engine == "faster-whisper"
    assert config.stt.model == "large-v3"
    assert config.stt.language is None  # auto-detect by default


def test_tts_defaults(config: AliceConfig) -> None:
    assert config.tts.engine == "piper"
    assert config.tts.sample_rate == 22050


def test_voice_defaults(config: AliceConfig) -> None:
    assert config.voice.wake_word == "alice"
    assert config.voice.activation_mode == "push_to_talk"


def test_ui_defaults(config: AliceConfig) -> None:
    assert config.ui.theme == "dark"
    assert config.ui.language == "it"


def test_load_config_missing_file_uses_defaults() -> None:
    """When the config file does not exist, defaults + env vars are used."""
    cfg = load_config(Path("/nonexistent/path.yaml"))
    assert isinstance(cfg, AliceConfig)
    # Defaults should still be valid
    assert cfg.server.port == 8000


def test_known_model_auto_capabilities() -> None:
    """Capabilities are auto-detected from KNOWN_MODELS when not explicitly set."""
    # qwen3.5:9b has vision=True, thinking=True
    llm = LLMConfig(model="qwen3.5:9b")
    assert llm.supports_vision is True
    assert llm.supports_thinking is True

    # qwq has vision=False, thinking=True
    llm = LLMConfig(model="qwq")
    assert llm.supports_vision is False
    assert llm.supports_thinking is True


def test_explicit_capabilities_override_known_models() -> None:
    """Explicitly set capabilities are not overridden by KNOWN_MODELS."""
    # qwq normally has thinking=True, but user explicitly sets False
    llm = LLMConfig(model="qwq", supports_thinking=False)
    assert llm.supports_thinking is False

    # Unknown model with explicit capabilities
    llm = LLMConfig(model="some-unknown-model", supports_vision=True)
    assert llm.supports_vision is True


def test_default_model_matches_constant() -> None:
    """The DEFAULT_MODEL constant is used as the LLMConfig default."""
    llm = LLMConfig()
    assert llm.model == DEFAULT_MODEL
    assert DEFAULT_MODEL in KNOWN_MODELS


def test_lmstudio_style_key_thinking_capabilities() -> None:
    """LM Studio-style keys (e.g. 'qwen/qwq-32b') auto-detect thinking."""
    llm = LLMConfig(model="qwen/qwq-32b")
    assert llm.supports_thinking is True
    assert llm.supports_vision is False


def test_lmstudio_style_key_vision_capabilities() -> None:
    """LM Studio-style keys (e.g. 'qwen/qwen3.5-9b') auto-detect vision."""
    llm = LLMConfig(model="qwen/qwen3.5-9b")
    assert llm.supports_vision is True
    assert llm.supports_thinking is True


def test_lmstudio_style_key_deepseek_reasoning() -> None:
    """LM Studio DeepSeek R1 key auto-detects thinking capability."""
    llm = LLMConfig(model="deepseek/deepseek-r1-0528-qwen3-8b")
    assert llm.supports_thinking is True
    assert llm.supports_vision is False


def test_removed_legacy_keys_are_stripped() -> None:
    """Fase 5: dead flags are stripped per-layer before model validation."""
    from backend.core.config import migrate_legacy_config_keys

    data = {
        "voice": {"wake_word": "alice", "voice_confirmation_enabled": True},
        "pc_automation": {"enabled": False, "command_timeout_s": 30},
        "notifications": {"sound_enabled": True, "app_id": "AL\\CE"},
    }
    migrate_legacy_config_keys(data)
    assert "voice_confirmation_enabled" not in data["voice"]
    assert "enabled" not in data["pc_automation"]
    assert "sound_enabled" not in data["notifications"]
    assert data["pc_automation"]["command_timeout_s"] == 30


def test_stale_flag_survives_full_aliceconfig_construction() -> None:
    """Fase 5: extra=forbid does not break when a dead flag reaches AliceConfig."""
    from backend.core.config import AliceConfig

    cfg = AliceConfig(voice={"wake_word": "alice", "voice_confirmation_enabled": True})
    assert not hasattr(cfg.voice, "voice_confirmation_enabled")
    assert cfg.voice.wake_word == "alice"


class TestCommandsConfig:
    """Command Bridge config section (Fase 7, spec §7)."""

    def test_defaults(self) -> None:
        from backend.core.config import AliceConfig

        cfg = AliceConfig()
        assert cfg.commands.enabled is True
        assert cfg.commands.rpc_timeout_s == 10.0
        assert cfg.commands.disabled_commands == []

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from backend.core.config import CommandsConfig

        monkeypatch.setenv("ALICE_COMMANDS__ENABLED", "false")
        monkeypatch.setenv("ALICE_COMMANDS__RPC_TIMEOUT_S", "3.5")
        cfg = CommandsConfig()
        assert cfg.enabled is False
        assert cfg.rpc_timeout_s == 3.5


# ---------------------------------------------------------------------------
# OpenRouter provider config
# ---------------------------------------------------------------------------


def test_effective_base_url_openrouter() -> None:
    cfg = LLMConfig(provider="openrouter", base_url="http://localhost:1234")
    assert cfg.effective_base_url == "https://openrouter.ai/api"


def test_effective_base_url_local_providers() -> None:
    cfg = LLMConfig(provider="lmstudio", base_url="http://localhost:1234")
    assert cfg.effective_base_url == "http://localhost:1234"
    cfg = LLMConfig(provider="ollama", base_url="http://localhost:11434")
    assert cfg.effective_base_url == "http://localhost:11434"


def test_openrouter_defaults() -> None:
    cfg = LLMConfig()
    assert cfg.openrouter_api_key.get_secret_value() == ""
    assert cfg.openrouter_model == ""
    assert cfg.openrouter_favorites == []


# ---------------------------------------------------------------------------
# Secret fields (SecretStr)
# ---------------------------------------------------------------------------


def test_secret_fields_are_secretstr_and_redacted_in_dump() -> None:
    cfg = AliceConfig(
        llm={"api_token": "tok", "openrouter_api_key": "sk-or-x"},
        home_assistant={"token": "ha"},
        mqtt={"password": "mq"},
        continuum={"api_token": "ct"},
        email={"password": "pw"},
    )
    assert isinstance(cfg.llm.api_token, SecretStr)
    assert cfg.llm.openrouter_api_key.get_secret_value() == "sk-or-x"
    assert cfg.continuum.api_token is not None
    assert cfg.continuum.api_token.get_secret_value() == "ct"
    dumped = cfg.model_dump(mode="json")
    assert "sk-or-x" not in str(dumped)
    assert "pw" not in str(dumped)
