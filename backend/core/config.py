"""O.M.N.I.A. — Configuration system.

Loads configuration from ``config/default.yaml`` with environment-variable
overrides (prefix ``OMNIA_``, nested via double-underscore).  Uses Pydantic
Settings v2 for validation and env parsing.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

import yaml
from loguru import logger
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
"""Absolute path to the OMNIA project root (two levels up from core/)."""

DEFAULT_CONFIG_PATH: Path = PROJECT_ROOT / "config" / "default.yaml"


def _load_yaml(path: Path) -> dict[str, Any]:
    """Read a YAML file and return its contents as a dict."""
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data if isinstance(data, dict) else {}


# ---------------------------------------------------------------------------
# Model catalog
# ---------------------------------------------------------------------------

DEFAULT_MODEL: str = "qwen3.5:9b"
"""Default LLM model tag used when no model is specified."""

KNOWN_MODELS: dict[str, dict[str, bool]] = {
    "qwen3.5:9b": {"vision": True, "thinking": False},
    "qwen2.5:14b": {"vision": False, "thinking": False},
    "qwq": {"vision": False, "thinking": True},
    "deepseek-r1:14b": {"vision": False, "thinking": True},
    "llava": {"vision": True, "thinking": False},
}
"""Known models mapped to their capabilities (vision, thinking)."""


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------


class ServerConfig(BaseSettings):
    """HTTP server configuration."""

    model_config = SettingsConfigDict(env_prefix="OMNIA_SERVER__")

    host: str = "0.0.0.0"
    port: int = 8000
    reload: bool = True
    environment: str = "development"
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://localhost:3000",
        ]
    )

    @field_validator("cors_origins", mode="after")
    @classmethod
    def _sanitize_cors_origins(cls, v: list[str]) -> list[str]:
        """Strip dangerous origin values ('null' and '*') in production."""
        return [o for o in v if o not in ("null", "*")]
    max_upload_size_mb: int = 50
    """Maximum upload file size in megabytes."""
    ws_max_connections_per_ip: int = 5
    """Maximum concurrent WebSocket connections per IP address."""
    rate_limit: str = "60/minute"
    """Default rate limit for REST endpoints."""


class LLMConfig(BaseSettings):
    """LLM provider configuration."""

    model_config = SettingsConfigDict(env_prefix="OMNIA_LLM__")

    provider: str = "openai-compatible"
    base_url: str = "http://localhost:11434"
    model: str = DEFAULT_MODEL
    temperature: float = 0.7
    max_tokens: int = 4096
    timeout: float = 120.0
    """HTTP read timeout in seconds for streaming LLM responses."""
    connect_timeout: float = 10.0
    """HTTP connect timeout in seconds."""
    system_prompt_file: str = "config/system_prompt.md"
    supports_thinking: bool = False
    """Enable for reasoning models (QwQ, DeepSeek-R1) that emit <think> tags."""
    supports_vision: bool = False
    """Enable for multimodal models (LLaVA, Qwen2-VL) that accept images."""
    max_tool_iterations: int = 10
    """Maximum number of tool calling rounds before forcing a final answer."""
    confirmation_timeout_s: int = 60
    """Seconds to wait for user confirmation on dangerous tools."""

    # -- Ollama-specific options (ignored by other providers) --
    num_ctx: int = 8192
    """Context window size. Ollama defaults to 2048; 8192 is better for 9B+ models."""
    num_gpu: int = -1
    """-1 = offload all layers to GPU. Set to 0 to force CPU."""
    keep_alive: str = "5m"
    """How long Ollama keeps the model loaded in memory after a request."""

    @model_validator(mode="before")
    @classmethod
    def _infer_capabilities(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Auto-detect capabilities from KNOWN_MODELS if not explicitly set."""
        if not isinstance(data, dict):
            return data
        model = data.get("model", DEFAULT_MODEL)
        if model in KNOWN_MODELS:
            caps = KNOWN_MODELS[model]
            if "supports_vision" not in data:
                data["supports_vision"] = caps["vision"]
            if "supports_thinking" not in data:
                data["supports_thinking"] = caps["thinking"]
        return data


class STTConfig(BaseSettings):
    """Speech-to-text configuration."""

    model_config = SettingsConfigDict(env_prefix="OMNIA_STT__")

    engine: str = "faster-whisper"
    model: str = "large-v3"
    language: str = "it"
    device: str = "cuda"
    compute_type: str = "float16"
    vad_filter: bool = True
    vad_threshold: float = 0.5


