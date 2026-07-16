"""Tests for the config writability/secret policy."""

from __future__ import annotations

from backend.services.config_policy import (
    SECRET_PATHS,
    is_preference_writable,
    is_secret_path,
)


def test_secret_paths_census_is_closed() -> None:
    assert frozenset({
        "llm.api_token",
        "llm.openrouter_api_key",
        "home_assistant.token",
        "mqtt.password",
        "continuum.api_token",
        "email.password",
    }) == SECRET_PATHS


def test_secret_paths_are_never_preference_writable() -> None:
    for path in SECRET_PATHS:
        assert is_secret_path(path)
        assert not is_preference_writable(path)


def test_known_preference_paths_are_writable() -> None:
    for path in (
        "tts.engine", "stt.model", "voice.wake_word", "ui.theme",
        "email.username", "email.imap_port", "agent.prompts.persona",
        "permissions.confirmations_enabled", "llm.provider",
        "llm.openrouter_model", "llm.openrouter_favorites",
        "llm.temperature", "llm.max_tokens", "llm.model",
        "llm.supports_thinking", "llm.supports_vision",
        "llm.user_preferred_name", "llm.disabled_tools",
        "llm.tools_enabled", "llm.system_prompt_enabled",
        "llm.max_tool_iterations", "llm.context_compression_enabled",
        "llm.context_compression_threshold",
        "llm.context_compression_reserve",
        "llm.tool_rag_enabled", "llm.tool_rag_top_k",
    ):
        assert is_preference_writable(path), path


def test_out_of_policy_paths_are_rejected() -> None:
    for path in (
        "server.port",            # non è una preferenza utente
        "llm.base_url",           # infrastruttura, layer user/system
        "email.use_keyring",      # campo eliminato
        "database.url",
        "bogus.section",
    ):
        assert not is_preference_writable(path), path
