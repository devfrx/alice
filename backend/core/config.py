"""AL\\CE — Configuration system.

Loads configuration from ``config/default.yaml`` with environment-variable
overrides (prefix ``ALICE_``, nested via double-underscore).  Uses Pydantic
Settings v2 for validation and env parsing.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from loguru import logger
from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
"""Absolute path to the AL\\CE project root (two levels up from core/)."""

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
            *[f"http://localhost:{p}" for p in range(5173, 5181)],
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
    """One of "lmstudio", "ollama", "openrouter"."""
    base_url: str = "http://localhost:1234"
    model: str = DEFAULT_MODEL
    temperature: float = 0.7
    max_tokens: int = -1
    api_token: str = ""
    """LM Studio API authentication token (optional)."""
    timeout: float = 120.0
    """HTTP read timeout in seconds for streaming LLM responses."""
    connect_timeout: float = 50.0
    """HTTP connect timeout in seconds."""
    system_prompt_file: str = "config/system_prompt.md"
    system_prompt_enabled: bool = True
    """Whether to include the system prompt in LLM requests."""
    user_preferred_name: str = ""
    """How the user wants the assistant to address them. Injected into the
    system prompt's environment block so the model uses it. Empty = unset."""
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
    tool_execution_timeout: float = 1300.0
    """Timeout in seconds for parallel tool execution per iteration.

    Default 1300s (~22 min) covers the slowest tool: TRELLIS / TRELLIS.2
    image-to-3D generation, which can take up to ``trellis*.request_timeout_s``
    (1200s) plus client overhead. Faster tools complete in a few seconds and
    are unaffected.

    If any tool takes longer than this, the gather is cancelled and
    a timeout error is recorded for the stuck tool(s)."""
    max_tools: int = 0
    """Maximum number of tool definitions sent to the LLM per request.

    Smaller models (<13B) struggle with more than ~20-30 tools.
    Priority plugins (memory, system_info) are always included first.
    Set to 0 to disable the limit."""
    priority_plugins: list[str] = Field(
        default_factory=lambda: ["memory", "system_info", "web_search"],
    )
    """Plugins whose tools are always included regardless of tool_rag results."""
    disabled_tools: list[str] = Field(default_factory=list)
    """Namespaced tool names the user has turned off for chat (opt-out filter).

    Empty (the default) means every available tool is offered to the LLM.
    When non-empty, matching tools are removed from the toolset assembled
    in the non-RAG / non-scoped branch of the chat handler. The selection
    is persisted as a user preference and survives restarts.

    Has no effect when ``tool_rag_enabled`` is True (Tool RAG auto-selects
    the relevant tools) or when ``tools_enabled`` is False (no tools sent)."""
    # -- Ollama-specific options (ignored by other providers) --
    num_ctx: int = 8192
    """Context window size. Ollama defaults to 2048; 8192 is better for 9B+ models."""
    num_gpu: int = -1
    """-1 = offload all layers to GPU. Set to 0 to force CPU."""
    keep_alive: str = "5m"
    """How long Ollama keeps the model loaded in memory after a request."""
    # -- OpenRouter-specific options (used when provider == "openrouter") --
    openrouter_api_key: str = ""
    """OpenRouter API key (Bearer). Empty = not configured."""
    openrouter_base_url: str = "https://openrouter.ai/api"
    """OpenRouter API origin. ``/v1/...`` paths are appended by the client."""
    openrouter_model: str = ""
    """Active OpenRouter model id (e.g. ``anthropic/claude-sonnet-5``).

    Kept separate from ``model`` so switching provider back and forth
    preserves both the local and the cloud selection."""
    openrouter_favorites: list[str] = Field(default_factory=list)
    """Pinned OpenRouter model ids, shown first in the model selector."""
    tool_rag_enabled: bool = True
    """Use semantic search to select relevant tools instead of sending all tool definitions."""
    tool_rag_top_k: int = 20
    """Number of most relevant tools retrieved via Tool RAG per LLM request."""
    # -- Context compression options --
    context_compression_enabled: bool = True
    """Enable automatic context compression when approaching context window limit."""
    context_compression_threshold: float = 0.75
    """Fraction of context window usage that triggers compression (0.50–0.95)."""
    context_compression_reserve: int = 4096
    """Tokens always reserved for model output generation (minimum 512)."""
    context_compression_timeout: float = 120.0
    """Read timeout in seconds for the non-streaming LLM call used during compression.

    Reasoning models (QwQ-32B, DeepSeek-R1) can generate slowly (~10 tok/s);
    512 output tokens alone may take ~51 s.  120 s gives a safe margin.
    """

    @property
    def effective_base_url(self) -> str:
        """Base URL for the active provider (OpenRouter or local server)."""
        if self.provider == "openrouter":
            return self.openrouter_base_url.rstrip("/")
        return self.base_url

    @field_validator("context_compression_threshold")
    @classmethod
    def _clamp_threshold(cls, v: float) -> float:
        """Ensure compression threshold stays within [0.50, 0.95]."""
        return max(0.50, min(0.95, v))

    @field_validator("context_compression_reserve")
    @classmethod
    def _positive_reserve(cls, v: int) -> int:
        """Ensure compression reserve is at least 512 tokens."""
        return max(512, v)

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
    voice: str = "models/tts/piper/it_IT-paola-medium"
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


