"""O.M.N.I.A. — Configuration system.

Loads configuration from ``config/default.yaml`` with environment-variable
overrides (prefix ``OMNIA_``, nested via double-underscore).  Uses Pydantic
Settings v2 for validation and env parsing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from loguru import logger
from pydantic import Field, model_validator
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
    # Ollama-style keys
    "qwen3.5:9b": {"vision": True, "thinking": True},
    "qwen2.5:14b": {"vision": False, "thinking": False},
    "qwq": {"vision": False, "thinking": True},
    "deepseek-r1:14b": {"vision": False, "thinking": True},
    "llava": {"vision": True, "thinking": False},
    # LM Studio-style keys
    "qwen/qwen3.5-9b": {"vision": True, "thinking": True},
    "qwen/qwq-32b": {"vision": False, "thinking": True},
    "deepseek/deepseek-r1-0528-qwen3-8b": {
        "vision": False, "thinking": True,
    },
    "mistralai/ministral-3-14b-reasoning": {
        "vision": False, "thinking": True,
    },
}
"""Known models mapped to their capabilities (vision, thinking)."""


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------


class ServerConfig(BaseSettings):
    """HTTP server configuration."""

    model_config = SettingsConfigDict(env_prefix="OMNIA_SERVER__")

    host: str = "127.0.0.1"
    port: int = 8000
    reload: bool = True
    environment: str = "development"
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://localhost:3000",
            "null",
        ]
    )

    @model_validator(mode="after")
    def _sanitize_cors_origins(self) -> ServerConfig:
        """Strip wildcard origins in production; allow 'null' in development.

        Electron's ``file://`` protocol sends ``Origin: null``, so we must
        allow it during development.  In production the Electron app should
        use a custom protocol with a proper origin.
        """
        if self.environment != "development":
            self.cors_origins = [
                o for o in self.cors_origins if o not in ("null", "*")
            ]
        else:
            # Still block wildcard "*" even in dev — too permissive.
            self.cors_origins = [
                o for o in self.cors_origins if o != "*"
            ]
        return self

    max_upload_size_mb: int = 50
    """Maximum upload file size in megabytes."""
    ws_max_connections_per_ip: int = 5
    """Maximum concurrent WebSocket connections per IP address."""
    rate_limit: str = "60/minute"
    """Default rate limit for REST endpoints."""


class LLMConfig(BaseSettings):
    """LLM provider configuration."""

    model_config = SettingsConfigDict(env_prefix="OMNIA_LLM__")

    provider: str = "lmstudio"
    base_url: str = "http://localhost:1234"
    model: str = DEFAULT_MODEL
    temperature: float = 0.7
    max_tokens: int = 8192
    api_token: str = ""
    """LM Studio API authentication token (optional)."""
    timeout: float = 120.0
    """HTTP read timeout in seconds for streaming LLM responses."""
    connect_timeout: float = 10.0
    """HTTP connect timeout in seconds."""
    system_prompt_file: str = "config/system_prompt.md"
    system_prompt_enabled: bool = True
    """Whether to include the system prompt in LLM requests."""
    tools_enabled: bool = True
    """Whether to send tool definitions to the LLM for function calling."""
    supports_thinking: bool = False
    """Request explicit reasoning from the API (QwQ, DeepSeek-R1).

    Inline ``<think>`` tags are always detected and parsed regardless
    of this flag — it only controls sending ``reasoning: "on"`` to
    LM Studio and folding system prompts into user messages."""
    supports_vision: bool = False
    """Enable for multimodal models (LLaVA, Qwen2-VL) that accept images."""
    max_tool_iterations: int = 25
    """Maximum number of tool calling rounds before forcing a final answer."""
    max_tools: int = 0
    """Maximum number of tool definitions sent to the LLM per request.

    Smaller models (<13B) struggle with more than ~20-30 tools.
    Priority plugins (memory, system_info) are always included first.
    Set to 0 to disable the limit."""
    priority_plugins: list[str] = Field(
        default_factory=lambda: ["memory", "system_info"],
    )
    """Plugins whose tools are always included when limiting by max_tools."""
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

    engine: Literal["faster-whisper"] = "faster-whisper"
    model: str = "large-v3"
    language: str | None = None
    device: str = "cuda"
    compute_type: str = "float16"
    vad_filter: bool = True
    vad_threshold: float = 0.5
    enabled: bool = False
    """Whether STT is enabled. Model loads lazily when first activated."""
    max_audio_duration_s: int = 300
    """Maximum audio recording duration in seconds (5 minutes)."""
    max_audio_size_mb: int = 50
    """Maximum audio buffer size in megabytes."""


class TTSConfig(BaseSettings):
    """Text-to-speech configuration."""

    model_config = SettingsConfigDict(env_prefix="OMNIA_TTS__")

    engine: Literal["piper", "xtts", "kokoro"] = "piper"
    voice: str = "models/tts/it_IT-paola-medium"
    sample_rate: int = 22050
    enabled: bool = False
    """Whether TTS is enabled."""
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    """Playback speed multiplier (0.5 to 2.0)."""
    # XTTS-specific options (ignored when engine == "piper")
    xtts_model: str = "tts_models/multilingual/multi-dataset/xtts_v2"
    """XTTS v2 model identifier."""
    xtts_speaker_wav: str = ""
    """Path to reference WAV for voice cloning (XTTS only)."""
    xtts_language: str = "it"
    """Language for XTTS synthesis."""
    # Kokoro-specific options (ignored when engine != "kokoro")
    kokoro_model: str = "models/tts/kokoro-v1.0.onnx"
    """Path to the Kokoro ONNX model file."""
    kokoro_voices: str = "models/tts/voices-v1.0.bin"
    """Path to the Kokoro voices binary."""
    kokoro_voice: str = "if_sara"
    """Kokoro voice name (e.g. 'if_sara', 'im_nicola', 'if_lucia')."""
    kokoro_language: str = "it"
    """Language code for Kokoro (e.g. 'it', 'en', 'fr')."""


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
    auto_tts_response: bool = True
    """Automatically speak LLM responses when voice mode is active."""
    voice_confirmation_enabled: bool = True
    """Use voice for tool confirmation (say 'sì'/'no')."""


class PcAutomationConfig(BaseSettings):
    """PC Automation plugin configuration."""

    model_config = SettingsConfigDict(env_prefix="OMNIA_PC_AUTOMATION__")

    enabled: bool = False
    """Whether PC automation tools are available."""
    screenshot_lockout_s: int = 60
    """Seconds to block dangerous tools after a screenshot."""
    command_timeout_s: int = 30
    """Maximum seconds a command can run."""
    max_command_output_chars: int = 500
    """Maximum characters of command output to return."""
    confirmations_enabled: bool = True
    """Whether tool confirmations are required (safety feature)."""
    confirmation_timeout_s: int = 60
    """Seconds to wait for user confirmation on dangerous tools."""


class VRAMConfig(BaseSettings):
    """VRAM monitoring configuration."""

    model_config = SettingsConfigDict(env_prefix="OMNIA_VRAM__")

    monitoring_enabled: bool = True
    """Enable GPU VRAM monitoring."""
    warning_threshold_mb: int = 14_000
    """VRAM warning threshold in MB (emit alert above this)."""
    critical_threshold_mb: int = 15_000
    """VRAM critical threshold in MB (trigger degradation above this)."""
    poll_interval_s: float = 10.0
    """Seconds between VRAM checks."""
    total_budget_mb: int = 16_000
    """Total GPU VRAM budget in MB."""


class WebSearchConfig(BaseSettings):
    """Web search plugin configuration."""

    model_config = SettingsConfigDict(env_prefix="OMNIA_WEB_SEARCH__")

    max_results: int = 5
    """Default number of search results."""
    cache_ttl_s: int = 300
    """Seconds before cached search results expire."""
    request_timeout_s: int = 10
    """HTTP timeout for scrape requests in seconds."""
    rate_limit_s: float = 2.0
    """Minimum seconds between search calls."""
    region: str = "it-it"
    """Search region code (e.g. 'it-it', 'us-en', 'wt-wt' for none)."""
    proxy_http: str | None = None
    """Optional HTTP proxy URL."""
    proxy_https: str | None = None
    """Optional HTTPS proxy URL."""


class UIConfig(BaseSettings):
    """UI configuration."""

    model_config = SettingsConfigDict(env_prefix="OMNIA_UI__")

    theme: str = "dark"
    global_hotkey: str = "Ctrl+Shift+O"
    language: str = "it"


class CalendarConfig(BaseSettings):
    """Calendar plugin configuration."""

    model_config = SettingsConfigDict(env_prefix="OMNIA_CALENDAR__")

    timezone: str = "Europe/Rome"
    reminder_check_interval_s: int = 60


class WeatherConfig(BaseSettings):
    """Weather plugin configuration."""

    model_config = SettingsConfigDict(env_prefix="OMNIA_WEATHER__")

    default_city: str = "Rome"
    units: Literal["metric", "imperial"] = "metric"
    lang: str = "it"
    cache_ttl_s: int = 600
    request_timeout_s: int = 8


class ClipboardConfig(BaseSettings):
    """Clipboard plugin configuration."""

    model_config = SettingsConfigDict(env_prefix="OMNIA_CLIPBOARD__")

    max_content_chars: int = 4000


class NotificationsConfig(BaseSettings):
    """Notifications plugin configuration."""

    model_config = SettingsConfigDict(env_prefix="OMNIA_NOTIFICATIONS__")

    app_id: str = "OMNIA"
    sound_enabled: bool = True
    default_timeout_s: int = 5
    max_active_timers: int = 20


class MediaControlConfig(BaseSettings):
    """Media control plugin configuration."""

    model_config = SettingsConfigDict(env_prefix="OMNIA_MEDIA_CONTROL__")

    volume_step: int = 10
    brightness_step: int = 10


class FileSearchConfig(BaseSettings):
    """File search plugin configuration."""

    model_config = SettingsConfigDict(env_prefix="OMNIA_FILE_SEARCH__")

    allowed_paths: list[str] = Field(default_factory=list)
    forbidden_paths: list[str] = Field(default_factory=lambda: [
        "C:\\Windows", "C:\\Program Files",
        "C:\\Program Files (x86)", "C:\\ProgramData",
    ])
    max_results: int = 50
    max_file_size_read_bytes: int = 1_048_576
    max_content_chars: int = 8000
    follow_symlinks: bool = False


class NewsConfig(BaseSettings):
    """News/briefing plugin configuration."""

    model_config = SettingsConfigDict(env_prefix="OMNIA_NEWS__")

    feeds: list[str] = Field(default_factory=lambda: [
        "https://feeds.bbci.co.uk/news/world/rss.xml",
        "https://www.ansa.it/sito/notizie/tecnologia/rss.xml",
        "https://www.repubblica.it/rss/homepage/rss2.0.xml",
    ])
    max_articles: int = 10
    cache_ttl_minutes: int = 15
    request_timeout_s: int = 10
    default_lang: str = "it"


class MemoryConfig(BaseSettings):
    """Persistent semantic memory configuration."""

    model_config = SettingsConfigDict(env_prefix="OMNIA_MEMORY__")

    enabled: bool = False
    """Enable the Memory Service. False by default (opt-in)."""

    db_path: str = "data/memory.db"
    """Path to the dedicated memory SQLite file (separate from omnia.db)."""

    embedding_model: str = "text-embedding-mxbai-embed-large-v1"
    """Embedding model name for LM Studio/Ollama /v1/embeddings."""

    embedding_dim: int = 1024
    """Vector dimensions of the chosen embedding model."""

    embedding_fallback: bool = True
    """If True, fall back to fastembed (CPU) when LLM embedding API is unavailable."""

    top_k: int = 5
    """Max memories retrieved for context injection."""

    similarity_threshold: float = 0.4
    """Minimum cosine similarity score to include a memory (0.0\u20131.0)."""

    inject_in_context: bool = True
    """If True, relevant memories are injected into the system prompt."""

    context_max_chars: int = 2000
    """Max characters injected from memory context into prompt."""

    session_ttl_hours: int = 24
    """TTL for session-scoped memories. Expired entries are ignored."""

    auto_cleanup_days: int = 90
    """Remove memories not accessed for N days (0 = disabled)."""


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
    pc_automation: PcAutomationConfig = Field(
        default_factory=PcAutomationConfig
    )
    vram: VRAMConfig = Field(default_factory=VRAMConfig)
    ui: UIConfig = Field(default_factory=UIConfig)
    web_search: WebSearchConfig = Field(default_factory=WebSearchConfig)
    calendar: CalendarConfig = Field(default_factory=CalendarConfig)
    weather: WeatherConfig = Field(default_factory=WeatherConfig)
    clipboard: ClipboardConfig = Field(default_factory=ClipboardConfig)
    notifications: NotificationsConfig = Field(
        default_factory=NotificationsConfig
    )
    media_control: MediaControlConfig = Field(
        default_factory=MediaControlConfig
    )
    file_search: FileSearchConfig = Field(default_factory=FileSearchConfig)
    news: NewsConfig = Field(default_factory=NewsConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)

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
