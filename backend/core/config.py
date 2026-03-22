"""AL\CE — Configuration system.

Loads configuration from ``config/default.yaml`` with environment-variable
overrides (prefix ``ALICE_``, nested via double-underscore).  Uses Pydantic
Settings v2 for validation and env parsing.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import re

import yaml
from loguru import logger
from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
"""Absolute path to the AL\CE project root (two levels up from core/)."""

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

    model_config = SettingsConfigDict(env_prefix="ALICE_SERVER__")

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

    model_config = SettingsConfigDict(env_prefix="ALICE_LLM__")

    provider: str = "lmstudio"
    base_url: str = "http://localhost:1234"
    model: str = DEFAULT_MODEL
    temperature: float = 0.7
    max_tokens: int = 16384
    api_token: str = ""
    """LM Studio API authentication token (optional)."""
    timeout: float = 120.0
    """HTTP read timeout in seconds for streaming LLM responses."""
    connect_timeout: float = 50.0
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
    tool_execution_timeout: float = 120.0
    """Timeout in seconds for parallel tool execution per iteration.

    If any tool takes longer than this, the gather is cancelled and
    a timeout error is recorded for the stuck tool(s)."""
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

    model_config = SettingsConfigDict(env_prefix="ALICE_STT__")

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

    model_config = SettingsConfigDict(env_prefix="ALICE_TTS__")

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

    model_config = SettingsConfigDict(env_prefix="ALICE_DATABASE__")

    url: str = "sqlite+aiosqlite:///data/alice.db"


class PluginsConfig(BaseSettings):
    """Plugin configuration."""

    model_config = SettingsConfigDict(env_prefix="ALICE_PLUGINS__")

    enabled: list[str] = Field(
        default_factory=lambda: [
            "system_info",
        ]
    )


class HomeAssistantConfig(BaseSettings):
    """Home Assistant integration configuration."""

    model_config = SettingsConfigDict(env_prefix="ALICE_HOME_ASSISTANT__")

    url: str = "http://homeassistant.local:8123"
    token: str = ""


class MQTTConfig(BaseSettings):
    """MQTT broker configuration."""

    model_config = SettingsConfigDict(env_prefix="ALICE_MQTT__")

    broker: str = "localhost"
    port: int = 1883
    username: str = ""
    password: str = ""


class VoiceConfig(BaseSettings):
    """Voice interaction configuration."""

    model_config = SettingsConfigDict(env_prefix="ALICE_VOICE__")

    wake_word: str = "alice"
    activation_mode: str = "push_to_talk"
    silence_timeout_ms: int = 1500
    auto_tts_response: bool = True
    """Automatically speak LLM responses when voice mode is active."""
    voice_confirmation_enabled: bool = True
    """Use voice for tool confirmation (say 'sì'/'no')."""


class PcAutomationConfig(BaseSettings):
    """PC Automation plugin configuration."""

    model_config = SettingsConfigDict(env_prefix="ALICE_PC_AUTOMATION__")

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

    model_config = SettingsConfigDict(env_prefix="ALICE_VRAM__")

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

    model_config = SettingsConfigDict(env_prefix="ALICE_WEB_SEARCH__")

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

    model_config = SettingsConfigDict(env_prefix="ALICE_UI__")

    theme: str = "dark"
    global_hotkey: str = "Ctrl+Shift+O"
    language: str = "it"


class CalendarConfig(BaseSettings):
    """Calendar plugin configuration."""

    model_config = SettingsConfigDict(env_prefix="ALICE_CALENDAR__")

    timezone: str = "Europe/Rome"
    reminder_check_interval_s: int = 60


class WeatherConfig(BaseSettings):
    """Weather plugin configuration."""

    model_config = SettingsConfigDict(env_prefix="ALICE_WEATHER__")

    default_city: str = "Rome"
    units: Literal["metric", "imperial"] = "metric"
    lang: str = "it"
    cache_ttl_s: int = 600
    request_timeout_s: int = 8


class ClipboardConfig(BaseSettings):
    """Clipboard plugin configuration."""

    model_config = SettingsConfigDict(env_prefix="ALICE_CLIPBOARD__")

    max_content_chars: int = 4000


class NotificationsConfig(BaseSettings):
    """Notifications plugin configuration."""

    model_config = SettingsConfigDict(env_prefix="ALICE_NOTIFICATIONS__")

    app_id: str = "AL\\CE"
    sound_enabled: bool = True
    default_timeout_s: int = 5
    max_active_timers: int = 20


class MediaControlConfig(BaseSettings):
    """Media control plugin configuration."""

    model_config = SettingsConfigDict(env_prefix="ALICE_MEDIA_CONTROL__")

    volume_step: int = 10
    brightness_step: int = 10


class FileSearchConfig(BaseSettings):
    """File search plugin configuration."""

    model_config = SettingsConfigDict(env_prefix="ALICE_FILE_SEARCH__")

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

    model_config = SettingsConfigDict(env_prefix="ALICE_NEWS__")

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

    model_config = SettingsConfigDict(env_prefix="ALICE_MEMORY__")

    enabled: bool = False
    """Enable the Memory Service. False by default (opt-in)."""

    db_path: str = "data/memory.db"
    """Path to the dedicated memory SQLite file (separate from alice.db)."""

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
    """Remove memories older than N days based on creation date (0 = disabled)."""


class NotesConfig(BaseSettings):
    """Note system (Obsidian-like vault) configuration."""

    model_config = SettingsConfigDict(env_prefix="ALICE_NOTES__")

    enabled: bool = False
    """Enable the Note System. False by default (opt-in)."""

    db_path: str = "data/notes.db"
    """Path to the dedicated notes SQLite file (separate from alice.db)."""

    embedding_enabled: bool = True
    """Enable semantic search via sqlite-vec embeddings."""

    embedding_model: str = "text-embedding-mxbai-embed-large-v1"
    """Embedding model name for LM Studio/Ollama /v1/embeddings."""

    embedding_dim: int = 1024
    """Vector dimensions of the chosen embedding model."""

    embedding_fallback: bool = True
    """Fall back to fastembed (CPU) when LLM API is unavailable."""

    max_content_chars_llm: int = 8000
    """Max note content chars included in LLM tool responses."""

    semantic_threshold: float = 0.70
    """Minimum cosine similarity for semantic search results."""

    max_search_results: int = 20
    """Maximum results returned from search."""


_MCP_SERVER_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,29}$")


class McpServerConfig(BaseModel):
    """Configuration for a single MCP server connection."""

    name: str
    """Unique identifier (lowercase_snake_case). Used in tool prefix: mcp_{name}_*."""

    transport: Literal["stdio", "sse"] = "stdio"

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        if not _MCP_SERVER_NAME_RE.match(v):
            raise ValueError(
                f"MCP server name '{v}' must be lowercase "
                "alphanumeric + underscores, 1-30 chars, start with letter"
            )
        return v
    """Connection transport: 'stdio' for subprocess, 'sse' for HTTP/SSE."""

    command: list[str] | None = None
    """[stdio only] Command + args to launch the MCP server subprocess."""

    url: str | None = None
    """[sse only] Full URL of the SSE endpoint."""

    env: dict[str, str] = Field(default_factory=dict)
    """Extra environment variables injected into the subprocess (stdio only)."""

    enabled: bool = True
    """Set to false to skip this server without removing it from config."""

    @model_validator(mode="after")
    def _validate_transport_fields(self) -> McpServerConfig:
        if self.transport == "stdio" and not self.command:
            raise ValueError(
                f"MCP server '{self.name}': stdio transport requires 'command'"
            )
        if self.transport == "sse" and not self.url:
            raise ValueError(
                f"MCP server '{self.name}': sse transport requires 'url'"
            )
        return self


class ChartConfig(BaseSettings):
    """Configurazione plugin chart_generator."""

    model_config = SettingsConfigDict(env_prefix="ALICE_CHART__")

    enabled: bool = False
    """Abilita il plugin chart_generator (opt-in, come tutti i plugin AL\CE)."""

    chart_output_dir: str = "data/charts"
    """Directory dove vengono salvati i chart spec JSON."""

    max_option_chars: int = 10_000
    """Dimensione massima della echarts_option serializzata (in caratteri)."""

    max_charts: int = 1_000
    """Numero massimo di grafici persistiti."""


class WhiteboardConfig(BaseSettings):
    """Configurazione plugin whiteboard (tldraw)."""

    model_config = SettingsConfigDict(env_prefix="ALICE_WHITEBOARD__")

    enabled: bool = False
    """Abilita il plugin whiteboard (opt-in)."""

    whiteboard_output_dir: str = "data/whiteboards"
    """Directory dove vengono salvati i board spec JSON."""

    max_boards: int = 500
    """Numero massimo di lavagne persistite."""


class EmailConfig(BaseSettings):
    """Email assistant (IMAP / SMTP) configuration."""

    model_config = SettingsConfigDict(env_prefix="ALICE_EMAIL__")

    enabled: bool = False
    imap_host: str = ""
    imap_port: int = 993
    imap_ssl: bool = True
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_ssl: bool = False
    username: str = ""
    use_keyring: bool = True
    password: SecretStr = Field(default=SecretStr(""))
    fetch_last_n: int = 20
    max_fetch: int = 50
    max_email_body_chars: int = 8_000
    cache_ttl_s: int = 300
    rate_limit_send_per_hour: int = 10
    allowed_recipients: list[str] = Field(default_factory=list)
    imap_idle_enabled: bool = True
    connection_timeout_s: int = 30
    archive_folder: str = "Archive"


class TrellisServiceConfig(BaseSettings):
    """TRELLIS 3D generation microservice configuration."""

    model_config = SettingsConfigDict(env_prefix="ALICE_TRELLIS__")

    enabled: bool = False
    """Enable the cad_generator plugin. Requires the TRELLIS microservice installed."""

    service_url: str = "http://localhost:8090"
    """Base URL of the TRELLIS microservice (separate Python 3.10-3.12 process)."""

    request_timeout_s: int = 600
    """Timeout for 3D generation in seconds.
    First run downloads model weights (~60s) + two sampling passes (~180s).
    Subsequent runs still need ~180s for inference. 600s gives ample margin."""

    max_model_size_mb: int = 100
    """Maximum accepted size for generated GLB files."""

    model_output_dir: str = "data/3d_models"
    """Local directory for generated GLB files (relative to PROJECT_ROOT)."""

    auto_vram_swap: bool = True
    """If True, automatically unload the LLM from VRAM before 3D generation
    and reload it after. Required on GPUs with < 20GB VRAM."""

    trellis_model: str = "JeffreyXiang/TRELLIS-text-large"
    """TRELLIS model to load in the microservice (full HuggingFace repo ID).
    JeffreyXiang/TRELLIS-text-* = text-to-3D (accepts text prompts from chat).
    JeffreyXiang/TRELLIS-image-* = image-to-3D (requires an input image)."""

    trellis_dir: str = ""
    """Path to the TRELLIS-for-windows installation directory.
    Used by start-trellis.ps1. Empty = auto-detect (../TRELLIS-for-windows)."""

    seed: int = -1
    """Seed for generation. -1 = random."""


class NetworkProbeConfig(BaseSettings):
    """Network probe plugin configuration."""

    model_config = SettingsConfigDict(env_prefix="ALICE_NETWORK_PROBE__")

    max_ports_per_scan: int = 100
    """Hard upper limit on TCP ports per ``scan_ports`` call."""

    max_ping_count: int = 10
    """Maximum allowed ICMP packet count per ``ping_host`` call."""

    ping_timeout_s: float = 2.0
    """Seconds to wait for each ICMP reply."""

    port_scan_timeout_s: float = 1.0
    """Default per-port TCP connect timeout in seconds."""

    service_check_timeout_s: float = 5.0
    """Timeout for HTTP/SSH/FTP service banner checks in seconds."""

    discover_timeout_s: float = 30.0
    """Total timeout budget for ``discover_local_devices`` in seconds."""

    max_concurrent_scans: int = 50
    """Maximum concurrent TCP connections during port scanning."""

    max_concurrent_pings: int = 20
    """Maximum concurrent ping subprocesses during device discovery."""

    traceroute_max_hops: int = 30
    """Hard upper limit on hops for ``traceroute_host``."""

    max_connections_returned: int = 500
    """Maximum number of connections returned by ``get_open_connections``."""


class McpConfig(BaseSettings):
    """MCP client configuration."""

    model_config = SettingsConfigDict(env_prefix="ALICE_MCP__")

    servers: list[McpServerConfig] = Field(default_factory=list)
    """List of MCP servers to connect at startup. Empty by default (opt-in)."""


# ---------------------------------------------------------------------------
# Top-level config
# ---------------------------------------------------------------------------


class AliceConfig(BaseSettings):
    """Root configuration aggregating every sub-section."""

    model_config = SettingsConfigDict(
        env_prefix="ALICE_",
        env_nested_delimiter="__",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: Any,
        env_settings: Any,
        dotenv_settings: Any,
        file_secret_settings: Any,
    ) -> tuple[Any, ...]:
        """Env vars override YAML (init kwargs), not the other way around."""
        return (env_settings, init_settings, dotenv_settings, file_secret_settings)

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
    notes: NotesConfig = Field(default_factory=NotesConfig)
    mcp: McpConfig = Field(default_factory=McpConfig)
    trellis: TrellisServiceConfig = Field(default_factory=TrellisServiceConfig)
    chart: ChartConfig = Field(default_factory=ChartConfig)
    whiteboard: WhiteboardConfig = Field(default_factory=WhiteboardConfig)
    email: EmailConfig = Field(default_factory=EmailConfig)
    network_probe: NetworkProbeConfig = Field(
        default_factory=NetworkProbeConfig
    )

    @model_validator(mode="before")
    @classmethod
    def _resolve_paths(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Resolve relative paths to absolute using the project root."""
        if not isinstance(data, dict):
            return data

        # -- system prompt file --
        llm_data = data.get("llm")
        if isinstance(llm_data, dict):
            raw = llm_data.get(
                "system_prompt_file", "config/system_prompt.md"
            )
            if raw and not Path(raw).is_absolute():
                llm_data["system_prompt_file"] = str(
                    PROJECT_ROOT / raw
                )

        # -- database URL (make relative sqlite path absolute) --
        db_data = data.get("database")
        if isinstance(db_data, dict):
            db_url = db_data.get(
                "url", "sqlite+aiosqlite:///data/alice.db"
            )
            if db_url.startswith("sqlite") and ":///" in db_url:
                prefix, db_path = db_url.split(":///", 1)
                if db_path and not Path(db_path).is_absolute():
                    abs_path = PROJECT_ROOT / db_path
                    db_data["url"] = f"{prefix}:///{abs_path}"
        # -- MCP server commands: expand ~ and env vars in args --
        mcp_data = data.get("mcp", {})
        if isinstance(mcp_data, dict):
            for server in mcp_data.get("servers", []):
                if isinstance(server, dict) and server.get("command"):
                    server["command"] = [
                        str(Path(os.path.expandvars(arg)).expanduser())
                        if ("~" in arg or "$" in arg or "%" in arg)
                        else arg
                        for arg in server["command"]
                    ]
        return data


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_config(path: Path | None = None) -> AliceConfig:
    """Load configuration from a YAML file and apply env-var overrides.

    Args:
        path: Path to the YAML config file.  Defaults to
              ``config/default.yaml`` relative to the project root.

    Returns:
        A fully validated ``AliceConfig`` instance.
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

    return AliceConfig(**raw)