class PcAutomationConfig(BaseSettings):
    """PC Automation plugin configuration.

    Note:
        The ``confirmations_enabled`` / ``confirmation_timeout_s`` knobs used
        to live here but were promoted to the neutral :class:`PermissionsConfig`
        (``permissions.*``) in Fase 2 — they gate **every** dangerous tool, not
        just PC-automation ones. Legacy ``pc_automation.*`` values still load
        (folded into ``permissions`` by :func:`migrate_legacy_config_keys`).
    """

    model_config = SettingsConfigDict(env_prefix="ALICE_PC_AUTOMATION__")

    screenshot_lockout_s: int = 60
    """Seconds to block dangerous tools after a screenshot."""
    command_timeout_s: int = 30
    """Maximum seconds a command can run."""
    max_command_output_chars: int = 500
    """Maximum characters of command output to return."""


class PermissionsConfig(BaseSettings):
    """Central tool-permission / confirmation policy (neutral home).

    Owns the cross-cutting safety knobs that gate **any** dangerous tool,
    independent of the plugin that exposes it. Consumed by the turn engine's
    ``ConfirmationMiddleware`` and ``PermissionService``. Promoted out of
    :class:`PcAutomationConfig` in Fase 2; old keys migrate transparently.
    """

    model_config = SettingsConfigDict(env_prefix="ALICE_PERMISSIONS__")

    confirmations_enabled: bool = True
    """Whether tool confirmations are required (safety feature)."""
    confirmation_timeout_s: int = 60
    """Seconds to wait for user confirmation on dangerous tools."""
    default_mode: Literal["strict", "auto_edits", "plan", "autopilot"] = "strict"
    """Default permission tier for a conversation with no explicit mode set.

    ``strict`` reproduces the pre-Fase-7 behaviour (prompt for every
    confirmation-required tool); the per-conversation mode (set only by the
    user, never the model) overrides this default."""


class CommandsConfig(BaseSettings):
    """Command Bridge policy (Fase 7, spec §7).

    Governs the kernel-owned ``app_command`` tool and the events-WS command
    RPC. ``disabled_commands`` is the per-command denylist the spec calls
    "allowlist configurabile per comando": a listed command is dropped at
    manifest ingestion and refused at call time.
    """

    model_config = SettingsConfigDict(env_prefix="ALICE_COMMANDS__")

    enabled: bool = True
    """Master switch for the Command Bridge (tool + manifest ingestion)."""
    rpc_timeout_s: float = 10.0
    """Seconds the ``app_command`` tool waits for the UI's command.result."""
    disabled_commands: list[str] = Field(default_factory=list)
    """Command names never callable by the agent, regardless of manifest."""


class AttentionConfig(BaseSettings):
    """AttentionService policy (Fase 8, spec §8)."""

    model_config = SettingsConfigDict(env_prefix="ALICE_ATTENTION__")

    enabled: bool = True
    """Master switch for agent-initiated attention towards the user."""
    cooldown_s: float = 30.0
    """Minimum seconds between two non-urgent notifications (anti-spam)."""


class TriggersConfig(BaseSettings):
    """TriggerService policy (Fase 8, spec §8)."""

    model_config = SettingsConfigDict(env_prefix="ALICE_TRIGGERS__")

    enabled: bool = True
    """Master switch for autonomous-turn triggers (none registered by default)."""
    max_concurrent_turns: int = 1
    """Autonomous turns that may run at once; extra fires are skipped."""


