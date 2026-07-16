"""Tests for backend.core.config."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

from backend.core.config import (
    DEFAULT_MODEL,
    KNOWN_MODELS,
    PROJECT_ROOT,
    AliceConfig,
    EmailConfig,
    LLMConfig,
    STTConfig,
    TTSConfig,
    UIConfig,
    VoiceConfig,
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
    # No exact-count assert: it was a change-detector that went stale on
    # every plugin addition. The invariant that matters is no duplicates.
    assert len(enabled) == len(set(enabled))


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


# ---------------------------------------------------------------------------
# PUT /config — email password lands in the SecretStore (Task 5)
# ---------------------------------------------------------------------------


async def test_email_password_lands_in_secret_store(client, app) -> None:
    ctx = app.state.context
    resp = await client.put(
        "/api/config",
        json={"email": {"username": "u@example.com", "password": "s3cret"}},
    )
    assert resp.status_code == 200
    assert ctx.secret_store.cached()["email.password"] == "s3cret"
    assert resp.json()["email"]["password_configured"] is True
    assert "use_keyring" not in resp.json()["email"]


async def test_removed_legacy_key_is_dropped_not_rejected(client) -> None:
    """A removed-legacy path (Task 11 review Finding 1) must not 400 the PUT.

    The FE cleanup for ``email.use_keyring`` happens in a later task; until
    then every auto-save PUT still sends it. A removed-legacy key is a
    distinct class from an unknown path — the system itself deprecated it —
    so it is silently dropped instead of rejecting the whole request.
    """
    resp = await client.put(
        "/api/config",
        json={"email": {"use_keyring": False, "imap_port": 995}, "ui": {"theme": "light"}},
    )
    assert resp.status_code == 200
    assert resp.json()["email"]["imap_port"] == 995
    assert resp.json()["ui"]["theme"] == "light"


# ---------------------------------------------------------------------------
# Overlay in-place → layer (audit I1)
# ---------------------------------------------------------------------------


async def test_sync_model_survives_config_rebuild(client, app) -> None:
    """sync-model scrive il layer preferences: un rebuild non lo perde più."""
    ctx = app.state.context

    class _StubManager:
        async def list_models(self) -> dict[str, Any]:
            return {
                "models": [{
                    "key": "org/synced-model",
                    "loaded_instances": [{"id": "i1"}],
                    "capabilities": {"thinking": True, "vision": False},
                }],
            }

    saved = ctx.lmstudio_manager
    ctx.lmstudio_manager = _StubManager()
    try:
        resp = await client.post("/api/config/sync-model")
        assert resp.status_code == 200
        assert resp.json() == {"synced": True, "model": "org/synced-model"}
        assert ctx.config.llm.model == "org/synced-model"
        assert ctx.config.llm.supports_thinking is True

        # Prima: object.__setattr__ in-place, clobberato dal primo rebuild.
        rebuilt = await ctx.config_service.rebuild()
        assert rebuilt.llm.model == "org/synced-model"

        prefs = await ctx.preferences_store.load()
        assert prefs["llm"]["model"] == "org/synced-model"
    finally:
        ctx.lmstudio_manager = saved


async def test_plugin_toggle_survives_config_rebuild(client, app) -> None:
    """Il toggle plugin scrive il layer runtime: un rebuild non lo perde più."""
    ctx = app.state.context
    target = "system_info"
    if target not in ctx.config.plugins.enabled:
        pytest.skip("system_info not enabled in the test app")

    resp = await client.patch(f"/api/plugins/{target}", json={"enabled": False})
    assert resp.status_code == 200
    assert target not in ctx.config.plugins.enabled

    # Prima: lista mutata in-place, clobberata dal primo rebuild.
    rebuilt = await ctx.config_service.rebuild()
    assert target not in rebuilt.plugins.enabled


# ---------------------------------------------------------------------------
# PUT /config misto — tutta la validazione PRIMA di ogni commit
# (audit Triage#1 / Triage#4)
# ---------------------------------------------------------------------------


async def test_mixed_put_invalid_pref_does_not_commit_secret(client, app) -> None:
    """Un segreto valido non deve atterrare se la parte preferenze 422a."""
    ctx = app.state.context
    resp = await client.put(
        "/api/config",
        json={"llm": {"temperature": 99, "openrouter_api_key": "sk-or-must-not-land"}},
    )
    assert resp.status_code == 422
    assert "llm.openrouter_api_key" not in ctx.secret_store.cached()


async def test_mixed_put_oversize_secret_does_not_commit_pref(client, app) -> None:
    """Una preferenza valida non deve atterrare se il segreto 400a."""
    ctx = app.state.context
    resp = await client.put(
        "/api/config",
        json={"ui": {"theme": "light"}, "llm": {"openrouter_api_key": "x" * 600}},
    )
    assert resp.status_code == 400
    prefs = await ctx.preferences_store.load()
    assert prefs.get("ui", {}).get("theme") != "light"


async def test_secret_update_without_store_returns_503(client, app) -> None:
    """Store segreti assente = 503 esplicito, non un 200 silenzioso."""
    ctx = app.state.context
    saved = ctx.secret_store
    ctx.secret_store = None
    try:
        resp = await client.put(
            "/api/config",
            json={"ui": {"theme": "light"}, "llm": {"openrouter_api_key": "sk-or-x"}},
        )
        assert resp.status_code == 503
        # Pre-flight: neanche la parte preferenze del body misto è atterrata.
        prefs = await ctx.preferences_store.load()
        assert prefs.get("ui", {}).get("theme") != "light"
    finally:
        ctx.secret_store = saved


# ---------------------------------------------------------------------------
# PUT /config — nested bodies flatten to leaf paths (audit M2)
# ---------------------------------------------------------------------------


def test_flatten_update_body_recurses_to_leaves() -> None:
    from backend.api.routes.config import _flatten_update_body

    flat = _flatten_update_body(
        {"agent": {"reflection": {"enabled": True}, "planning": False}},
    )
    assert flat == {"agent.reflection.enabled": True, "agent.planning": False}


def test_flatten_update_body_preserves_list_values() -> None:
    from backend.api.routes.config import _flatten_update_body

    flat = _flatten_update_body({"llm": {"openrouter_favorites": ["org/model"]}})
    assert flat == {"llm.openrouter_favorites": ["org/model"]}


def test_flatten_update_body_empty_dict_is_noop() -> None:
    from backend.api.routes.config import _flatten_update_body

    assert _flatten_update_body({"agent": {"prompts": {}}}) == {}


def test_flatten_update_body_non_dict_section_rejected() -> None:
    from fastapi import HTTPException

    from backend.api.routes.config import _flatten_update_body

    with pytest.raises(HTTPException):
        _flatten_update_body({"ui": 5})


async def test_put_three_level_body_persists_leaf_rows(client, app) -> None:
    ctx = app.state.context
    resp = await client.put(
        "/api/config", json={"agent": {"reflection": {"enabled": True}}},
    )
    assert resp.status_code == 200
    assert ctx.config.agent.reflection.enabled is True
    # The persisted row is the LEAF path — no dict-valued intermediate row.
    assert await ctx.preferences_store.delete_paths(["agent.reflection.enabled"]) == 1


# ---------------------------------------------------------------------------
# PUT /config rewritten on the unified engine (Task 11)
# ---------------------------------------------------------------------------


async def test_unknown_path_returns_400_with_the_paths(client) -> None:
    resp = await client.put(
        "/api/config", json={"llm": {"bogus_key": 1}, "nonsense": {"x": 2}},
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "llm.bogus_key" in str(detail)
    assert "nonsense.x" in str(detail)


async def test_invalid_value_returns_422(client) -> None:
    resp = await client.put("/api/config", json={"llm": {"temperature": 99}})
    assert resp.status_code == 422


async def test_put_persists_only_sent_paths(client, app) -> None:
    ctx = app.state.context
    resp = await client.put("/api/config", json={"ui": {"theme": "light"}})
    assert resp.status_code == 200
    prefs = await ctx.preferences_store.load()
    assert prefs == {"ui": {"theme": "light"}}


async def test_patch_persona_does_not_clobber_preferences(client, app) -> None:
    """Il test di regressione split-brain: oggi sarebbe rosso su main."""
    ctx = app.state.context
    seed = await client.put(
        "/api/config", json={"llm": {"provider": "openrouter"}},
    )
    assert seed.status_code == 200
    patch = await client.patch(
        "/api/config",
        json={"path": "agent.prompts.persona", "value": "Sii conciso."},
    )
    assert patch.status_code == 200
    # la resolved config conserva la preferenza DB dopo il rebuild da PATCH
    assert ctx.config.llm.provider == "openrouter"


async def test_patch_defaults_to_preferences_layer(client, app) -> None:
    ctx = app.state.context
    resp = await client.patch(
        "/api/config", json={"path": "ui.theme", "value": "light"},
    )
    assert resp.status_code == 200
    prefs = await ctx.preferences_store.load()
    assert prefs["ui"]["theme"] == "light"


# ---------------------------------------------------------------------------
# Declarative field constraints (Task 8) — replace hand-rolled route checks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("model_cls", "field", "bad"),
    [
        (LLMConfig, "temperature", 2.5),
        (LLMConfig, "temperature", -0.1),
        (LLMConfig, "max_tokens", 0),
        (LLMConfig, "max_tokens", -2),
        (LLMConfig, "max_tool_iterations", 0),
        (LLMConfig, "max_tool_iterations", 101),
        (LLMConfig, "context_compression_threshold", 0.4),
        (LLMConfig, "context_compression_threshold", 0.96),
        (LLMConfig, "context_compression_reserve", 511),
        (LLMConfig, "context_compression_reserve", 8193),
        (LLMConfig, "tool_rag_top_k", 0),
        (LLMConfig, "tool_rag_top_k", 101),
        (LLMConfig, "user_preferred_name", "x" * 81),
        (LLMConfig, "model", ""),
        (LLMConfig, "model", "x" * 257),
        (LLMConfig, "openrouter_model", "x" * 257),
        (LLMConfig, "provider", "bogus"),
        (STTConfig, "device", "tpu"),
        (STTConfig, "model", ""),
        (STTConfig, "language", "x" * 11),
        (TTSConfig, "engine", "espeak"),
        (TTSConfig, "speed", 0.4),
        (TTSConfig, "speed", 2.1),
        (TTSConfig, "sample_rate", 12345),
        (TTSConfig, "voice", ""),
        (UIConfig, "theme", "sepia"),
        (UIConfig, "language", ""),
        (VoiceConfig, "activation_mode", "telepathy"),
        (VoiceConfig, "wake_word", ""),
        (EmailConfig, "imap_port", 0),
        (EmailConfig, "imap_port", 65536),
        (EmailConfig, "fetch_last_n", 0),
        (EmailConfig, "fetch_last_n", 501),
        (EmailConfig, "max_fetch", 501),
        (EmailConfig, "imap_host", "x" * 256),
    ],
)
def test_field_constraints_reject_bad_values(model_cls, field, bad) -> None:
    with pytest.raises(ValidationError):
        model_cls(**{field: bad})


def test_provider_is_normalized_lowercase() -> None:
    assert LLMConfig(provider="OpenRouter").provider == "openrouter"


def test_openrouter_favorites_capped_at_200() -> None:
    with pytest.raises(ValidationError):
        LLMConfig(openrouter_favorites=[f"m{i}" for i in range(201)])


# ---------------------------------------------------------------------------
# Strip/coercion normalizations restored at the model layer (Task 11 review
# Finding 2) — the old imperative PUT handler used to strip/coerce string
# inputs before storing them; now every ``set_many`` call runs full model
# validation, so the models themselves must canonicalize.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("model_cls", "field", "raw", "expected"),
    [
        (LLMConfig, "model", " my-model ", "my-model"),
        (LLMConfig, "user_preferred_name", None, ""),
        (LLMConfig, "user_preferred_name", " Jays ", "Jays"),
        (LLMConfig, "openrouter_model", None, ""),
        (EmailConfig, "imap_host", "imap.gmail.com ", "imap.gmail.com"),
        (EmailConfig, "username", " u@example.com ", "u@example.com"),
        (VoiceConfig, "wake_word", " alice ", "alice"),
        (UIConfig, "language", " it ", "it"),
        (TTSConfig, "voice", " path/to/voice ", "path/to/voice"),
    ],
)
def test_string_fields_are_normalized(model_cls, field, raw, expected) -> None:
    assert getattr(model_cls(**{field: raw}), field) == expected


def test_whitespace_only_model_rejected() -> None:
    with pytest.raises(ValidationError):
        LLMConfig(model="   ")


# ---------------------------------------------------------------------------
# Typed response model (Task 12)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_config_matches_response_model(client) -> None:
    resp = await client.get("/api/config")
    assert resp.status_code == 200
    body = resp.json()
    from backend.api.routes.config_schemas import ConfigResponse

    parsed = ConfigResponse.model_validate(body)
    assert parsed.llm.provider in ("lmstudio", "ollama", "openrouter")
    assert not hasattr(parsed.email, "use_keyring")