class TTSConfig(BaseSettings):
    """Text-to-speech configuration."""

    model_config = SettingsConfigDict(env_prefix="OMNIA_TTS__")

    engine: str = "piper"
    voice: str = "it_IT-riccardo-x_low"
    sample_rate: int = 22050


class DatabaseConfig(BaseSettings):
    """Database configuration."""

    model_config = SettingsConfigDict(env_prefix="OMNIA_DATABASE__")

    url: str = "sqlite+aiosqlite:///data/omnia.db"


class PluginsConfig(BaseSettings):
    """Plugin configuration."""

    model_config = SettingsConfigDict(env_prefix="OMNIA_PLUGINS__")

    enabled: list[str] = Field(
        default_factory=lambda: [
            "system_info",
            "pc_automation",
            "web_search",
            "calendar",
        ]
    )


class HomeAssistantConfig(BaseSettings):
    """Home Assistant integration configuration."""

    model_config = SettingsConfigDict(env_prefix="OMNIA_HOME_ASSISTANT__")

    url: str = "http://homeassistant.local:8123"
    token: str = ""


class MQTTConfig(BaseSettings):
    """MQTT broker configuration."""

    model_config = SettingsConfigDict(env_prefix="OMNIA_MQTT__")

    broker: str = "localhost"
    port: int = 1883
    username: str = ""
    password: str = ""


class VoiceConfig(BaseSettings):
    """Voice interaction configuration."""

    model_config = SettingsConfigDict(env_prefix="OMNIA_VOICE__")

    wake_word: str = "omnia"
    activation_mode: str = "push_to_talk"
    silence_timeout_ms: int = 1500


class UIConfig(BaseSettings):
    """UI configuration."""

    model_config = SettingsConfigDict(env_prefix="OMNIA_UI__")

    theme: str = "dark"
    global_hotkey: str = "Ctrl+Shift+O"
    language: str = "it"


# ---------------------------------------------------------------------------
# Top-level config
# ---------------------------------------------------------------------------


class OmniaConfig(BaseSettings):
    """Root configuration aggregating every sub-section."""

    model_config = SettingsConfigDict(
        env_prefix="OMNIA_",
        env_nested_delimiter="__",
    )

    server: ServerConfig = Field(default_factory=ServerConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    stt: STTConfig = Field(default_factory=STTConfig)
    tts: TTSConfig = Field(default_factory=TTSConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    plugins: PluginsConfig = Field(default_factory=PluginsConfig)
    home_assistant: HomeAssistantConfig = Field(
        default_factory=HomeAssistantConfig
    )
    mqtt: MQTTConfig = Field(default_factory=MQTTConfig)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)
    ui: UIConfig = Field(default_factory=UIConfig)

    @model_validator(mode="before")
    @classmethod
    def _resolve_paths(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Resolve relative paths to absolute using the project root."""
        if not isinstance(data, dict):
            return data

        # -- system prompt file --
        llm_data = data.get("llm", {})
        if isinstance(llm_data, dict):
            raw = llm_data.get(
                "system_prompt_file", "config/system_prompt.md"
            )
            if raw and not Path(raw).is_absolute():
                llm_data["system_prompt_file"] = str(
                    PROJECT_ROOT / raw
                )

        # -- database URL (make relative sqlite path absolute) --
        db_data = data.get("database", {})
        if isinstance(db_data, dict):
            db_url = db_data.get(
                "url", "sqlite+aiosqlite:///data/omnia.db"
            )
            if db_url.startswith("sqlite") and ":///" in db_url:
                prefix, db_path = db_url.split(":///", 1)
                if db_path and not Path(db_path).is_absolute():
                    abs_path = PROJECT_ROOT / db_path
                    db_data["url"] = f"{prefix}:///{abs_path}"

        return data


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_config(path: Path | None = None) -> OmniaConfig:
    """Load configuration from a YAML file and apply env-var overrides.

    Args:
        path: Path to the YAML config file.  Defaults to
              ``config/default.yaml`` relative to the project root.

    Returns:
        A fully validated ``OmniaConfig`` instance.
    """
    config_path = path or DEFAULT_CONFIG_PATH

    if config_path.exists():
        raw = _load_yaml(config_path)
        logger.debug("Loaded config from {}", config_path)
    else:
        raw = {}
        logger.warning(
            "Config file {} not found — using defaults + env vars",
            config_path,
        )

    return OmniaConfig(**raw)


@functools.lru_cache(maxsize=1)
def get_config() -> OmniaConfig:
    """Return a cached singleton of the default configuration.

    The config is loaded once (from the default YAML path) and then reused
    for subsequent calls.
    """
    return load_config()