class WorkspaceScopeConfig(BaseSettings):
    """Workspace-scope policy for tool filesystem confinement (Fase 6)."""

    model_config = SettingsConfigDict(env_prefix="ALICE_SCOPE__")

    forbidden_paths: list[str] = Field(default_factory=list)
    """Roots always out of scope even when a workspace scope is set."""

    fallback_mode: Literal["sandbox", "disabled"] = "disabled"
    """When no explicit scope is set, governs the **human interactive terminal**:
    'disabled' (the default) ⇒ the terminal refuses to run until the user sets a
    workspace folder; 'sandbox' ⇒ an ephemeral per-conversation working dir is
    allowed. NOTE: the *model's* permission gate no longer depends on this — it
    consumes :meth:`ScopeService.effective_roots`, which always confines the
    model's filesystem/exec tools to the explicit scope or a per-conversation
    sandbox dir (never the OS home), in every tier."""

    sandbox_root: str = "data/workspaces"
    """Project-relative root for ephemeral per-conversation sandboxes."""


class TerminalConfig(BaseSettings):
    """Scoped-terminal plugin policy (Fase 6).  Disabled by default."""

    model_config = SettingsConfigDict(env_prefix="ALICE_TERMINAL__")

    enabled: bool = Field(default=False, description="Expose run_terminal_command.")
    command_timeout_s: int = Field(
        default=30,
        ge=1,
        le=600,
        description="Per-command wall-clock timeout (seconds).",
    )
    max_output_bytes: int = Field(
        default=100_000,
        ge=1,
        description="Cap on captured stdout+stderr bytes.",
    )
    allow_network: bool = Field(
        default=False,
        description="Best-effort network policy hint (not a hard guarantee on Windows).",
    )
    max_sessions: int = Field(
        default=8,
        ge=1,
        le=64,
        description="Max concurrent interactive PTY sessions per conversation (Fase 7).",
    )
    interactive_shell: str | None = Field(
        default=None,
        description=(
            "Shell program for interactive PTY sessions (Fase 7). None ⇒ ComSpec "
            "(cmd.exe) on Windows, $SHELL (/bin/bash) on POSIX."
        ),
    )


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


class QdrantConfig(BaseSettings):
    """Qdrant vector store configuration."""

    model_config = SettingsConfigDict(env_prefix="ALICE_QDRANT__")

    mode: Literal["embedded", "server"] = "embedded"
    """'embedded' runs in-process (no Docker needed); 'server' connects to a Qdrant instance."""

    path: str = "data/qdrant"
    """[embedded only] Directory where Qdrant stores data on disk."""

    host: str = "localhost"
    """[server only] Qdrant server hostname."""

    port: int = 6333
    """[server only] Qdrant server gRPC port."""

    embedding_model: str = "text-embedding-bge-small-en-v1.5"
    """Embedding model name for LM Studio/Ollama /v1/embeddings."""

    embedding_dim: int = 1024
    """Vector dimensions of the chosen embedding model."""

    embedding_fallback: bool = True
    """If True, fall back to fastembed (CPU) when LLM embedding API is unavailable."""


class ContinuumConfig(BaseSettings):
    """Continuum knowledge-base integration.

    When enabled, ``note``-kind knowledge is delegated to a running
    Continuum server (see :class:`~backend.services.knowledge.\
continuum_backend.ContinuumBackend`) instead of Alice's local note
    store, while ``memory``/``fact`` kinds keep using Qdrant. The two are
    composed by :class:`~backend.services.knowledge.composite_backend.\
CompositeKnowledgeBackend`.

    Continuum is a *separate* local application; Alice talks to it over
    its REST API. The optional bearer token must match the server's
    ``CONTINUUM_API_TOKEN`` when that server enforces authentication.
    """

    model_config = SettingsConfigDict(env_prefix="ALICE_CONTINUUM__")

    enabled: bool = True
    """Route ``note`` knowledge to Continuum instead of the local vault."""

    base_url: str = "http://localhost:3001"
    """Base URL of the Continuum server (no trailing ``/api``)."""

    api_token: str | None = None
    """Bearer token sent on every request; ``None`` for token-less servers."""

    timeout_s: float = 15.0
    """Per-request HTTP timeout in seconds."""

    folder_cache_ttl_s: float = 30.0
    """How long the folder-path ↔ id resolution cache stays valid."""

    note_max_content_chars_llm: int = 8000
    """Max note content chars included in LLM ``read_note`` responses."""

    agent_prompt_file: str = "config/continuum_agent_prompt.md"
    """System prompt used for the *Continuum-scoped* Alice agent — i.e.
    chats opened from inside Continuum (``?scope=continuum``). Gives the
    agent a clean, Continuum-only persona instead of Alice's general
    desktop prompt. Resolved to an absolute path at load time."""

    agent_tool_plugins: list[str] = Field(
        default_factory=lambda: ["continuum"]
    )
    """Plugins whose tools are ALWAYS injected for the Continuum-scoped
    agent, bypassing tool RAG so the agent reliably knows how to act on
    Continuum itself."""


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
    """Abilita il plugin chart_generator (opt-in, come tutti i plugin AL\\CE)."""

    max_option_chars: int = 10_000
    """Dimensione massima della echarts_option serializzata (in caratteri)."""

    max_charts: int = 1_000
    """Numero massimo di grafici persistiti."""


