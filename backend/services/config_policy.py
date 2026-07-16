"""AL\\CE — Config writability policy and secret-path census.

Single registry for (a) which dotted paths the UI may persist into the
``preferences`` layer and (b) which paths are secrets (keyring-only,
never in any layer). Successor of the old ``PERSISTABLE_SECTIONS`` /
``PERSISTABLE_LLM_KEYS`` / ``SENSITIVE_PREFERENCE_KEYS`` allowlists.
"""

from __future__ import annotations

SECRET_PATHS: frozenset[str] = frozenset({
    "llm.api_token",
    "llm.openrouter_api_key",
    "home_assistant.token",
    "mqtt.password",
    "continuum.api_token",
    "email.password",
})

# Sections whose every (non-secret) key is a user preference.
PREFERENCE_PREFIXES: tuple[str, ...] = (
    "tts.", "stt.", "voice.", "ui.", "plugins.", "web_search.",
    "calendar.", "weather.", "clipboard.", "notifications.",
    "media_control.", "file_search.", "news.", "agent.",
)

# Individual preference keys in sections that are NOT wholly writable.
PREFERENCE_EXACT_PATHS: frozenset[str] = frozenset({
    "permissions.confirmations_enabled",
    "llm.system_prompt_enabled",
    "llm.tools_enabled",
    "llm.max_tool_iterations",
    "llm.context_compression_enabled",
    "llm.context_compression_threshold",
    "llm.context_compression_reserve",
    "llm.tool_rag_enabled",
    "llm.tool_rag_top_k",
    "llm.disabled_tools",
    "llm.user_preferred_name",
    "llm.provider",
    "llm.model",
    "llm.temperature",
    "llm.max_tokens",
    "llm.supports_thinking",
    "llm.supports_vision",
    "llm.openrouter_model",
    "llm.openrouter_favorites",
    "email.enabled",
    "email.imap_host",
    "email.imap_port",
    "email.imap_ssl",
    "email.smtp_host",
    "email.smtp_port",
    "email.smtp_ssl",
    "email.username",
    "email.fetch_last_n",
    "email.max_fetch",
    "email.imap_idle_enabled",
    "email.archive_folder",
})


def is_secret_path(path: str) -> bool:
    """Return whether ``path`` designates a keyring-only secret."""
    return path in SECRET_PATHS


def is_preference_writable(path: str) -> bool:
    """Return whether the UI may persist ``path`` in the preferences layer."""
    if is_secret_path(path):
        return False
    if path in PREFERENCE_EXACT_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in PREFERENCE_PREFIXES)
