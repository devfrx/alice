"""AL\\CE — Typed response models for the config routes.

Modeled EXACTLY on the dict currently built by ``get_config`` in
``config.py`` — field names/types must stay in lockstep with that
function body. A drift here silently changes the wire shape consumed by
the generated frontend contract and the ratchet test in
``tests/contracts/test_response_models.py``.
"""

from __future__ import annotations

from pydantic import BaseModel


class LLMSection(BaseModel):
    """``GET /api/config`` ``llm`` section."""

    provider: str
    base_url: str
    model: str
    temperature: float
    max_tokens: int
    supports_thinking: bool
    supports_vision: bool
    max_tool_iterations: int
    context_compression_enabled: bool
    context_compression_threshold: float
    context_compression_reserve: int
    tool_rag_enabled: bool
    tool_rag_top_k: int
    user_preferred_name: str
    openrouter_api_key_configured: bool
    openrouter_model: str
    openrouter_favorites: list[str]


class STTSection(BaseModel):
    """``GET /api/config`` ``stt`` section."""

    engine: str
    model: str
    language: str | None
    device: str
    enabled: bool


class TTSSection(BaseModel):
    """``GET /api/config`` ``tts`` section."""

    engine: str
    voice: str
    sample_rate: int
    enabled: bool
    speed: float
    kokoro_model: str
    kokoro_voices: str
    kokoro_voice: str
    kokoro_language: str


class UISection(BaseModel):
    """``GET /api/config`` ``ui`` section."""

    theme: str
    language: str


class VoiceSection(BaseModel):
    """``GET /api/config`` ``voice`` section."""

    auto_tts_response: bool
    activation_mode: str
    wake_word: str


class PCAutomationSection(BaseModel):
    """``GET /api/config`` ``pc_automation`` section.

    Storage moved to the neutral ``permissions`` block in Fase 2; the
    response keeps the historical shape for the settings UI.
    """

    confirmations_enabled: bool
    screenshot_lockout_s: int


class EmailSection(BaseModel):
    """``GET /api/config`` ``email`` section (without ``use_keyring``)."""

    enabled: bool
    imap_host: str
    imap_port: int
    imap_ssl: bool
    smtp_host: str
    smtp_port: int
    smtp_ssl: bool
    username: str
    fetch_last_n: int
    max_fetch: int
    imap_idle_enabled: bool
    archive_folder: str
    password_configured: bool
    service_running: bool


class ConfigResponse(BaseModel):
    """``GET /api/config`` and ``PUT /api/config`` response shape."""

    llm: LLMSection
    stt: STTSection
    tts: TTSSection
    ui: UISection
    voice: VoiceSection
    pc_automation: PCAutomationSection
    email: EmailSection