class WhiteboardConfig(BaseSettings):
    """Configurazione plugin whiteboard (tldraw)."""

    model_config = SettingsConfigDict(env_prefix="ALICE_WHITEBOARD__")

    enabled: bool = False
    """Abilita il plugin whiteboard (opt-in)."""

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

    request_timeout_s: int = 1200
    """Timeout for 3D generation in seconds (default 20 min).
    First run downloads model weights (~60s) + two sampling passes (~180s).
    Long timeout covers cold starts and high-quality presets on consumer GPUs."""

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


class Trellis2ServiceConfig(BaseSettings):
    """TRELLIS.2 (microsoft/TRELLIS.2-4B) microservice configuration.

    Sibling of :class:`TrellisServiceConfig` for the next-generation
    image-to-3D model.  The two services run side by side on different
    ports and use independent Python venvs.
    """

    model_config = SettingsConfigDict(env_prefix="ALICE_TRELLIS2__")

    enabled: bool = False
    """Enable the TRELLIS.2 microservice integration."""

    service_url: str = "http://localhost:8091"
    """Base URL of the TRELLIS.2 microservice (separate Python 3.10-3.12 process)."""

    request_timeout_s: int = 1200
    """Timeout for 3D generation in seconds (default 20 min). First call
    downloads ~8GB of weights; pipeline 1536_cascade can take minutes on
    consumer GPUs."""

    max_model_size_mb: int = 100
    """Maximum accepted size for generated GLB files."""

    model_output_dir: str = "data/3d_models"
    """Local directory for generated GLB files (relative to PROJECT_ROOT)."""

    auto_vram_swap: bool = True
    """If True, automatically unload the LLM from VRAM before 3D generation
    and reload it after. Required on GPUs with < 24GB VRAM (4B model)."""

    trellis2_model: str = "microsoft/TRELLIS.2-4B"
    """TRELLIS.2 model to load in the microservice (HuggingFace repo ID).
    Currently only the 4B image-to-3D checkpoint is published."""

    trellis2_dir: str = ""
    """Path to the TRELLIS.2 installation directory.
    Used by start-trellis2.ps1. Empty = auto-detect (../TRELLIS.2)."""

    pipeline_type: str = "1024"
    """Default generation resolution: 512 (~3s), 1024 (~17s),
    1024_cascade or 1536_cascade (~60s on H100)."""

    allowed_pipeline_types: list[str] = ["512", "1024"]
    """Whitelist of pipeline_type values the LLM is allowed to pick.
    On consumer GPUs (16 GB VRAM) ``512`` and ``1024`` reliably fit
    CuMesh's post-processing buffers; the ``*_cascade`` variants
    produce mesh densities that go OOM in ``fill_holes``/``simplify``.
    Add them back here only on 24 GB+ cards."""

    decimation_target: int = 600_000
    """Target triangle count for the exported GLB. 500k is the tested
    maximum for RTX 5080 (16 GB VRAM); raise to 1M+ on 24 GB+ cards."""

    texture_size: int = 4096
    """Square PBR texture resolution for the exported GLB. 4096 works
    on 16 GB VRAM with pipeline_type 512 and 1024; lower to 2048 if
    running into OOM during texture baking."""

    seed: int = -1
    """Seed for generation. -1 = random."""

    force_diffuse_materials: bool = True
    """If True, post-process the generated GLB to neutralise the
    unreliable ``metallic`` channel emitted by the TRELLIS.2 texturing
    pipeline.  Stylised / anime characters are wrongly predicted as
    near-pure metal, which under a small ``RoomEnvironment`` renders
    them almost completely black.  Setting ``metallicFactor=0`` makes
    the material fully diffuse and restores the real ``baseColorTexture``
    look.  Disable to keep the raw TRELLIS.2 export unchanged."""

    diffuse_roughness_factor: float = 0.85
    """``roughnessFactor`` applied alongside ``force_diffuse_materials``.
    ``0.85`` keeps the look matte without going fully Lambertian.
    Ignored when ``force_diffuse_materials`` is False."""


