"""Tests for backend.core.config."""

from __future__ import annotations

from pathlib import Path

from backend.core.config import (
    DEFAULT_MODEL,
    KNOWN_MODELS,
    PROJECT_ROOT,
    OmniaConfig,
    LLMConfig,
    load_config,
)


def test_load_config_returns_omnia_config(config: OmniaConfig) -> None:
    assert isinstance(config, OmniaConfig)


def test_all_sections_exist(config: OmniaConfig) -> None:
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


def test_server_port(config: OmniaConfig) -> None:
    assert config.server.port == 8000


def test_server_host(config: OmniaConfig) -> None:
    assert config.server.host == "127.0.0.1"


def test_llm_provider(config: OmniaConfig) -> None:
    assert config.llm.provider == "lmstudio"


def test_llm_base_url(config: OmniaConfig) -> None:
    assert isinstance(config.llm.base_url, str)
    assert config.llm.base_url.startswith("http")
    assert len(config.llm.base_url) > 0


def test_llm_model(config: OmniaConfig) -> None:
    assert isinstance(config.llm.model, str)
    assert len(config.llm.model) > 0


def test_llm_temperature(config: OmniaConfig) -> None:
    assert config.llm.temperature == 0.7


def test_llm_max_tokens(config: OmniaConfig) -> None:
    assert isinstance(config.llm.max_tokens, int)
    assert config.llm.max_tokens > 0


def test_system_prompt_file_is_absolute(config: OmniaConfig) -> None:
    """system_prompt_file should be resolved to an absolute path."""
    prompt_path = Path(config.llm.system_prompt_file)
    assert prompt_path.is_absolute()
    assert str(PROJECT_ROOT) in config.llm.system_prompt_file


def test_database_url(config: OmniaConfig) -> None:
    assert "sqlite+aiosqlite" in config.database.url


def test_plugins_enabled_list(config: OmniaConfig) -> None:
    enabled = config.plugins.enabled
    assert isinstance(enabled, list)
    assert "system_info" in enabled
    assert "pc_automation" in enabled
    assert "memory" in enabled
    assert len(enabled) == 11


def test_stt_defaults(config: OmniaConfig) -> None:
    assert config.stt.engine == "faster-whisper"
    assert config.stt.model == "large-v3"
    assert config.stt.language is None  # auto-detect by default


def test_tts_defaults(config: OmniaConfig) -> None:
    assert config.tts.engine == "piper"
    assert config.tts.sample_rate == 22050


def test_voice_defaults(config: OmniaConfig) -> None:
    assert config.voice.wake_word == "omnia"
    assert config.voice.activation_mode == "push_to_talk"


def test_ui_defaults(config: OmniaConfig) -> None:
    assert config.ui.theme == "dark"
    assert config.ui.language == "it"


def test_load_config_missing_file_uses_defaults() -> None:
    """When the config file does not exist, defaults + env vars are used."""
    cfg = load_config(Path("/nonexistent/path.yaml"))
    assert isinstance(cfg, OmniaConfig)
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
