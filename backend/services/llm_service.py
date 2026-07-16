"""AL\\CE — LLM service facade for OpenAI-compatible APIs.

The historical monolith was split (Fase 5, spec §5.1) into
``backend/services/llm/``: :class:`~backend.services.llm.client.LLMClient`
(HTTP/streaming), :class:`~backend.services.llm.prompting.PromptBuilder`
(system-prompt + message assembly), and
:class:`~backend.services.llm.model_resolution.ModelResolver`
(``"auto"`` model resolution + capability profile).  ``LLMService`` stays
the single facade every consumer (turn engine, chat assembly, routes)
depends on — its public API is unchanged.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx
from loguru import logger

from backend.core.config import LLMConfig
from backend.services.llm.client import LLMClient
from backend.services.llm.model_resolution import ModelResolver
from backend.services.llm.prompting import PromptBuilder
from backend.services.model_capability_registry import ModelCapabilityRegistry


class LLMService:
    """Communicate with any OpenAI-compatible API (LM Studio, Ollama, etc.).

    Args:
        config: The ``LLMConfig`` holding provider URL, model name, etc.
        model_registry: Dynamic per-model capability registry.  When
            provided, per-request capability checks (thinking, vision,
            reasoning param) use the registry instead of static config
            flags.  Passing ``None`` preserves the legacy behaviour.
    """

    def __init__(
        self,
        config: LLMConfig,
        model_registry: ModelCapabilityRegistry | None = None,
    ) -> None:
        self._config = config
        self._model_registry = model_registry
        # Shared httpx client — owned here, injected into every
        # collaborator below. Kept as ``self._client`` (not ``self._http``)
        # because tests patch ``svc._client.get`` / ``svc._client.stream``
        # directly expecting the raw httpx client (see Deviazioni in the
        # Task 5 report).
        headers: dict[str, str] = {}
        if config.provider == "openrouter" and config.openrouter_api_key:
            headers = {
                "Authorization": f"Bearer {config.openrouter_api_key}",
                # Attribution opzionale OpenRouter (rankings).
                "HTTP-Referer": "https://github.com/devfrx/alice",
                "X-Title": "ALICE",
            }
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=config.connect_timeout,
                read=config.timeout,
                write=10.0,
                pool=10.0,
            ),
            headers=headers,
        )
        self._resolver = ModelResolver(config, model_registry, http=self._client)
        self._prompts = PromptBuilder(config)
        self._llm_client = LLMClient(
            config,
            http=self._client,
            resolver=self._resolver,
            model_registry=model_registry,
            prompts=self._prompts,
        )

        # ------------------------------------------------------------------
        # Context-window cache — kept directly on the facade (not delegated
        # to ModelResolver). ``tests/test_context_window_cache.py`` builds
        # an ``LLMService`` via ``LLMService.__new__`` (bypassing
        # ``__init__``) and pokes these attributes directly, then calls
        # ``get_cached_context_window`` / ``_refresh_context_window`` /
        # ``invalidate_context_window_cache`` on the instance. Delegating
        # to a collaborator that never gets constructed in that path would
        # break the (binding, unmodifiable) test — see Deviazioni.
        # ------------------------------------------------------------------
        # Non-blocking cache for the active model's context window. Read on the
        # chat turn-start / conversation-open hot paths; refreshed in the
        # background so those paths never await an LM Studio round-trip.
        self._ctx_window_cache: int | None = None
        self._ctx_window_expires: float = 0.0
        self._ctx_window_ttl: float = 300.0
        self._ctx_window_ttl_failure: float = 20.0
        self._default_ctx_window: int = 32768
        self._ctx_window_refreshing: bool = False
        self._refresh_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # Model resolution / capability — delegates to ModelResolver
    # ------------------------------------------------------------------

    @property
    def supports_vision(self) -> bool:
        """Whether the active model supports multimodal (vision) input."""
        return self._resolver.supports_vision

    def invalidate_model_cache(self) -> None:
        """Invalidate the cached auto-resolved model ID.

        Call this whenever the active model changes (load, unload,
        config update, sync) so the next chat request re-resolves the
        ``"auto"`` model against LM Studio's currently loaded set.
        """
        self._resolver.invalidate_model_cache()

    # -- test-compat aliases (backlog: migrate tests to ModelResolver) ------
    async def _resolve_model(self) -> str:
        return await self._resolver.resolve()

    _is_embedding_model = staticmethod(ModelResolver._is_embedding_model)
    _model_id = staticmethod(ModelResolver._model_id)
    _is_loaded = staticmethod(ModelResolver._is_loaded)

    # ------------------------------------------------------------------
    # System prompt / message building — delegates to PromptBuilder
    # ------------------------------------------------------------------

    def get_system_prompt(
        self,
        memory_context: str | None = None,
        *,
        persona: str | None = None,
    ) -> str:
        """Build the full system prompt with optional persona + memory context."""
        return self._prompts.get_system_prompt(memory_context, persona=persona)

    def get_scoped_system_prompt(
        self,
        base_prompt_path: str,
        memory_context: str | None = None,
    ) -> str:
        """Build a task-scoped system prompt from an ALTERNATE base file."""
        return self._prompts.get_scoped_system_prompt(base_prompt_path, memory_context)

    def build_messages(
        self,
        user_content: str,
        history: list[dict[str, Any]] | None = None,
        attachments: list[dict[str, str]] | None = None,
        memory_context: str | None = None,
        system_prompt: str | None = None,
    ) -> list[dict[str, Any]]:
        """Build a full message list with system prompt, history, and user msg."""
        return self._prompts.build_messages(
            user_content,
            history=history,
            attachments=attachments,
            memory_context=memory_context,
            system_prompt=system_prompt,
            supports_vision=self._resolver.supports_vision,
        )

    def build_continuation_messages(
        self,
        history: list[dict[str, Any]],
        memory_context: str | None = None,
        system_prompt: str | None = None,
    ) -> list[dict[str, Any]]:
        """Build messages for tool-loop continuation (no new user message)."""
        return self._prompts.build_continuation_messages(
            history, memory_context=memory_context, system_prompt=system_prompt,
        )

    def invalidate_system_prompt_cache(self) -> None:
        """Clear the cached system prompt so it is reloaded on next access."""
        self._prompts.invalidate_system_prompt_cache()

    # ------------------------------------------------------------------
    # Streaming / non-streaming chat — delegates to LLMClient
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        cancel_event: asyncio.Event | None = None,
        *,
        user_content: str | None = None,
        conversation_id: str | None = None,
        attachments: list[dict[str, str]] | None = None,
        memory_context: str | None = None,
        system_prompt: str | None = None,
        max_output_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream a chat completion, choosing the best backend."""
        async for event in self._llm_client.chat(
            messages,
            tools=tools,
            cancel_event=cancel_event,
            user_content=user_content,
            conversation_id=conversation_id,
            attachments=attachments,
            memory_context=memory_context,
            system_prompt=system_prompt,
            max_output_tokens=max_output_tokens,
            response_format=response_format,
            temperature=temperature,
        ):
            yield event

    async def complete_nonstreaming(
        self, messages: list[dict[str, Any]], max_tokens: int = 512,
    ) -> str:
        """Complete a chat request without streaming (for summarization)."""
        return await self._llm_client.complete_nonstreaming(messages, max_tokens)

    # ------------------------------------------------------------------
    # Context-window cache
    # ------------------------------------------------------------------

    def get_cached_context_window(self, lmstudio_manager: Any = None) -> int:
        """Return the active model's context window WITHOUT blocking.

        Serves the cached value (or the default) immediately. When the cache is
        empty or stale it schedules a background refresh so the *next* call is
        warm — the hot path (turn-start, conversation-open) never awaits LM Studio.
        For OpenRouter, the value comes from the capability registry (catalog)
        instead — no cache and no LM Studio probe involved.

        Args:
            lmstudio_manager: Optional LMStudioManager used by the background
                refresh to query loaded-model metadata.

        Returns:
            Context window size in tokens (cached, last-known, or the default).
        """
        # OpenRouter: the context window comes from the catalog (capability
        # registry), not an LM Studio probe. ``getattr`` guards against
        # ``tests/test_context_window_cache.py``, which builds the service
        # via ``LLMService.__new__`` and never sets ``_config``.
        config: LLMConfig | None = getattr(self, "_config", None)
        if config is not None and config.provider == "openrouter":
            model_registry: ModelCapabilityRegistry | None = getattr(
                self, "_model_registry", None,
            )
            if model_registry is not None:
                profile = model_registry.get_profile(
                    config.openrouter_model or "openrouter/auto",
                )
                if profile.context_length > 0:
                    return profile.context_length
            return self._default_ctx_window

        now = time.monotonic()
        if self._ctx_window_cache is not None and now < self._ctx_window_expires:
            return self._ctx_window_cache
        if lmstudio_manager is not None and not self._ctx_window_refreshing:
            self._ctx_window_refreshing = True
            try:
                loop = asyncio.get_running_loop()
                self._refresh_task = loop.create_task(
                    self._refresh_context_window(lmstudio_manager)
                )
                self._refresh_task.add_done_callback(
                    lambda _t: setattr(self, "_ctx_window_refreshing", False)
                )
            except RuntimeError:
                # No running loop (sync test context) — drop the refresh flag.
                self._ctx_window_refreshing = False
        return (
            self._ctx_window_cache
            if self._ctx_window_cache is not None
            else self._default_ctx_window
        )

    async def _refresh_context_window(self, lmstudio_manager: Any = None) -> None:
        """Refresh the cached context window from LM Studio (never raises)."""
        value = self._ctx_window_cache
        got_value = False
        try:
            if lmstudio_manager is not None:
                data = await lmstudio_manager.list_models()
                for model in data.get("models", []):
                    if model.get("type") == "embedding":
                        continue
                    instances = model.get("loaded_instances", [])
                    if instances:
                        ctx_len = instances[0].get("config", {}).get("context_length", 0)
                        if ctx_len > 0:
                            value = ctx_len
                            got_value = True
                            break
        except Exception as exc:
            logger.debug("Failed to refresh context window: {}", exc)
        if value is None:
            value = self._default_ctx_window
        self._ctx_window_cache = value
        # Fix 4 (minor): when the probe didn't yield a real value (LM Studio down or
        # no model loaded), expire sooner so recovery is fast instead of stuck 5 min.
        ttl = self._ctx_window_ttl if got_value else self._ctx_window_ttl_failure
        self._ctx_window_expires = time.monotonic() + ttl

    def invalidate_context_window_cache(self) -> None:
        """Drop the cached context window (call on model switch / config change)."""
        self._ctx_window_cache = None
        self._ctx_window_expires = 0.0
        self._ctx_window_refreshing = False

    async def get_active_context_window(self, lmstudio_manager: Any = None) -> int:
        """Back-compat async accessor: refresh if needed, then return the cache."""
        now = time.monotonic()
        if self._ctx_window_cache is None or now >= self._ctx_window_expires:
            await self._refresh_context_window(lmstudio_manager)
        return self.get_cached_context_window(lmstudio_manager)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the underlying httpx client and release caches."""
        await self._client.aclose()
        self._llm_client.clear_response_ids()
        self._resolver.invalidate_model_cache()
        logger.debug("LLMService httpx client closed")


# Re-exported for backward compatibility — historically defined in this
# module; several tests and a couple of call sites import it from here.
from backend.services.llm.prompting import normalize_history  # noqa: E402,F401