class Trellis2MultiviewServiceConfig(BaseSettings):
    """TRELLIS.2 multi-view microservice configuration.

    Sibling of :class:`Trellis2ServiceConfig` for the multi-image
    fork (cpuai/Trellis.2.multiview).  The two services use
    independent venvs and ports so they can coexist or be enabled
    one at a time.  Multi-view conditioning typically yields a
    visibly more accurate reconstruction when 2-6 photos of the
    same object are provided.
    """

    model_config = SettingsConfigDict(env_prefix="ALICE_TRELLIS2_MULTIVIEW__")

    enabled: bool = False
    """Enable the TRELLIS.2 multi-view microservice integration."""

    service_url: str = "http://localhost:8092"
    """Base URL of the TRELLIS.2 multi-view microservice."""

    request_timeout_s: int = 1800
    """Timeout for multi-view 3D generation in seconds (default 30 min).
    Multi-view runs do more sampling work than single-image and the
    first call also downloads ~8GB of weights."""

    max_model_size_mb: int = 100
    """Maximum accepted size for generated GLB files."""

    model_output_dir: str = "data/3d_models"
    """Local directory for generated GLB files (relative to PROJECT_ROOT)."""

    auto_vram_swap: bool = True
    """If True, automatically unload the LLM from VRAM before generation
    and reload it after.  Required on GPUs with < 24GB VRAM."""

    trellis2multiview_model: str = "microsoft/TRELLIS.2-4B"
    """TRELLIS.2 checkpoint to load (HuggingFace repo ID).  Currently
    only the 4B image-to-3D weights support multi-view conditioning."""

    trellis2multiview_dir: str = ""
    """Path to the TRELLIS.2.multiview installation directory.  Used by
    start-trellis2multiview.ps1.  Empty = auto-detect (../TRELLIS.2.multiview)."""

    pipeline_type: str = "1024"
    """Default generation resolution: 512 / 1024 / 1024_cascade /
    1536_cascade.  See trellis2 for trade-offs."""

    allowed_pipeline_types: list[str] = ["512", "1024"]
    """Whitelist of pipeline_type values the LLM is allowed to pick.
    Same hardware-budget reasoning as :class:`Trellis2ServiceConfig`."""

    decimation_target: int = 500_000
    """Target triangle count for the exported GLB."""

    texture_size: int = 4096
    """Square PBR texture resolution for the exported GLB."""

    seed: int = -1
    """Seed for generation. -1 = random."""

    max_input_images: int = 6
    """Maximum number of views the LLM tool will accept.  Capped here
    AND server-side (``trellis2multiview_server._MAX_INPUT_IMAGES``).
    Most reconstructions plateau between 4 and 6 views."""

    force_diffuse_materials: bool = True
    """Same metallicFactor neutralisation as :class:`Trellis2ServiceConfig`.
    The multi-view fork shares the same texturing pipeline and exhibits
    the same near-pure-metal artefact on stylised inputs."""

    diffuse_roughness_factor: float = 0.85
    """``roughnessFactor`` applied alongside ``force_diffuse_materials``."""


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
# Agent loop (Agent Loop v2)
# ---------------------------------------------------------------------------


class AgentVoiceConfig(BaseSettings):
    """Voice-turn tuning for the model-driven loop."""

    model_config = SettingsConfigDict(env_prefix="ALICE_AGENT__VOICE__")

    max_tools: int = 8
    """Cap on the number of tools exposed in voice turns, for latency.

    Voice interactions favour a fast, terse reply over broad tool
    coverage; trimming the toolset keeps the first token quick."""


class AgentReflectionConfig(BaseSettings):
    """Optional self-check (reflection) for the model-driven loop.

    Reflection is the lightweight, opt-in replacement for structured mode's
    per-step critic: instead of grading every step, a single verification
    pass runs on the final answer and surfaces a non-blocking warning when
    the output looks degenerate. It costs one extra LLM call on the turns
    it covers, so it is OFF by default.
    """

    model_config = SettingsConfigDict(env_prefix="ALICE_AGENT__REFLECTION__")

    enabled: bool = False
    """Run a reflection (self-check) pass on the final answer (opt-in)."""

    tool_turns_only: bool = True
    """When True, only verify turns that actually used tools (where a mistake
    is most likely); when False, verify every turn."""

    max_output_tokens: int = 80
    """Cap on the reflection LLM response (verdict + brief reason)."""

    temperature: float = 0.0
    """Sampling temperature for the reflection call (0.0 = deterministic)."""

    fail_open: bool = True
    """On LLM/parse error, treat the answer as OK so the user is not blocked."""

    degeneration_detector_enabled: bool = True
    """If True, run a local rule-based degeneration detector BEFORE the LLM
    call.  Saves one round-trip when an obvious pathological output
    (paragraph repetition, inline ``<tool_code>`` / fake JSON tool calls,
    ``finish_reason=length``) is present."""


class AgentSubagentConfig(BaseSettings):
    """Runtime limits for the ``spawn_subagent`` delegation tool.

    The sub-agent runs **serially** (blocking) — a single local GPU
    serialises inference, so there is no benefit to parallel sub-agents.
    """

    model_config = SettingsConfigDict(env_prefix="ALICE_AGENT__SUBAGENT__")

    max_steps: int = 6
    """Hard cap on tool-call iterations inside a single sub-agent run."""

    max_output_tokens: int = 1024
    """Cap on the LLM output per sub-agent step."""

    timeout_seconds: float = 180.0
    """Wall-clock budget for an entire sub-agent run."""

    max_tools: int = 16
    """Maximum number of tools exposed to a sub-agent (after filtering)."""


class AgentPromptsConfig(BaseSettings):
    """User-customisable prompt overrides for the agentic chat path.

    Holds free-text that is layered onto the model's instructions:

    - :attr:`persona` is appended **globally** to every system prompt
      (after the base prompt, before any memory/MCP context), so the user
      can set a stable tone or set of standing instructions.
    - :attr:`tier_guidance` maps a permission-tier name to bespoke guidance
      text; an empty mapping means the hardcoded per-tier defaults are used
      elsewhere.

    Both default to empty, so an untouched install behaves exactly as before.
    """

    model_config = SettingsConfigDict(env_prefix="ALICE_AGENT__PROMPTS__")

    persona: str = ""
    """Free-text persona/instructions appended globally to the system prompt.

    Empty (the default) adds nothing. When set, the text is inserted as a
    ``## Istruzioni personalizzate`` block after the base prompt and before
    any memory context."""

    tier_guidance: dict[str, str] = Field(default_factory=dict)
    """Per-tier guidance overrides keyed by tier name.

    Keys are permission-tier strings (``"strict"``, ``"auto_edits"``,
    ``"plan"``, ``"autopilot"``); values are the guidance text shown for
    that tier. An empty mapping (the default) means the hardcoded per-tier
    defaults are used elsewhere."""


class AgentConfig(BaseSettings):
    """Configuration for the (only) model-driven agentic chat path.

    The model itself decides step-by-step what to do, with the
    ``update_tasks`` and ``spawn_subagent`` meta-tools for structure and an
    optional, non-blocking reflection pass on the final answer. There is no
    separate ``enabled`` switch and no legacy structured pipeline: the engine
    is always :class:`DirectTurnExecutor`, optionally wrapped by
    :class:`ReflectiveTurnExecutor` when :attr:`reflection` is enabled.
    """

    model_config = SettingsConfigDict(env_prefix="ALICE_AGENT__")

    planning: bool = True
    """Expose the ``update_tasks`` todo-list tool in the model-driven loop."""

    delegation: bool = True
    """Expose the ``spawn_subagent`` delegation tool in the model-driven loop."""

    clarification: bool = True
    """Expose the ``ask_user`` clarifying-question tool in the model-driven loop."""

    reflection: AgentReflectionConfig = Field(
        default_factory=AgentReflectionConfig
    )
    """Optional final-answer self-check (non-blocking reflection pass)."""

    subagent: AgentSubagentConfig = Field(default_factory=AgentSubagentConfig)
    """Runtime limits for ``spawn_subagent``."""

    voice: AgentVoiceConfig = Field(default_factory=AgentVoiceConfig)
    """Voice-turn tuning (e.g. tool cap for latency)."""

    prompts: AgentPromptsConfig = Field(default_factory=AgentPromptsConfig)
    """User-customisable prompt overrides (global persona + per-tier guidance)."""


# ---------------------------------------------------------------------------
# Legacy-key migration (shared by AliceConfig and the layered config service)
# ---------------------------------------------------------------------------

_LEGACY_AGENT_SCALAR_MAP = {
    "plan_enabled": "planning",
    "delegation_enabled": "delegation",
}
_LEGACY_AGENT_SUBAGENT_MAP = {
    "subagent_max_steps": "max_steps",
    "subagent_max_output_tokens": "max_output_tokens",
    "subagent_timeout_seconds": "timeout_seconds",
    "subagent_max_tools": "max_tools",
}
# Confirmation knobs promoted from ``pc_automation`` to the neutral
# ``permissions`` block in Fase 2. They are *moved* (popped) because every
# config model forbids unknown fields, so a stale key left under
# ``pc_automation`` would otherwise fail validation.
_LEGACY_PC_AUTOMATION_PERMISSION_KEYS = (
    "confirmations_enabled",
    "confirmation_timeout_s",
)


def _migrate_pc_automation_permissions(data: dict[str, Any]) -> None:
    """Fold legacy ``pc_automation`` confirmation keys into ``permissions``.

    Mutates ``data`` in place. Pops ``confirmations_enabled`` /
    ``confirmation_timeout_s`` out of any ``pc_automation`` block and moves
    them under ``permissions`` (an explicitly-set new key always wins). A
    no-op when neither legacy key is present.
    """
    pc_auto = data.get("pc_automation")
    if not isinstance(pc_auto, dict):
        return
    if not any(k in pc_auto for k in _LEGACY_PC_AUTOMATION_PERMISSION_KEYS):
        return

    permissions = data.get("permissions")
    if not isinstance(permissions, dict):
        permissions = {}

    for key in _LEGACY_PC_AUTOMATION_PERMISSION_KEYS:
        if key in pc_auto:
            value = pc_auto.pop(key)
            if key not in permissions:
                permissions[key] = value

    if permissions:
        data["permissions"] = permissions
    logger.info(
        "Migrated legacy 'pc_automation' confirmation keys into 'permissions'"
    )


# Dead flags removed in Fase 5 (never read by any consumer).  Stale keys
# persisted in system.yaml/user.yaml must be dropped per layer because
# every config model forbids unknown fields.
_REMOVED_LEGACY_KEYS: tuple[tuple[str, str], ...] = (
    ("voice", "voice_confirmation_enabled"),
    ("pc_automation", "enabled"),
    ("notifications", "sound_enabled"),
)


def _strip_removed_legacy_keys(data: dict[str, Any]) -> None:
    """Drop config keys removed in Fase 5 from a raw layer dict, in place."""
    for section, key in _REMOVED_LEGACY_KEYS:
        block = data.get(section)
        if isinstance(block, dict) and key in block:
            block.pop(key)
            logger.info(
                "Dropped removed legacy config key '{}.{}'", section, key,
            )


def migrate_legacy_config_keys(data: dict[str, Any]) -> dict[str, Any]:
    """Fold renamed legacy config keys into their current location, in place.

    The agentic-chat refactor unified the standalone ``agent_tools`` section
    into the :class:`AgentConfig` tree (``agent_tools.plan_enabled`` →
    ``agent.planning``, ``agent_tools.delegation_enabled`` →
    ``agent.delegation`` and ``agent_tools.subagent_*`` → ``agent.subagent.*``).
    A persisted ``system.yaml`` / ``user.yaml`` written by an older build can
    still carry the legacy block; because every config model forbids unknown
    fields, leaving it in place makes the whole config — and therefore the
    backend — fail to load.

    This helper is applied **per layer** by
    :class:`~backend.services.config_service.LayeredConfigService` *before* the
    layers are merged, so a user's legacy value lands in its own layer and
    wins over lower-precedence defaults exactly like a native ``agent.*`` key
    would. It is also wired as a ``model_validator(before)`` on
    :class:`AliceConfig` as a safety net for the runtime/env layer and direct
    construction (e.g. tests). Within a single dict, an explicitly-set new
    ``agent.*`` key always wins over a migrated legacy one.

    Args:
        data: A raw config dict (one layer, or the merged result). Mutated and
            returned; non-dict input is returned unchanged.

    Returns:
        The same dict with any ``agent_tools`` block folded into ``agent``.
    """
    if not isinstance(data, dict):
        return data

    # pc_automation → permissions (independent of the agent_tools block below).
    _migrate_pc_automation_permissions(data)
    _strip_removed_legacy_keys(data)

    legacy = data.pop("agent_tools", None)
    if not isinstance(legacy, dict):
        return data

    agent = data.get("agent")
    if not isinstance(agent, dict):
        agent = {}
        data["agent"] = agent
    subagent = agent.get("subagent")
    if not isinstance(subagent, dict):
        subagent = {}

    for old_key, value in legacy.items():
        if old_key in _LEGACY_AGENT_SCALAR_MAP:
            new_key = _LEGACY_AGENT_SCALAR_MAP[old_key]
            if new_key not in agent:
                agent[new_key] = value
        elif old_key in _LEGACY_AGENT_SUBAGENT_MAP:
            new_key = _LEGACY_AGENT_SUBAGENT_MAP[old_key]
            if new_key not in subagent:
                subagent[new_key] = value
        else:
            logger.warning("Dropping unrecognized legacy agent_tools key: {}", old_key)

    if subagent:
        agent["subagent"] = subagent
    logger.info("Migrated legacy 'agent_tools' config block into 'agent'")
    return data


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
    permissions: PermissionsConfig = Field(
        default_factory=PermissionsConfig
    )
    commands: CommandsConfig = Field(default_factory=CommandsConfig)
    attention: AttentionConfig = Field(default_factory=AttentionConfig)
    """Agent→user initiative policy (Fase 8)."""
    triggers: TriggersConfig = Field(default_factory=TriggersConfig)
    """Autonomous-turn trigger policy (Fase 8)."""
    scope: WorkspaceScopeConfig = Field(default_factory=WorkspaceScopeConfig)
    terminal: TerminalConfig = Field(default_factory=TerminalConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
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
    qdrant: QdrantConfig = Field(default_factory=QdrantConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    continuum: ContinuumConfig = Field(default_factory=ContinuumConfig)
    mcp: McpConfig = Field(default_factory=McpConfig)
    trellis: TrellisServiceConfig = Field(default_factory=TrellisServiceConfig)
    trellis2: Trellis2ServiceConfig = Field(default_factory=Trellis2ServiceConfig)
    # Field name kept lower-camel-ish (no underscore between "2" and
    # "multiview") so it matches the managed-service name used in URL
    # routes (``/api/services/trellis2multiview/...``) and lets the
    # generic config endpoint resolve the section via ``getattr``.
    trellis2multiview: Trellis2MultiviewServiceConfig = Field(
        default_factory=Trellis2MultiviewServiceConfig
    )
    chart: ChartConfig = Field(default_factory=ChartConfig)
    whiteboard: WhiteboardConfig = Field(default_factory=WhiteboardConfig)
    email: EmailConfig = Field(default_factory=EmailConfig)
    network_probe: NetworkProbeConfig = Field(
        default_factory=NetworkProbeConfig
    )

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_keys(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Safety-net legacy-key migration for direct construction / env layer.

        Delegates to :func:`migrate_legacy_config_keys`. The primary migration
        happens per-layer in the layered config service (so values keep their
        layer precedence); this validator covers direct ``AliceConfig(**d)``
        construction (e.g. tests) and the runtime/env layer.
        """
        return migrate_legacy_config_keys(data)

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

        # -- continuum agent prompt file (resolve relative to PROJECT_ROOT) --
        continuum_data = data.get("continuum")
        if isinstance(continuum_data, dict):
            raw_prompt = continuum_data.get(
                "agent_prompt_file", "config/continuum_agent_prompt.md"
            )
            if raw_prompt and not Path(raw_prompt).is_absolute():
                continuum_data["agent_prompt_file"] = str(
                    PROJECT_ROOT / raw_prompt
                )

        # -- qdrant path (resolve relative to PROJECT_ROOT) --
        qdrant_data = data.get("qdrant")
        if isinstance(qdrant_data, dict):
            raw_path = qdrant_data.get("path", "")
            if raw_path and not Path(raw_path).is_absolute():
                qdrant_data["path"] = str(PROJECT_ROOT / raw_path)

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
